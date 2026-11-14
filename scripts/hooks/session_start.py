#!/usr/bin/env python3
"""SessionStart hook: tell the agent which projects exist, their stage, next action and unfinished actions."""

from __future__ import annotations

import json

from _common import ROOT, all_projects

from checkpoint import ledger_summary  # noqa: E402  (path set in _common)


def main() -> None:
    lines = []
    for path in all_projects():
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ledger = ledger_summary(path)
        unfinished = ledger.get("unfinished_actions") or []
        lines.append(f"- {path.relative_to(ROOT).as_posix()}: stage={project.get('stage')}; next={project.get('next_action')}"
                     + (f"; UNFINISHED actions in ledger: {unfinished}" if unfinished else ""))
    if lines:
        text = ("Projects in this repository (state from files, not memory). To continue one, use the resume skill "
                "or run `python3 scripts/checkpoint.py <project.json> resume`:\n" + "\n".join(lines))
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
