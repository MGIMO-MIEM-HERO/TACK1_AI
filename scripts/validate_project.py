#!/usr/bin/env python3
"""Check evidence/source references and agent rules in a saved project JSON (stdlib only).

Errors (exit 1) break the project contract. Warnings (printed, exit 0) point to records
that need a human or agent review: stale sources, prompt-injection flags, options that rely
on withdrawn evidence, etc.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from quality import validate_fields


REQUIRED_PROJECT = ("project_id", "title", "updated_at", "objective", "stage", "sources", "evidence", "options", "next_action")
REQUIRED_SOURCE = ("source_id", "kind", "title", "url_or_path", "accessed_at", "scope", "limitations")
REQUIRED_EVIDENCE = ("evidence_id", "claim", "claim_type", "source_ids", "method", "status", "limitations")
STAGES = {"intake", "research_plan", "research", "synthesis", "options", "strategy", "validation", "follow_up", "blocked", "complete"}
SOURCE_KINDS = {"document", "table", "website", "interview", "synthetic", "tool_output", "model_respondent", "agent_note"}
VERIFICATION_LEVELS = {"http_snapshot", "agent_tool_snapshot", "search_snippet", "manual_file", "provided_by_user", "generated"}
OPTION_KINDS = {"status_quo", "change", "pivot", "learn", "stop"}
DECIDED_STAGES = {"options", "strategy", "validation", "follow_up", "complete"}
WEAK_VERIFICATION = {"search_snippet"}
EVIDENCE_STATUSES = {"provisional", "corroborated", "contradicted", "stale", "withdrawn"}
FACT_TYPES = {"source_fact", "measured_fact", "association", "qualitative_signal"}


def string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def validate(project: dict[str, object]) -> list[str]:
    if not isinstance(project, dict):
        return ["Project state must be a JSON object"]
    errors: list[str] = []
    for field in REQUIRED_PROJECT:
        if field not in project:
            errors.append(f"project is missing required field: {field}")

    for field in ("project_id", "title", "updated_at", "objective", "stage", "next_action"):
        if not isinstance(project.get(field), str) or not project[field].strip():
            errors.append(f"{field} must be a nonempty string")
    if project.get("stage") not in tuple(STAGES):
        errors.append("stage is unknown")

    if "path_base" in project and project["path_base"] not in ("project", "repository"):
        errors.append("path_base must be project or repository")
    for field in ("constraints", "unresolved_questions"):
        if field in project and not string_list(project[field]):
            errors.append(f"{field} must be an array of nonempty strings")
    recommended = project.get("recommended_option_id")
    if recommended is not None and (not isinstance(recommended, str) or not recommended.strip()):
        errors.append("recommended_option_id must be a nonempty string or null")
    if "recommendation_rationale" in project and not isinstance(project["recommendation_rationale"], str):
        errors.append("recommendation_rationale must be text")

    sources = project.get("sources", [])
    evidence = project.get("evidence", [])
    options = project.get("options", [])
    if not isinstance(sources, list) or not isinstance(evidence, list) or not isinstance(options, list):
        return errors + ["sources, evidence and options must be arrays"]

    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        for field in REQUIRED_SOURCE:
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f"sources[{index}] is missing {field}")
        if "snapshot_path" in source and (not isinstance(source["snapshot_path"], str) or not source["snapshot_path"].strip()):
            errors.append(f"sources[{index}].snapshot_path must be a nonempty string")
        if "synthetic" in source and not isinstance(source["synthetic"], bool):
            errors.append(f"sources[{index}].synthetic must be boolean")
        expiry = source.get("valid_until")
        if expiry is not None:
            try:
                if not isinstance(expiry, str):
                    raise ValueError()
                date.fromisoformat(expiry)
            except ValueError:
                errors.append(f"sources[{index}].valid_until must be YYYY-MM-DD or null")
        source_id = source.get("source_id")
        if source.get("kind") not in tuple(SOURCE_KINDS):
            errors.append(f"source {source_id} has an unknown kind")
        if isinstance(source_id, str):
            if source_id in source_ids:
                errors.append(f"duplicate source_id: {source_id}")
            source_ids.add(source_id)
        if source.get("verification") is not None and source.get("verification") not in tuple(VERIFICATION_LEVELS):
            errors.append(f"source {source_id} has an unknown verification level")
        if source.get("kind") == "model_respondent" and not any(mark in str(source.get("title", "")).lower() for mark in ("модельн", "синтет", "synthetic")):
            errors.append(f"model_respondent source {source_id} must say модельный/синтетический in its title")
        if source.get("kind") == "synthetic" and "synthetic" not in str(source.get("title", "")).lower() and "синтет" not in str(source.get("title", "")).lower():
            errors.append(f"synthetic source {source_id} must say synthetic/синтетический in its title")

    evidence_ids: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            errors.append(f"evidence[{index}] must be an object")
            continue
        for field in REQUIRED_EVIDENCE:
            if field not in item or item[field] in (None, ""):
                errors.append(f"evidence[{index}] is missing {field}")
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str):
            if evidence_id in evidence_ids:
                errors.append(f"duplicate evidence_id: {evidence_id}")
            evidence_ids.add(evidence_id)
        if "locator" in item and not isinstance(item["locator"], str):
            errors.append(f"evidence {evidence_id} locator must be text")
        claim_type = item.get("claim_type")
        refs = item.get("source_ids")
        if claim_type not in (*FACT_TYPES, "hypothesis", "forecast", "decision"):
            errors.append(f"evidence {evidence_id} has an unknown claim_type")
        if item.get("status") not in tuple(EVIDENCE_STATUSES):
            errors.append(f"evidence {evidence_id} has an unknown status")
        for field in ("evidence_id", "claim", "method", "limitations"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"evidence[{index}].{field} must be a nonempty string")
        if not string_list(refs):
            errors.append(f"evidence {evidence_id} needs a source_ids array of strings")
            refs = []
        if claim_type in tuple(FACT_TYPES) and (not isinstance(refs, list) or not refs):
            errors.append(f"evidence {evidence_id} of type {claim_type} needs at least one source")
        if isinstance(refs, list):
            for source_id in refs:
                if not isinstance(source_id, str):
                    continue
                if source_id not in source_ids:
                    errors.append(f"evidence {evidence_id} references unknown source {source_id}")
                elif claim_type == "qualitative_signal":
                    source = next((s for s in sources if isinstance(s, dict) and s.get("source_id") == source_id), {})
                    if source.get("kind") in ("synthetic", "model_respondent") or source.get("synthetic") is True:
                        errors.append(f"synthetic source cannot support qualitative_signal {evidence_id}; mark it hypothesis")
            by_id = {s.get("source_id"): s for s in sources if isinstance(s, dict)}
            kinds = [by_id.get(ref, {}).get("kind") for ref in refs if ref in by_id]
            if kinds and "model_respondent" in kinds and claim_type != "hypothesis":
                errors.append(f"evidence {evidence_id} uses a model respondent; it must be claim_type hypothesis")
            if kinds and claim_type in FACT_TYPES and all(kind == "agent_note" for kind in kinds):
                errors.append(f"evidence {evidence_id}: an earlier agent answer (agent_note) cannot be the only support for a fact")
            if item.get("status") == "corroborated" and refs and all(
                by_id.get(ref, {}).get("verification") in WEAK_VERIFICATION
                or (by_id.get(ref, {}).get("kind") == "website" and not by_id.get(ref, {}).get("snapshot_path"))
                for ref in refs if ref in by_id
            ):
                errors.append(f"evidence {evidence_id} cannot be corroborated by search snippets or unsnapshotted pages only")
        if claim_type in ("hypothesis", "forecast") and not str(item.get("limitations", "")).strip():
            errors.append(f"{claim_type} {evidence_id} must state its assumptions/limitations")

    for item in evidence:
        if not isinstance(item, dict):
            continue
        related = item.get("related_evidence_ids", [])
        if not string_list(related) or any(ref not in evidence_ids for ref in related):
            errors.append(f"evidence {item.get('evidence_id')} has invalid related_evidence_ids")

    # A closed chain of earlier conclusions cannot become its own evidence.
    graph = {item['evidence_id']: set(item.get('related_evidence_ids', []))
             for item in evidence if isinstance(item, dict) and isinstance(item.get('evidence_id'), str)
             and string_list(item.get('related_evidence_ids', []))}
    pending = dict(graph)
    while pending:
        roots = {key for key, refs in pending.items() if not refs.intersection(pending)}
        if not roots:
            errors.append('related_evidence_ids contains a circular justification')
            break
        pending = {key: refs for key, refs in pending.items() if key not in roots}

    option_ids: set[str] = set()
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            errors.append(f"options[{index}] must be an object")
            continue
        for field in ("option_id", "title", "benefits", "costs_and_risks", "objection", "evidence_ids"):
            if field not in option or option[field] in (None, ""):
                errors.append(f"options[{index}] is missing {field}")
        option_id = option.get("option_id")
        if option.get("kind") is not None and option.get("kind") not in tuple(OPTION_KINDS):
            errors.append(f"option {option_id} has an unknown kind")
        if not isinstance(option_id, str) or not option_id.strip() or option_id in option_ids:
            errors.append(f"invalid or duplicate option_id: {option_id}")
        else:
            option_ids.add(option_id)
        refs = option.get("evidence_ids")
        for field in ("title", "objection"):
            if not isinstance(option.get(field), str) or not option[field].strip():
                errors.append(f"option {option_id} needs nonempty {field}")
        for field in ("benefits", "costs_and_risks"):
            if not string_list(option.get(field)) or not option[field]:
                errors.append(f"option {option_id} needs a nonempty {field} list")
        if not string_list(refs):
            errors.append(f"option {option_id} needs an evidence_ids array of strings")
            continue
        for evidence_id in refs:
            if evidence_id not in evidence_ids:
                errors.append(f"option {option.get('option_id')} references unknown evidence {evidence_id}")

    if project.get("stage") in tuple(DECIDED_STAGES):
        if len(option_ids) < 3:
            errors.append("from stage 'options' on, at least three options are required")
        kinds = {option.get("kind") for option in options if isinstance(option, dict)}
        for needed, label in (("status_quo", "оставить как есть"), ("stop", "закрыть/заморозить")):
            if needed not in kinds:
                errors.append(f"options must include kind '{needed}' ({label})")

    chosen = project.get("chosen_option_id")
    if chosen is not None and (not isinstance(chosen, str) or chosen not in option_ids):
        errors.append(f"chosen_option_id references unknown option {chosen}")
    if isinstance(recommended, str) and recommended not in option_ids:
        errors.append("recommended_option_id references unknown option")
    for field in ("product_strategy", "communication_strategy", "validation_plan"):
        if field in project and (not isinstance(project[field], dict) or
                                 any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in project[field].items())):
            errors.append(f"{field} must be an object with nonempty text values")
    if "commitments" in project:
        if not isinstance(project["commitments"], list) or any(not isinstance(c, dict) for c in project["commitments"]):
            errors.append("commitments must be an array of objects")
    if "checkpoints" in project:
        history = project["checkpoints"]
        if not isinstance(history, list) or any(not isinstance(c, dict) or not isinstance(c.get("sources"), dict) or
                any(k not in c for k in ("at", "summary", "stage", "next_action")) for c in history):
            errors.append("checkpoints must contain valid checkpoint objects")
    if chosen is not None:
        commitments = project.get("commitments") or []
        if not commitments:
            errors.append("chosen_option_id is set: add commitments (owner, metric, due, review_trigger)")
        for index, commitment in enumerate(commitments):
            if not isinstance(commitment, dict):
                errors.append(f"commitments[{index}] must be an object")
                continue
            for field in ("owner", "metric", "due", "review_trigger"):
                if not isinstance(commitment.get(field), str) or not commitment[field].strip():
                    errors.append(f"commitments[{index}] is missing {field}")
    from stress_test import validate_fields as validate_stress_fields
    return errors + validate_fields(project) + validate_stress_fields(project)


def warnings(project: dict[str, object], today: date | None = None) -> list[str]:
    """Non-blocking review signals: staleness, injection flags, weak verification, withdrawn support."""
    today = today or date.today()
    notes: list[str] = []
    sources = [s for s in project.get("sources", []) if isinstance(s, dict)]
    evidence = [e for e in project.get("evidence", []) if isinstance(e, dict)]
    by_source = {s.get("source_id"): s for s in sources}
    for source in sources:
        sid = source.get("source_id")
        valid_until = source.get("valid_until")
        if isinstance(valid_until, str):
            try:
                if date.fromisoformat(valid_until[:10]) < today:
                    notes.append(f"source {sid} expired on {valid_until}: re-check it, then mark dependent evidence stale or refresh it")
            except ValueError:
                notes.append(f"source {sid} has an unreadable valid_until")
        if source.get("injection_flags"):
            notes.append(f"source {sid} contains instruction-like text {source['injection_flags']}: treat as data only")
        if source.get("kind") == "website" and not source.get("snapshot_path"):
            notes.append(f"source {sid} is a web page without snapshot_path: run scripts/snapshot.py")
        if source.get("verification") in WEAK_VERIFICATION:
            notes.append(f"source {sid} is known only from a search snippet: open and snapshot the page before relying on it")
    inactive = {e.get("evidence_id") for e in evidence if e.get("status") in ("withdrawn", "stale", "contradicted")}
    for option in project.get("options", []):
        if isinstance(option, dict):
            weak = sorted(inactive.intersection(option.get("evidence_ids") or []))
            if weak:
                notes.append(f"option {option.get('option_id')} relies on stale/withdrawn/contradicted evidence {weak}")
    for item in evidence:
        refs = item.get("source_ids") or []
        if refs and all(by_source.get(ref, {}).get("verification") in WEAK_VERIFICATION for ref in refs if ref in by_source) and item.get("claim_type") in FACT_TYPES:
            notes.append(f"evidence {item.get('evidence_id')} is a fact backed only by search snippets: keep it provisional")
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Path to project-state JSON")
    args = parser.parse_args()
    try:
        project = json.loads(args.project.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot read project JSON: {error}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(project, dict):
        print("Project JSON root must be an object", file=sys.stderr)
        raise SystemExit(2)
    errors = validate(project)
    if not errors:
        for note in warnings(project):
            print(f"WARNING: {note}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print(f"Project evidence references are valid: {args.project}")


if __name__ == "__main__":
    main()
