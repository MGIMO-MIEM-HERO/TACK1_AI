#!/usr/bin/env python3
"""Append-only action ledger for a project: what was done, on what basis, at what cost.

The ledger lives next to project.json as ledger.jsonl. Every line is one JSON entry that
contains the hash of the previous line, so silent edits or deletions are detectable with
`verify`. Idempotency keys (`begin` / `finish`) stop the agent from silently repeating an
action that already finished, and expose actions interrupted by a crash.

Commands:
  log      PROJECT --step S --action A [...]     record a finished action
  begin    PROJECT --key K --step S --action A   mark start; exit 3 if K already done,
                                                 exit 4 if K was interrupted (use --retry)
  finish   PROJECT --key K [--status done|failed] [...]
  status   PROJECT                               keys and their last status; pending ones
  verify   PROJECT                               check the hash chain
  report   PROJECT [--out FILE]                  cost/time report by step, tool and model
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRICES = ROOT / "config" / "model_prices.json"
GENESIS = "0" * 64
EXIT_ALREADY_DONE = 3
EXIT_INTERRUPTED = 4

try:  # POSIX advisory lock; on Windows we fall back to a plain append.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def ledger_path(project: Path) -> Path:
    project = Path(project)
    return (project.parent if project.suffix == ".json" else project) / "ledger.jsonl"


def canonical(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def entry_hash(entry: dict) -> str:
    body = {key: value for key, value in entry.items() if key != "hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError(f"{path}:{number} must be a ledger object")
                for key in ("cost_usd", "duration_s", "human_minutes", "elapsed_s"):
                    value = entry.get(key)
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                              or not math.isfinite(value) or value < 0):
                        raise ValueError(f"{path}:{number} has invalid {key}")
                tokens = entry.get("tokens")
                if tokens is not None and (not isinstance(tokens, dict) or any(
                    tokens.get(k) is not None and (isinstance(tokens[k], bool) or not isinstance(tokens[k], int) or tokens[k] < 0)
                    for k in ("input", "output", "cache_read"))):
                    raise ValueError(f"{path}:{number} has invalid token counts")
                entries.append(entry)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number} is not valid JSON ({error}); the ledger was damaged") from error
    return entries


def load_prices() -> dict:
    try:
        return json.loads(PRICES.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"models": {}, "aliases": {}}


def estimate_cost(model: str | None, tokens: dict | None, prices: dict) -> tuple[float | None, str]:
    """Return (cost_usd, basis). Unknown model or missing tokens -> None, never a guess."""
    if not model:
        return None, "no model (human or local step)"
    name = prices.get("aliases", {}).get(model, model)
    table = prices.get("models", {}).get(name)
    if table is None:
        return None, f"model {model} not in config/model_prices.json"
    if not tokens or tokens.get("input") is None or tokens.get("output") is None:
        return None, "token counts unknown"
    cost = (tokens["input"] * table["input"] + tokens["output"] * table["output"]
            + (tokens.get("cache_read") or 0) * table.get("cache_read", table["input"])) / 1_000_000
    flag = "estimated tokens" if tokens.get("estimated") else "reported tokens"
    return round(cost, 6), f"{name} list price checked {prices.get('checked_at', '?')}; {flag}"


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield handle
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)


def append(project: Path, fields: dict) -> dict:
    """Append one entry atomically under a lock and return it."""
    path = ledger_path(project)
    prices = load_prices()
    with locked(path) as handle:
        handle.seek(0)
        lines = [line for line in handle.read().splitlines() if line.strip()]
        previous = json.loads(lines[-1]) if lines else None
        entry = {
            "seq": (previous["seq"] + 1) if previous else 1,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        entry.update({key: value for key, value in fields.items() if value not in (None, [], {})})
        if "cost_usd" not in entry:
            cost, basis = estimate_cost(entry.get("model"), entry.get("tokens"), prices)
            entry["cost_usd"] = cost
            entry["cost_basis"] = basis
        entry["prev_hash"] = previous["hash"] if previous else GENESIS
        entry["hash"] = entry_hash(entry)
        handle.seek(0, 2)
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
    return entry


def key_states(entries: list[dict]) -> dict[str, dict]:
    states: dict[str, dict] = {}
    for entry in entries:
        key = entry.get("key")
        if key:
            states[key] = entry
    return states


def verify(entries: list[dict]) -> list[str]:
    problems = []
    previous = GENESIS
    for index, entry in enumerate(entries, 1):
        if entry.get("seq") != index:
            problems.append(f"entry {index}: seq is {entry.get('seq')} (line missing or reordered)")
        if entry.get("prev_hash") != previous:
            problems.append(f"entry {index}: prev_hash does not match the previous line")
        if entry_hash(entry) != entry.get("hash"):
            problems.append(f"entry {index}: content was edited after writing")
        previous = entry.get("hash", "")
    return problems


def summarize(entries: list[dict]) -> dict:
    def bucket() -> dict:
        return {"actions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                "cost_unknown_actions": 0, "duration_s": 0.0, "human_minutes": 0.0,
                "unknown_duration_actions": 0, "unknown_human_time_actions": 0, "unknown_token_actions": 0,
                "measured_duration_s": 0.0, "estimated_duration_s": 0.0, "unspecified_duration_s": 0.0, "journal_elapsed_s": 0.0}

    totals = bucket()
    groups: dict[str, dict[str, dict]] = {"step": defaultdict(bucket), "tool": defaultdict(bucket), "model": defaultdict(bucket)}
    for entry in entries:
        if entry.get("status") == "started":
            continue  # the finishing line carries the numbers
        for target in (totals, groups["step"][entry.get("step", "?")], groups["tool"][entry.get("tool", "?")],
                       groups["model"][entry.get("model") or "—"]):
            target["actions"] += 1
            if entry.get("duration_s") is None:
                target["unknown_duration_actions"] += 1
            if entry.get("human_minutes") is None:
                target["unknown_human_time_actions"] += 1
            tokens = entry.get("tokens") or {}
            if entry.get("model") and (tokens.get("input") is None or tokens.get("output") is None):
                target["unknown_token_actions"] += 1
            target["input_tokens"] += tokens.get("input") or 0
            target["output_tokens"] += tokens.get("output") or 0
            if entry.get("cost_usd") is None:
                if entry.get("model"):
                    target["cost_unknown_actions"] += 1
            else:
                target["cost_usd"] += entry["cost_usd"]
            duration = entry.get("duration_s") or 0
            target["duration_s"] += duration
            duration_key = {"measured": "measured_duration_s", "estimated": "estimated_duration_s"}.get(entry.get("duration_basis"), "unspecified_duration_s")
            target[duration_key] += duration
            target["journal_elapsed_s"] += entry.get("elapsed_s") or 0
            target["human_minutes"] += entry.get("human_minutes") or 0
    return {"totals": totals, "by": {name: dict(value) for name, value in groups.items()}}


def render_report(project_path: Path, entries: list[dict]) -> str:
    summary = summarize(entries)
    totals = summary["totals"]
    try:
        project = json.loads(Path(project_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        project = {}
    states = key_states(entries)
    pending = sorted(key for key, entry in states.items() if entry.get("status") == "started")
    failed = sorted(key for key, entry in states.items() if entry.get("status") == "failed")
    integrity = verify(entries)
    estimated = sum(1 for entry in entries if (entry.get("tokens") or {}).get("estimated"))
    lines = [
        f"# Стоимость и время: {project.get('title', project_path)}",
        "",
        f"Сформировано `scripts/ledger.py report` по `{ledger_path(project_path).name}` ({len(entries)} записей).",
        "Стоимость — оценка эквивалента API по `config/model_prices.json`; подписка IDE тарифицируется иначе.",
        "",
        "## Итого",
        "",
        f"- Действий: {totals['actions']}; токены вход/выход: {totals['input_tokens']:,} / {totals['output_tokens']:,}".replace(",", " "),
        f"- Известная часть стоимости: **${totals['cost_usd']:.4f}**; полная стоимость неизвестна при пропусках. Действий модели с неизвестной стоимостью: {totals['cost_unknown_actions']}",
        f"- Записей с оценёнными (не измеренными) токенами: {estimated}",
        f"- Учтённое время действий: {totals['duration_s'] / 60:.1f} мин; учтённое время человека: {totals['human_minutes']:.0f} мин",
        f"- Измеренная длительность действий: {totals['measured_duration_s']:.3f} с; оценённая: {totals['estimated_duration_s']:.3f} с; без основания (старые записи): {totals['unspecified_duration_s']:.3f} с.",
        f"- Интервалы между записями begin/finish: {totals['journal_elapsed_s']:.3f} с — не длительность исследования и не основание экономии.",
        f"- Неизвестно: длительность {totals['unknown_duration_actions']} действий; участие человека {totals['unknown_human_time_actions']} действий; токены {totals['unknown_token_actions']} вызовов модели.",
        "- Нулевые суммы означают только известную часть. Пропуски не равны нулю; длительности параллельных действий не равны времени по часам.",
        f"- Целостность журнала: {'цепочка хешей сходится' if not integrity else 'НАРУШЕНА: ' + '; '.join(integrity)}",
        f"- Незавершённые действия (begin без finish): {', '.join(pending) if pending else 'нет'}",
        f"- Завершились ошибкой: {', '.join(failed) if failed else 'нет'}",
    ]
    baseline = project.get("manual_baseline")
    if isinstance(baseline, dict) and baseline.get("hours"):
        incomplete_time = bool(totals["unknown_duration_actions"] or totals["unknown_human_time_actions"] or totals["estimated_duration_s"] or totals["unspecified_duration_s"])
        spent_h = (totals["duration_s"] / 60 + totals["human_minutes"]) / 60
        lines += [
            "",
            "## Сравнение с ручным способом",
            "",
            f"- Ручной способ: {baseline['hours']} ч ({'измерено' if baseline.get('measured') else 'не измерено'}; основание: {baseline.get('basis', 'не указано')})",
            f"- С агентом по журналу: {spent_h:.1f} ч учтённого времени человека и инструментов (время генерации модели в IDE журнал знает только если его записали).",
            "- Выигрыш во времени не установлен: журнал неполон." if incomplete_time else "- Сравнение требует одинакового объёма и качества результата; суммы времени не доказывают ускорение.",
        ]
    for name, title in (("step", "По этапам"), ("tool", "По инструментам"), ("model", "По моделям")):
        lines += ["", f"## {title}", "", "| Ключ | Действий | Токены вход | Токены выход | $ (оценка) | $ неизвестна | Время, мин |", "|---|---:|---:|---:|---:|---:|---:|"]
        for key, value in sorted(summary["by"][name].items()):
            lines.append(f"| {key} | {value['actions']} | {value['input_tokens']} | {value['output_tokens']} | {value['cost_usd']:.4f} | {value['cost_unknown_actions']} | {(value['duration_s'] / 60 + value['human_minutes']):.1f} |")
    return "\n".join(lines) + "\n"


def tokens_from_args(args: argparse.Namespace) -> dict | None:
    if args.input_tokens is None and args.output_tokens is None and args.estimate_chars is None:
        return None
    if args.estimate_chars is not None:
        # Rough rule for mixed Russian/English text: about 3 characters per token. Marked as estimated.
        return {"input": math.ceil(args.estimate_chars[0] / 3), "output": math.ceil(args.estimate_chars[1] / 3), "estimated": True}
    return {"input": args.input_tokens, "output": args.output_tokens, "cache_read": args.cache_read_tokens,
            "estimated": bool(args.tokens_estimated)}


def fields_from_args(args: argparse.Namespace, status: str) -> dict:
    split = lambda value: [item.strip() for item in value.split(",") if item.strip()] if value else []
    return {
        "step": getattr(args, "step", None), "action": getattr(args, "action", None), "status": status,
        "key": getattr(args, "key", None), "actor": getattr(args, "actor", None), "tool": getattr(args, "tool", None),
        "model": getattr(args, "model", None), "evidence_ids": split(getattr(args, "evidence", None)),
        "source_ids": split(getattr(args, "sources", None)), "outputs": split(getattr(args, "outputs", None)),
        "tokens": tokens_from_args(args), "duration_s": getattr(args, "duration_s", None),
        "human_minutes": getattr(args, "human_minutes", None), "note": getattr(args, "note", None),
        "retrospective": getattr(args, "retrospective", False),
        "duration_basis": (getattr(args, "duration_basis", None) or "unspecified") if getattr(args, "duration_s", None) is not None else None,
        **({"cost_usd": args.cost_usd, "cost_basis": "entered manually"} if getattr(args, "cost_usd", None) is not None else {}),
    }


def nonnegative(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("Expected a finite nonnegative number")
    return number


def token_count(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Token/character counts cannot be negative")
    return number


def add_common(parser: argparse.ArgumentParser, require_step: bool) -> None:
    parser.add_argument("--step", required=require_step, help="workflow stage: intake, research, options, strategy, ...")
    parser.add_argument("--action", required=require_step, help="what was done, one line")
    parser.add_argument("--actor", default="agent", choices=["agent", "subagent", "human", "script", "hook"])
    parser.add_argument("--tool", default="llm", help="tool or script used, e.g. WebSearch, scripts/snapshot.py")
    parser.add_argument("--model", help="model id or alias (opus/sonnet/haiku); omit for scripts and people")
    parser.add_argument("--evidence", help="comma-separated evidence IDs used as basis or produced")
    parser.add_argument("--sources", help="comma-separated source IDs")
    parser.add_argument("--outputs", help="comma-separated files written")
    parser.add_argument("--input-tokens", type=token_count)
    parser.add_argument("--output-tokens", type=token_count)
    parser.add_argument("--cache-read-tokens", type=token_count)
    parser.add_argument("--tokens-estimated", action="store_true", help="token numbers are an estimate, not reported by the provider")
    parser.add_argument("--estimate-chars", type=token_count, nargs=2, metavar=("IN_CHARS", "OUT_CHARS"), help="estimate tokens from characters (marked estimated)")
    parser.add_argument("--cost-usd", type=nonnegative, help="known cost from a provider bill (overrides the price table)")
    parser.add_argument("--retrospective", action="store_true", help="Record past work; never derive its duration from the logging timestamp")
    parser.add_argument("--duration-basis", choices=("measured", "estimated"), help="Required when duration-s is supplied")
    parser.add_argument("--duration-s", type=nonnegative)
    parser.add_argument("--human-minutes", type=nonnegative)
    parser.add_argument("--note")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    log = commands.add_parser("log")
    log.add_argument("project", type=Path)
    add_common(log, True)
    log.add_argument("--status", default="done", choices=["done", "failed", "skipped"])
    log.add_argument("--key")
    begin = commands.add_parser("begin")
    begin.add_argument("project", type=Path)
    begin.add_argument("--key", required=True)
    begin.add_argument("--retry", action="store_true", help="explicitly retry an interrupted or failed action")
    add_common(begin, True)
    finish = commands.add_parser("finish")
    finish.add_argument("project", type=Path)
    finish.add_argument("--key", required=True)
    finish.add_argument("--status", default="done", choices=["done", "failed", "skipped"])
    add_common(finish, False)
    for name in ("status", "verify"):
        commands.add_parser(name).add_argument("project", type=Path)
    report = commands.add_parser("report")
    report.add_argument("project", type=Path)
    report.add_argument("--out", type=Path, help="write markdown here instead of stdout")
    args = parser.parse_args()
    if hasattr(args, "duration_s") and args.duration_s is not None and not args.duration_basis:
        parser.error("--duration-s requires --duration-basis measured or estimated")
    if hasattr(args, "estimate_chars") and args.estimate_chars is not None and not args.note:
        parser.error("--estimate-chars requires --note explaining measured character counts and coverage")

    try:
        path = ledger_path(args.project)
        entries = read_entries(path)
        if args.command == "log":
            entry = append(args.project, fields_from_args(args, args.status))
            print(f"ledger #{entry['seq']} {entry['status']}: {entry['action']} (cost: {entry['cost_usd']})")
        elif args.command == "begin":
            state = key_states(entries).get(args.key)
            if state and state.get("status") == "done" and not args.retry:
                print(f"SKIP: '{args.key}' already done at {state['at']} (ledger #{state['seq']}). Use its outputs; pass --retry only if the user asks to redo it.")
                raise SystemExit(EXIT_ALREADY_DONE)
            if state and state.get("status") in ("started", "failed") and not args.retry:
                print(f"INTERRUPTED: '{args.key}' is '{state['status']}' since {state['at']} (ledger #{state['seq']}). Check what it changed, tell the user, then rerun with --retry.")
                raise SystemExit(EXIT_INTERRUPTED)
            entry = append(args.project, fields_from_args(args, "started"))
            print(f"ledger #{entry['seq']} started: {args.key}")
        elif args.command == "finish":
            state = key_states(entries).get(args.key)
            if not state or state.get("status") != "started":
                raise ValueError(f"no started action with key '{args.key}'")
            fields = fields_from_args(args, args.status)
            fields["step"] = fields["step"] or state.get("step")
            fields["action"] = fields["action"] or state.get("action")
            if state.get("retrospective"):
                fields["retrospective"] = True
            elif state.get("at"):
                started = datetime.fromisoformat(state["at"])
                # Time between journal events includes pauses and parallel work. It is not task duration.
                fields["elapsed_s"] = max(0, round((datetime.now(timezone.utc) - started).total_seconds(), 3))
            entry = append(args.project, fields)
            print(f"ledger #{entry['seq']} {entry['status']}: {args.key}")
        elif args.command == "status":
            states = key_states(entries)
            print(json.dumps({
                "entries": len(entries),
                "keys": {key: {"status": value.get("status"), "at": value.get("at"), "seq": value.get("seq")} for key, value in states.items()},
                "unfinished": sorted(key for key, value in states.items() if value.get("status") == "started"),
                "failed": sorted(key for key, value in states.items() if value.get("status") == "failed"),
                "cost_usd_known": round(summarize(entries)["totals"]["cost_usd"], 6),
            }, ensure_ascii=False, indent=2))
        elif args.command == "verify":
            problems = verify(entries)
            if problems:
                print("\n".join(f"ERROR: {problem}" for problem in problems))
                raise SystemExit(1)
            print(f"Ledger chain is intact: {len(entries)} entries in {path}")
        else:
            text = render_report(args.project, entries)
            if args.out:
                from output_guard import check_output
                project = json.loads(args.project.read_text(encoding="utf-8-sig"))
                check_output(project, args.project, args.out)
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(text, encoding="utf-8")
                print(f"Report written to {args.out}")
            else:
                print(text)
    except (OSError, ValueError, KeyError) as error:
        print(f"Ledger: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
