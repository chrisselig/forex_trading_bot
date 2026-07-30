"""Fail if any top-level docs/research/*.md is not referenced in mkdocs.yml.

Reports were repeatedly merged to the repo but never added to the MkDocs nav,
so they silently never appeared on the GitHub Pages site (reports 15, 16, 17
all hit this). This guard makes that a CI failure: every reader-facing research
doc must be wired into the site.

The internal specs/ subdirectory is intentionally excluded — those are
implementation specs the pipeline follows, not reader-facing documentation.

Dependency-free on purpose (plain substring check, no YAML parser) so it runs
in the lint-and-test job without pulling mkdocs into that environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "docs" / "research"
MKDOCS = REPO_ROOT / "mkdocs.yml"


def main() -> int:
    nav_text = MKDOCS.read_text(encoding="utf-8")
    # Top-level research docs only (not the specs/ subdirectory).
    docs = sorted(p.name for p in RESEARCH_DIR.glob("*.md"))
    orphans = [name for name in docs if f"research/{name}" not in nav_text]
    if orphans:
        print("ERROR: docs/research files missing from mkdocs.yml nav:")
        for name in orphans:
            print(f"  - docs/research/{name}")
        print(
            "\nAdd each under the 'Analysis' nav section in mkdocs.yml "
            "(or move it into docs/research/specs/ if it is an internal spec, "
            "not a published doc)."
        )
        return 1
    print(f"OK: all {len(docs)} docs/research/*.md files are referenced in mkdocs.yml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
