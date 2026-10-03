#!/usr/bin/env python3
"""Summarize alert-recall sensitivity and repeated runtime measurements."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from deterministic_plots import configure_deterministic_pdf


configure_deterministic_pdf()


ROOT = Path(__file__).parents[1]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def bootstrap(values: list[float], seed: int = 20260716) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    array = np.asarray(values)
    samples = array[
        generator.integers(0, len(array), size=(10000, len(array)))
    ].mean(axis=1)
    return tuple(np.percentile(samples, [2.5, 97.5]))


def main() -> None:
    alert_rows = read_csv(ROOT / "results" / "raw" / "alert_recall_runs.csv")
    per_event: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in alert_rows:
        per_event[(row["event"], row["alert_recall"])].append(
            float(row["restored_fraction"])
        )
    events = sorted({event for event, _ in per_event})
    recalls = sorted({recall for _, recall in per_event}, key=float)
    alert_summary = []
    for recall in recalls:
        values = [statistics.mean(per_event[(event, recall)]) for event in events]
        low, high = bootstrap(values)
        alert_summary.append(
            {
                "alert_recall": recall,
                "events": len(values),
                "seeds_per_event": len(per_event[(events[0], recall)]),
                "mean_restored_fraction": statistics.mean(values),
                "median_restored_fraction": statistics.median(values),
                "ci95_low": low,
                "ci95_high": high,
            }
        )
    alert_path = ROOT / "results" / "alert_recall_summary.csv"
    with alert_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(alert_summary[0]))
        writer.writeheader()
        writer.writerows(alert_summary)

    plt.rcParams.update(
        {
            "font.size": 13,
            "axes.labelsize": 13,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "text.usetex": True,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    x = np.asarray([float(row["alert_recall"]) for row in alert_summary])
    y = np.asarray([row["mean_restored_fraction"] for row in alert_summary])
    low = np.asarray([row["ci95_low"] for row in alert_summary])
    high = np.asarray([row["ci95_high"] for row in alert_summary])
    ax.plot(x, y, color="#0072B2", marker="o", linewidth=2.0, markersize=7)
    ax.fill_between(x, low, high, color="#0072B2", alpha=0.15)
    ax.set_xlabel("Alert recall")
    ax.set_ylabel("Recovered lineage fraction")
    ax.set_xlim(0.47, 1.03)
    ax.set_ylim(0, 0.75)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    figures = ROOT / "results" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        figures / "alert_recall.pdf",
        metadata={"CreationDate": None, "ModDate": None},
    )
    fig.savefig(figures / "alert_recall.png", dpi=220)
    plt.close(fig)

    runtime_rows = read_csv(ROOT / "results" / "raw" / "runtime_runs.csv")
    measurements: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in runtime_rows:
        measurements[(row["event"], row["budget_fraction"], row["method"])].append(
            float(row["runtime_seconds"])
        )
    runtime_summary = []
    for method in ("factor_hybrid", "milp_exact"):
        medians = [
            statistics.median(values)
            for (_, _, row_method), values in measurements.items()
            if row_method == method
        ]
        runtime_summary.append(
            {
                "method": method,
                "event_budget_pairs": len(medians),
                "repetitions_per_pair": 7,
                "median_pair_runtime_seconds": statistics.median(medians),
                "p95_pair_runtime_seconds": float(np.percentile(medians, 95)),
                "max_pair_runtime_seconds": max(medians),
                "sum_pair_medians_seconds": sum(medians),
            }
        )
    runtime_path = ROOT / "results" / "runtime_summary.csv"
    with runtime_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(runtime_summary[0]))
        writer.writeheader()
        writer.writerows(runtime_summary)

    payload = {"alert_recall": alert_summary, "runtime": runtime_summary}
    (ROOT / "results" / "robustness_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
