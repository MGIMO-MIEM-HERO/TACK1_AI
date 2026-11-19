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

from validate_project import validate, warnings


ROOT = Path(__file__).resolve().parents[1]


def fingerprint(path: str, root: Path) -> str:
    if urlsplit(path).scheme in {"http", "https"}:
        return "remote: save a local snapshot to detect edits"
    root = root.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        return "outside project workspace"
    if not candidate.is_file():
        return "missing"
    digest = hashlib.sha256()
    # Git can translate LF to CRLF at checkout. Compare text content, not OS line endings.
    if candidate.suffix.lower() in {".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".html", ".htm", ".py", ".yaml", ".yml", ".toml"}:
        with candidate.open(encoding="utf-8", newline=None) as source:
            for chunk in iter(lambda: source.read(65536), ""):
                digest.update(chunk.encode("utf-8"))
    else:
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


def ledger_summary(project_path: Path) -> dict:
    """Unfinished/failed actions and known cost from ledger.jsonl, so a new chat does not repeat work."""
    try:
        from ledger import key_states, read_entries, ledger_path, summarize, verify
        entries = read_entries(ledger_path(project_path))
    except (ImportError, OSError, ValueError) as error:
        return {"error": str(error)}
    if not entries:
        return {"entries": 0}
    states = key_states(entries)
    totals = summarize(entries)["totals"]
    return {
        "entries": len(entries),
        "last_action": {key: entries[-1].get(key) for key in ("seq", "at", "step", "action", "status")},
        "unfinished_actions": sorted(key for key, value in states.items() if value.get("status") == "started"),
        "failed_actions": sorted(key for key, value in states.items() if value.get("status") == "failed"),
        "cost_usd_known": round(totals["cost_usd"], 4),
        "model_actions_with_unknown_cost": totals["cost_unknown_actions"],
        "chain_intact": not verify(entries),
    }


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


def save_checkpoint(project, path, summary, *, reviewed_changes=False, change_review=None,
                    initial_tracking=False, expected=None):
    """Shared checkpoint writer. A change assessment is not a human decision."""
    import copy
    from material_changes import enabled, source_versions, checkpoint_fields, snapshot as capture_snapshot
    from ledger import append, read_entries, ledger_path, verify
    base = path.parent if project.get('path_base') == 'project' else ROOT
    versions = source_versions(project, base)
    history = project.get('checkpoints', [])
    previous = history[-1]['sources'] if history else {}
    changed = {sid for sid in set(previous) | set(versions) if previous.get(sid) != versions.get(sid)} if history else set()
    if changed and not reviewed_changes and not initial_tracking:
        raise ValueError('Sources changed. Run resume, reassess affected evidence and options, then save with --reviewed-changes.')
    if verify(read_entries(ledger_path(path))): raise ValueError('Damaged ledger; inspect it before saving a checkpoint')
    if json.loads(path.read_text(encoding='utf-8-sig')) != (project if expected is None else expected):
        raise ValueError('Project changed; reload before checkpoint save')
    fields = checkpoint_fields(project, path, ROOT, change_review, initial=initial_tracking) if enabled(project) else {}
    if enabled(project) and (fields['change_snapshot'] != capture_snapshot(project, path, ROOT)
                             or versions != source_versions(project, base)):
        raise ValueError('Sources changed while assessing; read and prepare again')
    now = datetime.now(timezone.utc); candidate = copy.deepcopy(project)
    candidate.setdefault('checkpoints', []).append({'at': now.isoformat(timespec='seconds'), 'stage': project['stage'],
        'summary': summary, 'next_action': project['next_action'], 'sources': versions, **fields})
    candidate['updated_at'] = now.date().isoformat()
    errors = validate(candidate)
    if errors: raise ValueError('; '.join(errors))
    write_state(path, candidate)
    try:
        append(path, {'step': project['stage'], 'action': 'checkpoint: ' + summary, 'status': 'done',
                      'actor': 'script', 'tool': 'scripts/checkpoint.py', 'source_ids': sorted(changed),
                      'note': 'Impact assessment only, no human approval.' if fields else 'reviewed source changes' if reviewed_changes else None})
    except (OSError, ValueError) as error:
        raise ValueError('Checkpoint saved but ledger append failed; inspect before retrying: ' + str(error)) from error
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    resume = commands.add_parser("resume")
    resume.add_argument('--as-of', help='Offset-aware replay clock; read-only')
    impact = commands.add_parser("impact", help="list evidence/options that depend on given sources or evidence")
    impact.add_argument("--source-ids", default="")
    impact.add_argument("--evidence-ids", default="")
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
        from material_changes import source_versions, inspect as inspect_changes
        fingerprints = source_versions(project, base)
        history = project.get("checkpoints", [])
        previous = history[-1]["sources"] if history else {}
        changed = {key for key in previous.keys() | fingerprints.keys() if previous.get(key) != fingerprints.get(key)} if history else set()
        evidence, options = impacted(project, changed)
        if args.command == "impact":
            sources = {item.strip() for item in args.source_ids.split(",") if item.strip()}
            seeds = {item.strip() for item in args.evidence_ids.split(",") if item.strip()}
            evidence_hit, options_hit = impacted(project, sources)
            if seeds:
                # Treat the named evidence as if its source changed, then follow related_evidence_ids.
                marked = [dict(item, source_ids=item["source_ids"] + (["__seed__"] if item["evidence_id"] in seeds else []))
                          for item in project["evidence"]]
                more_e, more_o = impacted({"evidence": marked, "options": project["options"]}, {"__seed__"})
                evidence_hit = sorted(set(evidence_hit) | set(more_e))
                options_hit = sorted(set(options_hit) | set(more_o))
            print(json.dumps({"evidence_to_reassess": evidence_hit, "options_to_reassess": options_hit,
                              "chosen_option_affected": project.get("chosen_option_id") in options_hit}, ensure_ascii=False, indent=2))
            return
        if args.command == "resume":
            from stress_test import inspect as inspect_stress
            from claims_audit import inspect as inspect_claims
            from research_selection import inspect as inspect_research
            from follow_up import inspect as inspect_follow_up, instant
            from feasibility import inspect as inspect_feasibility
            ledger_state = ledger_summary(path)
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
                "review_warnings": warnings(project),
                "decision_stress_test": inspect_stress(project, path, ROOT),
                "marketing_claims_audit": inspect_claims(project, path, ROOT),
                "research_selection": inspect_research(project, path, ROOT),
                "feasibility": inspect_feasibility(project, path, ROOT),
                "material_changes": inspect_changes(project, path, ROOT),
                "follow_up": inspect_follow_up(project, path, ROOT,
                                               at=instant(args.as_of) if args.as_of else None),
                "ledger": ledger_state,
                "reminder": "Earlier agent conclusions in this file are records to re-check, not facts. Trust only evidence with sources.",
            }, ensure_ascii=False, indent=2))
            return
        save_checkpoint(project, path, args.summary, reviewed_changes=args.reviewed_changes)
        print(f"Saved checkpoint for {project['stage']}")
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        parser.exit(1, f"Checkpoint: {error}\n")


if __name__ == "__main__":
    main()
