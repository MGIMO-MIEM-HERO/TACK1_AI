#!/usr/bin/env python3
"""Stop hook: remind once to save a checkpoint when project.json changed after the last checkpoint."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from _common import ROOT, all_projects, last_checkpoint, read_event

GRACE_SECONDS = 10


def main() -> None:
    event = read_event()
    if event.get("stop_hook_active"):
        return  # never loop: the reminder is shown at most once per stop
    stale = []
    for path in all_projects():
        try:
            project = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        saved = last_checkpoint(project)
        if saved is None or (modified - saved).total_seconds() > GRACE_SECONDS:
            stale.append(path.relative_to(ROOT).as_posix())
    if stale:
        commands = "; ".join(f'python3 scripts/checkpoint.py {p} save --summary "..."' for p in stale)
        print(json.dumps({"decision": "block", "reason":
              f"project.json changed after the last checkpoint: {', '.join(stale)}. Save progress so a new chat can resume: {commands}. "
              "If sources changed, run resume first and add --reviewed-changes after reassessing. If nothing worth saving changed, say so and stop."},
              ensure_ascii=False))


if __name__ == "__main__":
    main()
