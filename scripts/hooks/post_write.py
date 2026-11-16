#!/usr/bin/env python3
"""PostToolUse hook (Write/Edit): validate project.json and log file writes to the project ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import ROOT, project_for, read_event


def main() -> None:
    event = read_event()
    tool_input = event.get("tool_input") or {}
    raw_path = tool_input.get("file_path")
    if not raw_path:
        return
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    project = project_for(path)
    if project is None or path.name == "ledger.jsonl":
        return
    try:
        from ledger import append
        append(project, {"step": "file_write", "action": f"{event.get('tool_name', 'Write')} {path.relative_to(project.parent).as_posix()}",
                         "status": "done", "actor": "hook", "tool": event.get("tool_name", "Write")})
    except Exception as error:  # a broken ledger must not stop work; report it to the agent
        print(f"Ledger hook failed: {error}", file=sys.stderr)
    if path.name == "project.json":
        from validate_project import validate, warnings
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"project.json is not valid JSON: {error}. Fix it before continuing.", file=sys.stderr)
            raise SystemExit(2)
        errors = validate(data) if isinstance(data, dict) else ["root must be an object"]
        if errors:
            print("validate_project failed:\n" + "\n".join(f"- {e}" for e in errors), file=sys.stderr)
            raise SystemExit(2)
        notes = warnings(data)
        if notes:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                  "additionalContext": "validate_project warnings:\n" + "\n".join(f"- {n}" for n in notes)}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
