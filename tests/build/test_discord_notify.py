"""The Discord pager: what it sends, when it stays quiet, and that it stays wired.

scripts/ci/notify_discord.py is the one path from automation to the
maintainer, and scripts/ci/workflow_alert.py decides which finished runs use
it. The properties pinned here are the ones whose failure is silent:

  * text can never ping @everyone or a role, however a branch or commit is named;
  * the webhook secret can only ever post to Discord;
  * a missing webhook or a Discord outage never fails the job that notified;
  * notify.yml still watches workflows that exist — `workflow_run` matches on
    `name:`, so a renamed workflow would drop out without a single red check.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts" / "ci"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
NOTIFY_WORKFLOW = WORKFLOWS / "notify.yml"
WEBHOOK = "https://discord.com/api/webhooks/123/abc"


def _load(name: str) -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


notify = _load("notify_discord")
alert = _load("workflow_alert")


class _Recorder:
    """A stand-in for urlopen that records requests and replays outcomes."""

    def __init__(self, outcomes: list[Exception | None]) -> None:
        self.outcomes = outcomes
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return io.BytesIO(b"")


class _HTTPError(urllib.error.HTTPError):
    """An HTTPError with a body and no underlying file to leak on teardown."""

    def __init__(self, code: int, body: bytes) -> None:
        super().__init__(WEBHOOK, code, "err", Message(), None)
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        return self._body


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return _HTTPError(code, body)


# ── notify_discord ──────────────────────────────────────────────────────────


def test_text_can_never_mention_anyone_by_default() -> None:
    payload = notify.build_payload(
        notify.Notification(level="failure", title="@everyone dev failed")
    )
    assert payload["allowed_mentions"] == {"parse": []}
    assert "content" not in payload


def test_the_only_mention_is_the_configured_user() -> None:
    payload = notify.build_payload(
        notify.Notification(level="failure", title="x", mention_user_id="424242")
    )
    assert payload["content"] == "<@424242>"
    assert payload["allowed_mentions"] == {"parse": [], "users": ["424242"]}


def test_a_non_numeric_mention_id_is_refused() -> None:
    with pytest.raises(ValueError):
        notify.build_payload(
            notify.Notification(level="info", title="x", mention_user_id="@here")
        )


def test_embed_fields_are_clipped_to_discords_limits() -> None:
    payload = notify.build_payload(
        notify.Notification(
            level="info",
            title="t" * 300,
            body="b" * 5000,
            fields=tuple((f"n{i}", "v" * 2000) for i in range(30)),
        )
    )
    embed = payload["embeds"][0]
    assert len(embed["title"]) == notify.TITLE_LIMIT
    assert len(embed["description"]) == notify.DESCRIPTION_LIMIT
    assert len(embed["fields"]) == notify.FIELD_COUNT_LIMIT
    assert all(len(f["value"]) == notify.FIELD_VALUE_LIMIT for f in embed["fields"])


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/1/a",
        "https://evil.example/api/webhooks/1/a",
        "https://discord.com.evil.example/api/webhooks/1/a",
        "https://discord.com/api/v10/users/@me",
    ],
)
def test_the_webhook_secret_can_only_post_to_discord(url: str) -> None:
    with pytest.raises(ValueError):
        notify.validate_webhook_url(url)


def test_a_missing_webhook_is_a_quiet_no_op() -> None:
    recorder = _Recorder([])
    assert (
        notify.send(
            notify.Notification(level="info", title="x"), env={}, opener=recorder
        )
        is False
    )
    assert recorder.requests == []


def test_a_rate_limit_is_retried_after_discords_delay() -> None:
    recorder = _Recorder([_http_error(429, b'{"retry_after": 0.25}'), None])
    slept: list[float] = []
    assert (
        notify.deliver(WEBHOOK, {"embeds": []}, opener=recorder, sleep=slept.append)
        is True
    )
    assert slept == [0.25]
    assert len(recorder.requests) == 2


def test_a_client_error_is_dropped_without_retrying() -> None:
    recorder = _Recorder([_http_error(404)])
    assert (
        notify.deliver(WEBHOOK, {"embeds": []}, opener=recorder, sleep=lambda _: None)
        is False
    )
    assert len(recorder.requests) == 1


def test_an_outage_never_fails_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(notify.WEBHOOK_ENV, WEBHOOK)
    monkeypatch.setattr(
        notify,
        "_default_opener",
        _Recorder([urllib.error.URLError("down")] * notify.MAX_ATTEMPTS),
    )
    monkeypatch.setattr(notify.time, "sleep", lambda _: None)
    assert notify.main(["--title", "x"]) == 0


# ── workflow_alert ──────────────────────────────────────────────────────────


def _run(**overrides: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "name": "Dev CI",
        "event": "push",
        "head_branch": "dev",
        "conclusion": "failure",
        "head_sha": "0123456789abcdef",
        "html_url": "https://github.com/BlkLeg/CircuitBreaker/actions/runs/1",
        "head_commit": {"message": "fix: something\n\nbody"},
    }
    run.update(overrides)
    return run


def test_a_failure_on_dev_alerts() -> None:
    note = alert.decide(_run(), previous_conclusion="success")
    assert note is not None and note.level == "failure"
    assert note.title == "Dev CI failed on dev"
    assert note.body == "fix: something"


def test_a_failed_nightly_alerts_whatever_its_branch() -> None:
    assert alert.decide(_run(event="schedule", head_branch="feature"), "") is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "pull_request"},
        {"event": "push", "head_branch": "dependabot/pip/x"},
        {"conclusion": "cancelled"},
        {"conclusion": "success"},
    ],
)
def test_proposals_cancellations_and_steady_green_stay_quiet(
    overrides: dict[str, Any],
) -> None:
    assert alert.decide(_run(**overrides), previous_conclusion="success") is None


def test_green_after_red_is_a_recovery() -> None:
    note = alert.decide(_run(conclusion="success"), previous_conclusion="failure")
    assert note is not None and note.level == "success"
    assert "recovered" in note.title


def test_the_event_file_drives_a_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"workflow_run": _run()}), encoding="utf-8")
    assert alert.main(["--event-path", str(event), "--dry-run"]) == 0
    assert "notification: Dev CI failed on dev" in capsys.readouterr().out


# ── notify.yml stays wired ──────────────────────────────────────────────────


def _notify_workflow() -> dict[Any, Any]:
    return yaml.safe_load(NOTIFY_WORKFLOW.read_text(encoding="utf-8"))


def _trigger(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as boolean True.
    return workflow.get("on") or workflow[True]


def test_every_watched_name_is_a_workflow_that_exists() -> None:
    names = {
        yaml.safe_load(path.read_text(encoding="utf-8")).get("name")
        for path in WORKFLOWS.glob("*.yml")
    }
    watched = _trigger(_notify_workflow())["workflow_run"]["workflows"]
    missing = sorted(set(watched) - names)
    assert not missing, (
        f"notify.yml watches {missing}, which no workflow is named. `workflow_run` "
        "matches on `name:`, so these would never notify. Update the list."
    )


def test_the_release_workflow_is_watched() -> None:
    assert "Release" in _trigger(_notify_workflow())["workflow_run"]["workflows"]


def test_notify_never_checks_out_the_watched_runs_code() -> None:
    for step in _notify_workflow()["jobs"]["notify"]["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert "ref" not in (step.get("with") or {}), (
                "notify.yml must check out its own default branch only"
            )


def test_the_webhook_reaches_scripts_only_through_env() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        for job in (
            yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}
        ).values():
            for step in job.get("steps") or []:
                assert "secrets.DISCORD" not in str(step.get("run", "")), (
                    f"{path.name}: a Discord secret is interpolated into a run: block; pass it through env:"
                )
