#!/usr/bin/env python3
"""Run and summarize the frozen structured missed-alert stress test."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml

from deterministic_plots import configure_deterministic_pdf
from mirrorplan.alerts import (
    candidate_impact,
    construct_alert_set,
    restrict_to_alerts,
)
from mirrorplan.algorithms import milp_exact
from mirrorplan.instance import load_instance


configure_deterministic_pdf()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    return parser.parse_args()


def bootstrap_mean(
    values: list[float], seed: int = 20260716, repetitions: int = 10000
) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    indices = generator.integers(0, len(array), size=(repetitions, len(array)))
    return tuple(np.percentile(array[indices].mean(axis=1), [2.5, 97.5]))


def main() -> None:
    args = parse_args()
    protocol_path = args.root / "protocols" / "alert_stress.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "frozen":
        raise SystemExit("Refusing stress run: protocol status is not frozen")
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows: list[dict] = []

    for event in map(str, protocol["events"]):
        instance = load_instance(
            args.root / "data" / "instances" / f"event_{event}.json.gz"
        )
        candidates = set(instance.candidates)
        scores = candidate_impact(instance)
        total_impact = sum(scores.values())
        budget = max(
            1,
            math.ceil(
                float(protocol["budget_fraction_of_original_candidates"])
                * len(candidates)
            ),
        )
        value_cache: dict[frozenset[str], int] = {}
        for mechanism, settings in protocol["mechanisms"].items():
            seeds = int(settings["seeds"])
            for recall_value in protocol["alert_recall"]:
                recall = float(recall_value)
                for seed in range(seeds):
                    alerted = construct_alert_set(
                        instance, recall, mechanism, seed=seed
                    )
                    key = frozenset(alerted)
                    if key not in value_cache:
                        restricted = restrict_to_alerts(instance, alerted)
                        solution = milp_exact(
                            restricted, min(budget, len(restricted.candidates))
                        )
                        value_cache[key] = solution.value
                    missed = candidates - alerted
                    rows.append(
                        {
                            "protocol_sha256": protocol_hash,
                            "event": event,
                            "mechanism": mechanism,
                            "alert_recall": f"{recall:.2f}",
                            "seed": seed,
                            "original_candidates": len(candidates),
                            "alerted_candidates": len(alerted),
                            "missed_owners": len(
                                {item.split("/", 1)[0] for item in missed}
                            ),
                            "missed_impact_share": (
                                sum(scores[item] for item in missed) / total_impact
                                if total_impact
                                else 0.0
                            ),
                            "budget": budget,
                            "all_affected_targets": instance.affected_targets,
                            "restored_targets": value_cache[key],
                            "restored_fraction": (
                                value_cache[key] / instance.affected_targets
                            ),
                        }
                    )

    raw_path = args.root / "results" / "raw" / "alert_stress_runs.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    per_event: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        per_event[(row["event"], row["mechanism"], row["alert_recall"])].append(
            float(row["restored_fraction"])
        )
    events = list(map(str, protocol["events"]))
    mechanisms = list(protocol["mechanisms"])
    recalls = [f"{float(value):.2f}" for value in protocol["alert_recall"]]
    summary_rows = []
    event_means: dict[tuple[str, str], list[float]] = {}
    for mechanism in mechanisms:
        for recall in recalls:
            values = [
                statistics.mean(per_event[(event, mechanism, recall)])
                for event in events
            ]
            event_means[(mechanism, recall)] = values
            low, high = bootstrap_mean(values)
            summary_rows.append(
                {
                    "mechanism": mechanism,
                    "alert_recall": recall,
                    "events": len(values),
                    "mean_restored_fraction": statistics.mean(values),
                    "median_restored_fraction": statistics.median(values),
                    "ci95_low": low,
                    "ci95_high": high,
                }
            )
    summary_path = args.root / "results" / "alert_stress_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    contrast_rows = []
    for recall in recalls:
        uniform = event_means[("uniform", recall)]
        for mechanism in ("owner_clustered", "impact_targeted"):
            differences = [
                candidate - baseline
                for candidate, baseline in zip(
                    event_means[(mechanism, recall)], uniform, strict=True
                )
            ]
            low, high = bootstrap_mean(differences)
            contrast_rows.append(
                {
                    "mechanism": mechanism,
                    "reference": "uniform",
                    "alert_recall": recall,
                    "events": len(differences),
                    "mean_paired_difference": statistics.mean(differences),
                    "median_paired_difference": statistics.median(differences),
                    "ci95_low": low,
                    "ci95_high": high,
                }
            )
    contrast_path = args.root / "results" / "alert_stress_contrasts.csv"
    with contrast_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(contrast_rows[0]))
        writer.writeheader()
        writer.writerows(contrast_rows)

    colors = {
        "uniform": "#0072B2",
        "owner_clustered": "#009E73",
        "impact_targeted": "#D55E00",
    }
    labels = {
        "uniform": "Uniform",
        "owner_clustered": "Owner-clustered",
        "impact_targeted": "Impact-targeted",
    }
    markers = {"uniform": "o", "owner_clustered": "s", "impact_targeted": "^"}
    plt.rcParams.update(
        {
            "font.size": 14,
            "axes.labelsize": 14,
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
            "legend.fontsize": 12,
            "text.usetex": True,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(5.2, 3.5))
    x = np.asarray([float(value) for value in recalls])
    for mechanism in mechanisms:
        method_rows = [
            row for row in summary_rows if row["mechanism"] == mechanism
        ]
        y = np.asarray([row["mean_restored_fraction"] for row in method_rows])
        low = np.asarray([row["ci95_low"] for row in method_rows])
        high = np.asarray([row["ci95_high"] for row in method_rows])
        ax.plot(
            x,
            y,
            color=colors[mechanism],
            marker=markers[mechanism],
            label=labels[mechanism],
            linewidth=2.0,
            markersize=7,
        )
        ax.fill_between(x, low, high, color=colors[mechanism], alpha=0.10)
    ax.set_xlabel("Alert recall")
    ax.set_ylabel("Recovered lineage fraction")
    ax.set_xlim(0.47, 1.03)
    ax.set_ylim(0, 0.75)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    figures = args.root / "results" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        figures / "alert_stress.pdf",
        metadata={"CreationDate": None, "ModDate": None},
    )
    fig.savefig(figures / "alert_stress.png", dpi=220)
    plt.close(fig)

    payload = {
        "protocol_sha256": protocol_hash,
        "rows": len(rows),
        "summary": summary_rows,
        "contrasts": contrast_rows,
    }
    (args.root / "results" / "alert_stress_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
