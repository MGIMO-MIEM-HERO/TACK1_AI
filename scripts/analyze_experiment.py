#!/usr/bin/env python3
"""Summarize the synthetic A/B case with user-level joins and uncertainty intervals."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "examples" / "activation-case"
INPUT = CASE / "inputs"
OUTPUT = CASE / "outputs"
METRICS = ("activation_24h", "retained_d7", "support_contact_7d", "refund_30d")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def wilson(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return [max(0.0, center - half), min(1.0, center + half)]


def rate(rows: Iterable[dict[str, object]], metric: str) -> dict[str, object]:
    items = list(rows)
    n = len(items)
    total = sum(int(row[metric]) for row in items)
    return {"n": n, "successes": total, "rate": total / n if n else None, "wilson_95": wilson(total, n)}


def difference_ci(a: dict[str, object], b: dict[str, object]) -> list[float] | None:
    """Newcombe hybrid score interval for p(B)-p(A), built from Wilson limits."""
    if a["rate"] is None or b["rate"] is None or a["wilson_95"] is None or b["wilson_95"] is None:
        return None
    pa, pb = float(a["rate"]), float(b["rate"])
    la, ua = a["wilson_95"]
    lb, ub = b["wilson_95"]
    diff = pb - pa
    low = diff - math.hypot(pb - lb, ua - pa)
    high = diff + math.hypot(ub - pb, pa - la)
    return [max(-1.0, low), min(1.0, high)]


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def pp(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f} п.п."


def approximate_n_per_arm(baseline: float | None, absolute_mde: float, alpha: float = 0.05, power: float = 0.8) -> int | None:
    """Approximate equal-arm sample size for two proportions; planning aid, not a production calculator."""
    if baseline is None or absolute_mde <= 0 or not 0 < baseline < 1 or not 0 < power < 1:
        return None
    p1 = baseline
    p2 = baseline + absolute_mde
    if p2 >= 1:
        return None
    pooled = (p1 + p2) / 2
    # Standard normal quantiles for two-sided alpha=.05 and power=.80 are used by default.
    # Other alpha/power values are intentionally not approximated in this first prototype.
    if abs(alpha - 0.05) > 1e-12 or abs(power - 0.8) > 1e-12:
        return None
    z_alpha, z_power = 1.96, 0.84
    numerator = (z_alpha * (2 * pooled * (1 - pooled)) ** 0.5
                 + z_power * (p1 * (1 - p1) + p2 * (1 - p2)) ** 0.5) ** 2
    return math.ceil(numerator / (absolute_mde ** 2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT, help="Directory containing users/events/outcomes/support CSVs")
    parser.add_argument("--out", type=Path, default=OUTPUT, help="Directory for analysis.json and analysis.md")
    parser.add_argument("--min-lift", type=float, default=0.03, help="Demo minimum useful absolute primary lift")
    parser.add_argument("--max-support-increase", type=float, default=0.02, help="Demo guardrail limit in absolute share")
    parser.add_argument("--max-refund-increase", type=float, default=0.01, help="Demo guardrail limit in absolute share")
    args = parser.parse_args()

    if not (0 < args.min_lift < 1 and 0 <= args.max_support_increase <= 1 and 0 <= args.max_refund_increase <= 1):
        parser.error("Thresholds must be finite fractions between 0 and 1; minimum lift must be positive")

    users = read_csv(args.input / "users.csv")
    outcomes = read_csv(args.input / "outcomes.csv")
    events = read_csv(args.input / "events.csv")
    support = read_csv(args.input / "support.csv")

    user_ids = [row["user_id"] for row in users]
    outcome_ids = [row["user_id"] for row in outcomes]
    user_set = set(user_ids)
    outcome_set = set(outcome_ids)
    outcome_by_user = {row["user_id"]: row for row in outcomes}
    users_by_id = {row["user_id"]: row for row in users}
    ticket_counts = Counter(row["user_id"] for row in support)
    if "" in user_set or {row["variant"] for row in users} != {"A", "B"}:
        raise SystemExit("Expected nonempty user IDs and both A and B arms")
    if any(row.get(metric) not in {"0", "1"} for row in outcomes for metric in METRICS):
        raise SystemExit("Outcome metrics must be binary (0 or 1)")

    quality = {
        "users_rows": len(users),
        "outcome_rows": len(outcomes),
        "unique_users": len(user_set),
        "duplicate_user_ids": len(user_ids) - len(user_set),
        "duplicate_outcome_user_ids": len(outcome_ids) - len(outcome_set),
        "users_without_outcome": len(user_set - outcome_set),
        "outcomes_without_user": len(outcome_set - user_set),
        "events_without_user": len({row["user_id"] for row in events} - user_set),
        "support_without_user": len({row["user_id"] for row in support} - user_set),
        "support_ticket_rows": len(support),
        "joined_user_level_before_support": True,
    }

    defects = {name: count for name, count in quality.items() if count and (name.startswith("duplicate_") or "_without_" in name)}
    if defects:
        raise SystemExit(f"Input integrity issue: {defects}")
    if any(int(row["support_contact_7d"]) != bool(ticket_counts[row["user_id"]]) for row in outcomes):
        raise SystemExit("Support outcome and ticket records disagree")

    user_level: list[dict[str, object]] = []
    for user_id in user_ids:
        merged: dict[str, object] = dict(users_by_id[user_id])
        merged.update({metric: int(outcome_by_user[user_id][metric]) for metric in METRICS})
        user_level.append(merged)

    by_variant = {v: [row for row in user_level if row["variant"] == v] for v in ("A", "B")}
    allocation = {v: len(by_variant[v]) for v in ("A", "B")}
    allocation_share_difference = abs(allocation["A"] / len(user_level) - allocation["B"] / len(user_level)) if user_level else None
    metrics: dict[str, object] = {}
    for metric in METRICS:
        a, b = rate(by_variant["A"], metric), rate(by_variant["B"], metric)
        metrics[metric] = {
            "label": {
                "activation_24h": "Primary: activation within 24h",
                "retained_d7": "Secondary: returned on day 7",
                "support_contact_7d": "Guardrail: support contact within 7d",
                "refund_30d": "Guardrail: refund within 30d",
            }[metric],
            "A": a,
            "B": b,
            "absolute_difference_B_minus_A": (b["rate"] - a["rate"]) if a["rate"] is not None and b["rate"] is not None else None,
            "difference_interval_95": difference_ci(a, b),
        }

    primary = metrics["activation_24h"]
    primary_delta = primary["absolute_difference_B_minus_A"]
    primary_interval = primary["difference_interval_95"]
    primary_positive = primary_interval is not None and primary_interval[0] > 0
    primary_useful = primary_delta is not None and primary_delta >= args.min_lift
    guardrails = {}
    for metric, limit in (("support_contact_7d", args.max_support_increase), ("refund_30d", args.max_refund_increase)):
        low, high = metrics[metric]["difference_interval_95"]
        guardrails[metric] = "within_limit" if high <= limit else "above_limit" if low > limit else "uncertain"
    eligible = primary_positive and primary_useful and all(value == "within_limit" for value in guardrails.values())
    sample_plan = {
        "baseline_rate_from_A": primary["A"]["rate"],
        "minimum_absolute_detectable_effect": args.min_lift,
        "two_sided_alpha": 0.05,
        "target_power": 0.8,
        "approximate_required_users_per_arm": approximate_n_per_arm(primary["A"]["rate"], args.min_lift),
        "method_note": "Approximate normal formula for two independent proportions; planning aid only, not production power analysis.",
    }

    event_users: dict[str, set[str]] = defaultdict(set)
    for event in events:
        event_users[event["event_name"]].add(event["user_id"])
    funnel_steps = ["app_open", "view_offer", "start_activation", "activation_success"]
    funnel = []
    previous_users = None
    for step in funnel_steps:
        step_users = event_users[step]
        if previous_users is not None:
            step_users = step_users & previous_users
        n = len(step_users)
        funnel.append({
            "step": step,
            "unique_users": n,
            "share_of_all_users": n / len(user_set) if user_set else None,
            "conversion_from_previous_step": n / len(previous_users) if previous_users else None,
        })
        previous_users = step_users

    segments: dict[str, object] = {}
    for field, metric in (("device", "activation_24h"), ("acquisition_channel", "retained_d7")):
        values = sorted({str(row[field]) for row in user_level})
        segments[field] = {}
        for value in values:
            arm_stats = {}
            for arm in ("A", "B"):
                group = [row for row in user_level if row[field] == value and row["variant"] == arm]
                arm_stats[arm] = rate(group, metric)
            segments[field][value] = {"metric": metric, "A": arm_stats["A"], "B": arm_stats["B"]}

    topic_counts = Counter(row["topic"] for row in support)
    report = {
        "case": "synthetic_onboarding_message_experiment",
        "created_by": "scripts/analyze_experiment.py",
        "synthetic_only": True,
        "unit_of_analysis": "unique user; support contacts aggregated to user before comparison",
        "data_quality": quality,
        "allocation": {
            "counts": allocation,
            "absolute_share_difference": allocation_share_difference,
            "note": "Descriptive allocation only; this is not a sample-ratio mismatch test.",
        },
        "primary_and_guardrail_metrics": metrics,
        "funnel": funnel,
        "segments": segments,
        "support_topics": dict(topic_counts),
        "demo_thresholds": {
            "minimum_activation_lift": args.min_lift,
            "maximum_support_increase": args.max_support_increase,
            "maximum_refund_increase": args.max_refund_increase,
        },
        "sample_planning": sample_plan,
        "decision_gate": {
            "status": "eligible_for_human_review" if eligible else "not_eligible_under_demo_rule",
            "meaning": "Mechanical synthetic-data gate only; never an automatic ship/no-ship decision.",
            "primary_interval_above_zero": primary_positive,
            "primary_lift_meets_demo_threshold": primary_useful,
            "guardrail_interval_status": guardrails,
        },
        "caveats": [
            "All records are synthetic and do not describe real Megafon customers or market behavior.",
            "The A/B assignment and effects are simulated; this run is not a real experiment.",
            "Segment breakdowns are exploratory and are not causal estimates of device or acquisition-channel effects.",
            "Difference intervals use a Newcombe hybrid score method based on Wilson intervals; read code and design docs before extending to production.",
            "No p-value, multiplicity correction, production power analysis, or real experiment validity checks are claimed by this demo analyzer.",
        ],
        "suggested_follow_up": [
            "Compare the primary interval with zero and the minimum useful effect.",
            "If planning a real test, validate the primary metric and use the sample-size estimate only as a rough starting point.",
            "Investigate guardrail differences and segment patterns as questions; do not treat these synthetic segment associations as causal.",
        ],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    json_path = args.out / "analysis.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Synthetic experiment summary",
        "",
        "> Synthetic demonstration only. This is not evidence about real customers or a launch recommendation.",
        "",
        f"Users: {len(user_level)}; A/B allocation: {allocation['A']} / {allocation['B']}.",
        "",
        "## Metrics (B minus A)",
        "",
        "| Metric | A | B | Absolute difference | 95% interval for difference |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in METRICS:
        item = metrics[key]
        interval = item["difference_interval_95"]
        formatted_interval = "n/a" if interval is None else f"[{pp(interval[0])}, {pp(interval[1])}]"
        lines.append(f"| {item['label']} | {pct(item['A']['rate'])} (n={item['A']['n']}) | {pct(item['B']['rate'])} (n={item['B']['n']}) | {pp(item['absolute_difference_B_minus_A'])} | {formatted_interval} |")
    lines.extend([
        "",
        "## Funnel",
        "",
        "| Step | Unique users | Share of all | From previous step |",
        "|---|---:|---:|---:|",
    ])
    for item in funnel:
        lines.append(f"| {item['step']} | {item['unique_users']} | {pct(item['share_of_all_users'])} | {pct(item['conversion_from_previous_step'])} |")
    lines.extend([
        "",
        f"## Mechanical gate: `{report['decision_gate']['status']}`",
        "",
        report["decision_gate"]["meaning"],
        "",
        f"Approximate sample planning: about {sample_plan['approximate_required_users_per_arm']} users per arm for a {args.min_lift * 100:.1f} п.п. absolute primary effect at 80% power and two-sided 5% alpha; this rough estimate is not a substitute for a production design review.",
        "",
        "The AI assistant must explain limitations, compare strategic options, and leave the decision to a person. See `knowledge/metrics-and-inference.md`.",
    ])
    (args.out / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Analysis written to {json_path}")
    print(f"Synthetic demo gate: {report['decision_gate']['status']}")


if __name__ == "__main__":
    main()
