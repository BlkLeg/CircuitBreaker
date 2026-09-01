"""Repo-policy checks on the Phase 2 baseline harness and wedge instrument.

These exist because the harness's own output is the only place its mistakes
show, and a mistake there looks exactly like a quiet result. Three of the checks
below encode a bug that shipped: a scrape URL that 404s, a nightly job that
skipped the only tier its targets apply to, and a wedge spec whose evidence did
not distinguish a stuck router from a stuck harness.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/baseline.yml"
LOADGEN = ROOT / "scripts/loadgen"
SPEC = ROOT / "apps/frontend/e2e/nav-wedge.spec.ts"
PLAYWRIGHT_CONFIG = ROOT / "apps/frontend/playwright.config.ts"


def _strip_js_comments(source: str) -> str:
    """Drop `//` and `/* */` comments so prose cannot satisfy or trip a rule.

    The comments in `nav-wedge.spec.ts` name the exact APIs the checks below
    forbid, because they explain why those APIs are forbidden. Matching against
    raw text would fail the build for documenting the rule.
    """
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _baseline_job() -> dict[str, Any]:
    return _workflow()["jobs"]["baseline"]


def test_workload_tiers_match_the_route_contract() -> None:
    """The tier shapes are route §5's workload matrix, not a paraphrase of it."""
    from scripts.loadgen.config import TIERS

    assert TIERS == {
        "A": {
            "name": "Starter",
            "monitors": 10,
            "interval_seconds": 60,
            "browser_users": 1,
            "ws_clients": 2,
            "topology_entities": 25,
        },
        "B": {
            "name": "Enthusiast",
            "monitors": 50,
            "interval_seconds": 30,
            "browser_users": 2,
            "ws_clients": 5,
            "topology_entities": 150,
        },
        "C": {
            "name": "Advanced",
            "monitors": 200,
            "interval_seconds": 30,
            "browser_users": 5,
            "ws_clients": 10,
            "topology_entities": 500,
        },
    }


def test_target_evaluation_records_pass_fail_and_not_applicable() -> None:
    from scripts.loadgen.config import evaluate_targets

    passing = evaluate_targets("C", 1.9, 29)
    assert passing["monitor_lag_under_shortest_interval_at_tier_c"]["passed"] is True
    assert passing["topology_load_p95_under_2s_at_500_entities"]["passed"] is True

    failing = evaluate_targets("C", 2.1, 31)
    assert failing["topology_load_p95_under_2s_at_500_entities"]["passed"] is False
    assert failing["monitor_lag_under_shortest_interval_at_tier_c"]["passed"] is False

    not_applicable = evaluate_targets("A", 0.1, 1)
    assert not_applicable["monitor_lag_under_shortest_interval_at_tier_c"]["applicable"] is False
    assert not_applicable["monitor_lag_under_shortest_interval_at_tier_c"]["passed"] is None


def test_an_unmeasured_target_is_not_reported_as_a_failure() -> None:
    """`None` and `False` mean different things and must not be collapsed.

    A run whose metrics scrape failed measures nothing. Scoring that as a failed
    target would make a broken harness indistinguishable from a regressed
    product — which is exactly what a nightly baseline exists to tell apart.
    """
    from scripts.loadgen.config import evaluate_targets

    unmeasured = evaluate_targets("C", None, None)
    for target in unmeasured.values():
        assert target["applicable"] is True
        assert target["passed"] is None
        assert target["measured"] is None


def test_seed_refuses_a_production_looking_database() -> None:
    spec = importlib.util.spec_from_file_location("loadgen_seed", LOADGEN / "seed.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit, match="refusing non-test database"):
        module.assert_safe_database("postgresql://db/prod")
    module.assert_safe_database("postgresql://db/circuitbreaker_test")


def test_the_metrics_scrape_path_carries_the_prefix_twice() -> None:
    """`GET /api/v1/metrics` is a 404; the route is `/api/v1/metrics/metrics`.

    `app.api.metrics` is included under the `/api/v1/metrics` prefix *and*
    declares its own route as `/metrics`. docs/metrics.md documents this as a
    trap and the load generator fell into it: every scrape 404'd, so
    `event_loop_lag_seconds`, `monitor_scheduling_lag_seconds` and `db_pool`
    were null in every report while the runs themselves looked clean.
    """
    from scripts.loadgen.run import METRICS_PATH

    assert METRICS_PATH == "/api/v1/metrics/metrics"

    router_source = (ROOT / "apps/backend/src/app/api/metrics.py").read_text(encoding="utf-8")
    assert '@router.get(\n    "/metrics"' in router_source, (
        "app.api.metrics no longer declares its route as '/metrics'; if the "
        "route moved, METRICS_PATH has to move with it."
    )
    main_source = (ROOT / "apps/backend/src/app/main.py").read_text(encoding="utf-8")
    assert 'prefix=f"{_V1}/metrics"' in main_source, (
        "the metrics router's mount prefix changed; re-derive METRICS_PATH."
    )


def test_every_metric_the_report_reads_is_one_the_app_exports() -> None:
    """A result field wired to a metric that does not exist is always null.

    `db_pool` shipped reading `circuitbreaker_db_pool_checked_out` and
    `circuitbreaker_db_pool_size`, neither of which was defined anywhere in the
    backend — two permanently-null fields that read as "the pool was idle".
    """
    run_source = (LOADGEN / "run.py").read_text(encoding="utf-8")
    referenced = set(re.findall(r'"(circuitbreaker_[a-z0-9_]+)"', run_source))
    assert referenced, "run.py no longer names any metric; the report reads nothing"

    backend = ROOT / "apps/backend/src/app"
    defined = set()
    for path in backend.rglob("*.py"):
        defined.update(re.findall(r'"(circuitbreaker_[a-z0-9_]+)"', path.read_text(encoding="utf-8")))

    missing = sorted(name for name in referenced if name not in defined)
    assert not missing, (
        f"run.py reads metrics the backend never exports: {missing}. Those fields "
        "are null in every result document ever produced."
    )


def test_nightly_workflow_is_non_blocking_scheduled_and_retained() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert trigger["schedule"][0]["cron"] == "17 5 * * *"
    job = _baseline_job()
    assert job["continue-on-error"] is True
    upload = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] >= 30
    assert (LOADGEN / "run.py").exists()


