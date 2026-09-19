"""A `<td>` must never carry a class that changes its `display`.

`.fleet-num` (styles/agents.css) sets `display: inline-block` so a number can be
right-aligned in a fixed-width box next to its sparkline. On a `<span>` inside a
cell that is exactly right, and `MetricCell` uses it that way. It was also put
on two `<td>` elements directly — the version cell and the uptime cell — and
`display: inline-block` on a table cell takes that cell out of table layout
altogether. The browser dropped both from the column grid, so version and uptime
collapsed together and every metric cell after them rendered one column to the
left of its own header: memory's number sat under CPU, network's under Disk,
temperature's under Net. The fleet table silently mislabelled every metric an
operator reads.

Nothing caught it. The rendered tests count DOM nodes, and jsdom performs no
layout at all, so `<td>` count still equalled `<th>` count and every assertion
passed while the real page was wrong. A layout bug that no layout engine runs in
CI can only be caught as a source rule, which is what this is.

The rule is deliberately narrow: it names the classes whose CSS actually changes
`display`, rather than trying to parse the stylesheet. Add a class here if you
add another that does the same thing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = REPO_ROOT / "apps" / "frontend" / "src"

#: Classes whose rule sets a non-table `display`. Applying one to a <td> or <th>
#: removes that cell from its table's column grid.
DISPLAY_CHANGING_CLASSES = ("fleet-num",)

#: Any <td ...> or <th ...> opening tag, with its attributes.
_CELL_TAG = re.compile(r"<(td|th)\s([^>]*)>", re.DOTALL)
_CLASS_ATTR = re.compile(r'className="([^"]*)"')


def _offenders(text: str, class_name: str) -> list[str]:
    found = []
    for match in _CELL_TAG.finditer(text):
        attrs = match.group(2)
        class_match = _CLASS_ATTR.search(attrs)
        if not class_match:
            continue
        if class_name in class_match.group(1).split():
            found.append(f"<{match.group(1)} className=\"{class_match.group(1)}\">")
    return found


def _jsx_files() -> list[Path]:
    return sorted(COMPONENTS.rglob("*.jsx"))


@pytest.mark.parametrize("class_name", DISPLAY_CHANGING_CLASSES)
def test_no_table_cell_carries_a_display_changing_class(class_name: str):
    assert COMPONENTS.is_dir(), f"{COMPONENTS} is missing"
    offenders: dict[str, list[str]] = {}
    for path in _jsx_files():
        found = _offenders(path.read_text(), class_name)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found

    assert not offenders, (
        f"`{class_name}` sets a non-table `display`, so a <td>/<th> carrying it "
        f"leaves the table's column grid and every cell after it shifts under "
        f"the wrong header. Put it on a <span> inside the cell instead, the way "
        f"MetricCell does: {offenders}"
    )


def test_the_rule_would_catch_the_defect_it_was_written_for():
    """The guard is only worth having if it fails on the original shape."""
    regressed = '<td className="fleet-cell fleet-num">{agent.agent_version}</td>'
    assert _offenders(regressed, "fleet-num")
    corrected = '<td className="fleet-cell"><span className="fleet-num">x</span></td>'
    assert not _offenders(corrected, "fleet-num")
