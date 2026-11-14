#!/usr/bin/env python3
"""PreToolUse hook (Write/Edit): block secrets and writes to .env files before they reach disk."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from _common import read_event

SECRET_PATTERNS = {
    "anthropic_key": r"sk-ant-[A-Za-z0-9_\-]{20,}",
    "openai_style_key": r"\bsk-(proj-)?[A-Za-z0-9]{32,}",
    "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "slack_token": r"\bxox[abpr]-[A-Za-z0-9-]{10,}",
    "private_key": r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "assigned_secret": r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
}


def main() -> None:
    event = read_event()
    tool_input = event.get("tool_input") or {}
    path = str(tool_input.get("file_path") or "")
    name = Path(path).name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        print("Blocked: .env files hold local secrets and are not written by the agent. Ask the user to edit them.", file=sys.stderr)
        raise SystemExit(2)
    text = "\n".join(str(tool_input.get(key) or "") for key in ("content", "new_string"))
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            text += "\n" + str(edit.get("new_string") or "")
    hits = [label for label, pattern in SECRET_PATTERNS.items() if re.search(pattern, text)]
    if hits:
        print(f"Blocked: content looks like a secret ({', '.join(hits)}). Secrets stay in the user's environment, never in the repository.", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
