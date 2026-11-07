#!/usr/bin/env python3
"""Generate deterministic, explicitly synthetic product experiment data."""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "examples" / "activation-case" / "inputs"
SEED = 20261107
USERS = 1200


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def generate(out_dir: Path) -> None:
    rng = random.Random(SEED)
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    users: list[dict[str, object]] = []
    outcomes: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    tickets: list[dict[str, object]] = []

    devices = ["Android", "iOS", "Desktop"]
    device_weights = [0.53, 0.35, 0.12]
    channels = ["Органический поиск", "Рекомендация", "Реклама", "Email"]
    channel_weights = [0.36, 0.22, 0.25, 0.17]

    for number in range(1, USERS + 1):
        user_id = f"u{number:05d}"
        variant = "B" if rng.random() < 0.5 else "A"
        device = rng.choices(devices, weights=device_weights, k=1)[0]
        channel = rng.choices(channels, weights=channel_weights, k=1)[0]
        plan = rng.choices(["Базовый", "Плюс", "Премиум"], weights=[0.58, 0.31, 0.11], k=1)[0]
        joined_days_ago = rng.randrange(0, 75)
        joined = base + timedelta(days=joined_days_ago, minutes=rng.randrange(0, 1440))

        users.append({
            "user_id": user_id,
            "variant": variant,
            "device": device,
            "acquisition_channel": channel,
            "plan": plan,
            "joined_at": joined.isoformat(timespec="minutes"),
        })

        session_id = f"s{number:05d}"
        step_minute = rng.randrange(0, 60)

        def add_event(name: str, offset: int) -> None:
            events.append({
                "event_id": f"e{len(events) + 1:07d}",
                "user_id": user_id,
                "session_id": session_id if name != "return_d7" else f"r{number:05d}",
                "occurred_at": (joined + timedelta(minutes=step_minute + offset)).isoformat(timespec="seconds"),
                "event_name": name,
            })

        add_event("app_open", 0)
        viewed_offer = rng.random() < 0.86
        if viewed_offer:
            add_event("view_offer", 1)
        started = viewed_offer and rng.random() < 0.79
        if started:
            add_event("start_activation", 2)

        p_activate = 0.60 + (0.075 if variant == "B" else 0.0)
        p_activate += {"Android": -0.08, "iOS": 0.0, "Desktop": 0.035}[device]
        p_activate += {"Органический поиск": 0.0, "Рекомендация": 0.035, "Реклама": -0.035, "Email": 0.015}[channel]
        activated = started and rng.random() < clamp(p_activate, 0.05, 0.95)
        if activated:
            add_event("activation_success", 3)
        elif started:
            add_event("activation_abandoned", 3)

        p_return = 0.11 + (0.43 if activated else 0.0)
        p_return += 0.02 if variant == "B" else 0.0
        p_return += {"Android": -0.045, "iOS": 0.0, "Desktop": 0.02}[device]
        p_return += -0.02 if channel == "Реклама" else 0.0
        retained = rng.random() < clamp(p_return, 0.02, 0.9)
        if retained:
            add_event("return_d7", 7 * 24 * 60)

        p_support = 0.035 + (0.045 if not activated else 0.0) + (0.035 if device == "Android" and not activated else 0.0)
        p_support -= 0.008 if variant == "B" else 0.0
        support_contact = rng.random() < clamp(p_support, 0.005, 0.5)
        if support_contact:
            topic = "Ошибка активации" if device == "Android" and not activated and rng.random() < 0.68 else "Как пользоваться"
            tickets.append({
                "ticket_id": f"t{len(tickets) + 1:05d}",
                "user_id": user_id,
                "topic": topic,
                "wait_hours": round(clamp(rng.gauss(5.5, 2.1), 0.2, 18), 1),
                "resolved": "yes" if rng.random() < 0.9 else "no",
            })

        p_refund = 0.035 + (0.018 if not retained else 0.0)
        refund = activated and rng.random() < p_refund
        outcomes.append({
            "user_id": user_id,
            "activation_24h": int(activated),
            "retained_d7": int(retained),
            "support_contact_7d": int(support_contact),
            "refund_30d": int(refund),
        })

    write_csv(out_dir / "users.csv", users, ["user_id", "variant", "device", "acquisition_channel", "plan", "joined_at"])
    write_csv(out_dir / "events.csv", events, ["event_id", "user_id", "session_id", "occurred_at", "event_name"])
    write_csv(out_dir / "outcomes.csv", outcomes, ["user_id", "activation_24h", "retained_d7", "support_contact_7d", "refund_30d"])
    write_csv(out_dir / "support.csv", tickets, ["ticket_id", "user_id", "topic", "wait_hours", "resolved"])

    print(f"Synthetic demo written to {out_dir}")
    print(f"seed={SEED}; users={len(users)}; events={len(events)}; support_tickets={len(tickets)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory for synthetic CSV files")
    args = parser.parse_args()
    generate(args.out)


if __name__ == "__main__":
    main()
