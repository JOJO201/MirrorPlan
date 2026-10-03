#!/usr/bin/env python3
"""Repeated timing study specified by the frozen main protocol."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import yaml

from mirrorplan.algorithms import factor_hybrid, milp_exact
from mirrorplan.instance import load_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--protocol", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    protocol_path = args.protocol or args.root / "protocols" / "main.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    warmups = int(protocol["runtime"]["warmups"])
    repetitions = int(protocol["runtime"]["measured_repetitions"])
    component_limit = int(protocol["solver"]["component_enumeration_limit"])
    rows = []
    for event in map(str, protocol["population"]["events"]):
        instance = load_instance(
            args.root / "data" / "instances" / f"event_{event}.json.gz"
        )
        for fraction_value in protocol["budgets"]["fractions"]:
            fraction = float(fraction_value)
            budget = min(
                len(instance.candidates),
                max(1, math.ceil(fraction * len(instance.candidates))),
            )
            methods = {
                "factor_hybrid": lambda: factor_hybrid(
                    instance, budget, component_limit=component_limit
                ),
                "milp_exact": lambda: milp_exact(instance, budget),
            }
            for method, solve in methods.items():
                for _ in range(warmups):
                    solve()
                expected = None
                for repetition in range(repetitions):
                    solution = solve()
                    if expected is None:
                        expected = solution.value
                    elif solution.value != expected:
                        raise SystemExit(
                            f"Nondeterministic objective for {event} {fraction} {method}"
                        )
                    rows.append(
                        {
                            "event": event,
                            "budget_fraction": f"{fraction:.4f}",
                            "budget": budget,
                            "method": method,
                            "repetition": repetition,
                            "value": solution.value,
                            "runtime_seconds": solution.runtime_seconds,
                        }
                    )
    output = args.root / "results" / "raw" / "runtime_runs.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} measured timing rows to {output}")


if __name__ == "__main__":
    main()

