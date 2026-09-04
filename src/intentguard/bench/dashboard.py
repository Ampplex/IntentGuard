"""Builds the dashboard page from a real run.

The template carries a single placeholder and this fills it with the JSON that
`export.py` produced by actually running the system. Keeping the data injection
here rather than fetching at page load means the page is one self-contained
file: it opens from disk, from a share link, or from a laptop with no network,
which is what a demo needs.

The stage gate is that the dashboard renders a real run rather than fixtures.
That is enforced by there being nowhere to put a fixture -- the placeholder is
replaced with export output or the build fails.
"""

from __future__ import annotations

import json
from pathlib import Path

PLACEHOLDER = "__DASHBOARD_DATA__"
ROOT = Path(__file__).resolve().parents[3]
DATA_PATH = ROOT / "data" / "dashboard.json"


def build(template: Path, out: Path, data_path: Path = DATA_PATH) -> Path:
    if not data_path.exists():
        raise FileNotFoundError(
            f"{data_path} is missing. Run `python -m intentguard.bench.export` first; "
            "the page is built from a real run and there is no fixture to fall back on."
        )
    html = template.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"{template} has no {PLACEHOLDER} to fill")

    run = json.loads(data_path.read_text(encoding="utf-8"))
    # Embedded rather than fetched, and escaped so a description containing a
    # closing script tag cannot end the block early. The merchant descriptions
    # in this data are hostile text by design.
    embedded = json.dumps(run, ensure_ascii=False).replace("</", "<\\/")
    out.write_text(html.replace(PLACEHOLDER, embedded), encoding="utf-8")
    return out


def main() -> None:
    import sys

    template = Path(sys.argv[1])
    out = Path(sys.argv[2])
    build(template, out)
    print(f"built {out} from {DATA_PATH.name} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
