#!/usr/bin/env python3
"""Analyze how the complementarity core contributes to exact plans."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from pathlib import Path

import numpy as np
import yaml

from mirrorplan.algorithms import singleton_only_ranking
from mirrorplan.instance import complementarity_core, load_instance


ROOT = Path(__file__).parents[1]


def bootstrap_mean(values: list[float], seed: int) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    indices = generator.integers(0, len(array), size=(10000, len(array)))
    return tuple(np.percentile(array[indices].mean(axis=1), [2.5, 97.5]))


def main() -> None:
    protocol_path = ROOT / "protocols" / "mechanism_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing mechanism analysis: protocol is not frozen")
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    selections: dict[tuple[str, str], dict] = {}
    with (ROOT / "results" / "raw" / "main_selections.jsonl").open(
        encoding="utf-8"
    ) as handle:
        for line in handle:
            row = json.loads(line)
            if row["method"] == "factor_hybrid":
                selections[(row["event"], row["budget_fraction"])] = row

    raw_rows = []
    for event in map(str, protocol["events"]):
        instance = load_instance(
            ROOT / "data" / "instances" / f"event_{event}.json.gz"
        )
        core = complementarity_core(instance)
        for fraction_value in protocol["budget_fractions"]:
            fraction = f"{float(fraction_value):.4f}"
            exact = selections[(event, fraction)]
            exact_selected = set(exact["selected"])
            exact_singleton_value = sum(
                group.weight
                for group in instance.groups
                if len(group.members) == 1
                and set(group.members).issubset(exact_selected)
            )
            exact_multi_value = int(exact["value"]) - exact_singleton_value
            additive = singleton_only_ranking(instance, int(exact["budget"]))
            raw_rows.append(
                {
                    "protocol_sha256": protocol_hash,
                    "event": event,
                    "budget_fraction": fraction,
                    "budget": int(exact["budget"]),
                    "affected_targets": instance.affected_targets,
                    "exact_value": int(exact["value"]),
                    "additive_value": additive.value,
                    "exact_core_candidates": len(exact_selected & core),
                    "exact_core_budget_fraction": (
                        len(exact_selected & core) / int(exact["budget"])
                    ),
                    "exact_multi_value": exact_multi_value,
                    "exact_multi_value_fraction": (
                        exact_multi_value / int(exact["value"])
                        if int(exact["value"])
                        else 0.0
                    ),
                    "paired_recovery_gain": (
                        (int(exact["value"]) - additive.value)
                        / instance.affected_targets
                    ),
                }
            )

    raw_path = ROOT / "results" / "mechanism_runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw_rows[0]))
        writer.writeheader()
        writer.writerows(raw_rows)

    seed = int(protocol["bootstrap_seed"])
    summary_rows = []
    for fraction_value in protocol["budget_fractions"]:
        fraction = f"{float(fraction_value):.4f}"
        rows = [row for row in raw_rows if row["budget_fraction"] == fraction]
        gains = [float(row["paired_recovery_gain"]) for row in rows]
        low, high = bootstrap_mean(gains, seed)
        summary_rows.append(
            {
                "budget_fraction": fraction,
                "events": len(rows),
                "mean_exact_core_budget_fraction": statistics.mean(
                    float(row["exact_core_budget_fraction"]) for row in rows
                ),
                "mean_exact_multi_value_fraction": statistics.mean(
                    float(row["exact_multi_value_fraction"]) for row in rows
                ),
                "mean_paired_recovery_gain": statistics.mean(gains),
                "median_paired_recovery_gain": statistics.median(gains),
                "events_strictly_better": sum(gain > 0 for gain in gains),
                "gain_ci95_low": low,
                "gain_ci95_high": high,
            }
        )
    summary_path = ROOT / "results" / "mechanism_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    payload = {
        "protocol_sha256": protocol_hash,
        "rows": len(raw_rows),
        "summary": summary_rows,
    }
    (ROOT / "results" / "mechanism_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