def test_nightly_workflow_runs_every_tier_including_c() -> None:
    """Both defensible §5 targets are Tier C claims.

    Topology load is specified "at 500 entities" and monitor lag "at Tier C", so
    a nightly job that runs only A and B archives `applicable: false` for both,
    every night, forever — it accumulates evidence for nothing. This shipped
    that way.
    """
    from scripts.loadgen.config import TIERS

    steps = " ".join(str(step.get("run", "")) for step in _baseline_job()["steps"])
    tier_loop = re.search(r"for tier in ([A-C ]+); do", steps)
    assert tier_loop is not None, "the baseline job no longer loops over tiers"
    looped = set(tier_loop.group(1).split())
    assert looped == set(TIERS), (
        f"the nightly job runs tiers {sorted(looped)} but the harness defines "
        f"{sorted(TIERS)}; a tier that is never run evidences nothing."
    )


def test_nightly_workflow_generates_secrets_at_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CB_JWT_SECRET:" not in text and "CB_VAULT_KEY:" not in text
    assert "jwt_secret=$(openssl rand" in text
    assert "vault_key=$(openssl rand" in text
    assert "POSTGRES_PASSWORD=breaker" not in text
    assert "Baseline123" not in text


def test_nav_wedge_is_opt_in_and_writes_machine_readable_rate() -> None:
    config = PLAYWRIGHT_CONFIG.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert "testIgnore: /(visual|nav-wedge)" in config
    assert "name: 'nav-wedge'" in config
    assert "wedge-rate.json" in spec and "wedge_rate" in spec
    assert "Emulation.setCPUThrottlingRate" in spec


def test_nav_wedge_drives_the_router_rather_than_the_url_bar() -> None:
    """A synthetic `popstate` is not a navigation react-router has processed.

    The first revision pushed a URL and dispatched `PopStateEvent`. Its own
    recorded evidence contained no nav entry for either wedged target, meaning
    the router never ran — the URL had moved because `pushState` moved it. The
    journey has to go through the UI, where a dock `<NavLink>` click reaches
    react-router's own `navigate()`.
    """
    spec = _strip_js_comments(SPEC.read_text(encoding="utf-8"))
    assert "PopStateEvent" not in spec and "history.pushState" not in spec, (
        "nav-wedge drives navigation by synthetic history events again; that "
        "bypasses react-router and measures the harness."
    )
    assert "navigateByUi" in spec and "macos-dock-link" in spec, (
        "nav-wedge no longer clicks a dock link; that is the app's real "
        "navigation and the only click path known to reach the router here."
    )
    dock = (ROOT / "apps/frontend/src/components/MacOSDOCK.jsx").read_text(encoding="utf-8")
    assert "macos-dock-link" in dock and "<NavLink" in dock, (
        "the dock no longer renders NavLinks under .macos-dock-link; the wedge "
        "harness clicks that selector and would silently record ui-failures."
    )


def test_nav_wedge_separates_a_wedge_from_a_harness_failure() -> None:
    """The wedge count must exclude everything that is not a wedge.

    A missing route element means the Suspense fallback is showing, which is the
    opposite of the wedge signature; a navigation the router never opened is a
    UI or harness fault. Counting either as a wedge inflates the one number this
    spec exists to produce.
    """
    spec = SPEC.read_text(encoding="utf-8")
    for signal in ("routerSawNavigation", "ui_failures", "fallbacks", "wedges_with_pending_chunk"):
        assert signal in spec, f"nav-wedge no longer reports {signal}"
    assert "[data-route-path]" in spec, (
        "nav-wedge locates the rendered route by position again; the first child "
        "of .page-content is the update banner or the Suspense fallback, neither "
        "of which carries a route path."
    )


def test_nav_wedge_classifies_every_wedge_into_a_decision_tree_branch() -> None:
    """A bare wedge rate does not say which of three problems it found.

    The measured branches are materially different defects — a location update
    that never reached `useLocation`, a route that never mounted, and an exit
    animation that never finished — and §4.4 sends each somewhere different. A
    run that reports only a rate makes the investigation start over.

    This also guards the classification itself: a revision that treated "no nav
    entry" as a harness fault discarded every sample of the branch the known bug
    actually exhibits, and reported a wedge rate of zero while doing it.
    """
    spec = _strip_js_comments(SPEC.read_text(encoding="utf-8"))
    for branch in (
        "router-location-never-updated",
        "incoming-route-never-mounted",
        "outgoing-route-never-removed",
    ):
        assert branch in spec, f"nav-wedge no longer distinguishes the {branch} branch"
    assert "wedges_by_branch" in spec
    assert "renderedRoutes" in spec, (
        "nav-wedge records only the first route element again; two at once is "
        "how an unfinished framer-motion exit is told apart from a route that "
        "never rendered."
    )
