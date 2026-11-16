#!/usr/bin/env python3
"""Save research progress and identify conclusions affected by changed source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from validate_project import validate


ROOT = Path(__file__).resolve().parents[1]


def fingerprint(path: str, root: Path) -> str:
    if urlsplit(path).scheme in {"http", "https"}:
        return "remote: save a local snapshot to detect edits"
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        return "outside project workspace"
    if not candidate.is_file():
        return "missing"
    digest = hashlib.sha256()
    with candidate.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def impacted(project: dict, changed: set[str]) -> tuple[list[str], list[str]]:
    affected = {item["evidence_id"] for item in project["evidence"] if changed.intersection(item["source_ids"])}
    while True:
        dependent = {
            item["evidence_id"] for item in project["evidence"]
            if affected.intersection(item.get("related_evidence_ids", []))
        }
        if dependent <= affected:
            break
        affected |= dependent
    options = sorted(item["option_id"] for item in project["options"] if affected.intersection(item["evidence_ids"]))
    return sorted(affected), options


def write_state(path: Path, project: dict) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(project, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("resume")
    save = commands.add_parser("save")
    save.add_argument("--summary", required=True)
    save.add_argument("--reviewed-changes", action="store_true")
    args = parser.parse_args()

    try:
        path = args.project.resolve()
        project = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(project, dict):
            raise ValueError("Project state must be a JSON object")
        errors = validate(project)
        if errors:
            raise ValueError("\n".join(errors))
        base = path.parent if project.get("path_base") == "project" else ROOT
        fingerprints = {
            source["source_id"]: {
                "location": source["url_or_path"],
                "fingerprint": fingerprint(source.get("snapshot_path") or source["url_or_path"], base),
            }
            for source in project["sources"]
        }
        history = project.get("checkpoints", [])
        previous = history[-1]["sources"] if history else {}
        changed = {key for key in previous.keys() | fingerprints.keys() if previous.get(key) != fingerprints.get(key)} if history else set()
        evidence, options = impacted(project, changed)
        if args.command == "resume":
            print(json.dumps({
                "stage": project["stage"],
                "last_checkpoint": {key: history[-1][key] for key in ("at", "summary")} if history else None,
                "next_action": project["next_action"],
                "changed_source_ids": sorted(changed),
                "evidence_to_reassess": evidence,
                "options_to_reassess": options,
                "sources_without_fingerprint": {
                    key: item["fingerprint"] for key, item in fingerprints.items() if len(item["fingerprint"]) != 64
                },
            }, ensure_ascii=False, indent=2))
            return
        if changed and not args.reviewed_changes:
            raise ValueError("Sources changed. Run resume, reassess affected evidence and options, then save with --reviewed-changes.")
        now = datetime.now(timezone.utc)
        history.append({
            "at": now.isoformat(timespec="seconds"),
            "stage": project["stage"],
            "summary": args.summary,
            "next_action": project["next_action"],
            "sources": fingerprints,
        })
        project["checkpoints"] = history
        project["updated_at"] = now.date().isoformat()
        write_state(path, project)
        print(f"Saved checkpoint for {project['stage']}")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f"Checkpoint: {error}\n")


if __name__ == "__main__":
    main()
