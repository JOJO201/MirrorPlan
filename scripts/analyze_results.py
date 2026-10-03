#!/usr/bin/env python3
"""Generate paper-facing tables, uncertainty intervals, and figures."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml

from deterministic_plots import configure_deterministic_pdf


configure_deterministic_pdf()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--protocol", type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def bootstrap_mean(values: list[float], seed: int, repetitions: int = 10000) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    indices = generator.integers(0, len(array), size=(repetitions, len(array)))
    means = array[indices].mean(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def main() -> None:
    args = parse_args()
    protocol_path = args.protocol or args.root / "protocols" / "main.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    raw_path = args.root / "results" / "raw" / "main_runs.csv"
    rows = read_csv(raw_path)
    results_dir = args.root / "results"
    figures_dir = results_dir / "figures"
    tables_dir = results_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    deterministic: dict[tuple[str, str, str], float] = {}
    random_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    values: dict[tuple[str, str, str], int] = {}
    runtimes: dict[tuple[str, str, str], float] = {}
    for row in rows:
        key = (row["event"], row["budget_fraction"], row["method"])
        if row["method"] == "random":
            random_values[(row["event"], row["budget_fraction"])].append(
                float(row["recovered_fraction"])
            )
        else:
            deterministic[key] = float(row["recovered_fraction"])
            values[key] = int(row["value"])
            runtimes[key] = float(row["runtime_seconds"])
    for (event, fraction), samples in random_values.items():
        deterministic[(event, fraction, "random")] = float(np.mean(samples))

    events = [str(value) for value in protocol["population"]["events"]]
    fractions = [f"{float(value):.4f}" for value in protocol["budgets"]["fractions"]]
    methods = ["factor_hybrid", "bundle_greedy", "peeling", "impact", "random"]
    seed = int(protocol["estimands"]["bootstrap_seed"])

    oracle_rows = []
    for event in events:
        for fraction in fractions:
            factor_value = values[(event, fraction, "factor_hybrid")]
            oracle_value = values[(event, fraction, "milp_exact")]
            oracle_rows.append(
                {
                    "event": event,
                    "budget_fraction": fraction,
                    "factor_value": factor_value,
                    "milp_value": oracle_value,
                    "agree": int(factor_value == oracle_value),
                }
            )
    if not all(row["agree"] for row in oracle_rows):
        raise SystemExit("FactorHybrid disagrees with independent MILP oracle")
    with (results_dir / "oracle_checks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(oracle_rows[0]))
        writer.writeheader()
        writer.writerows(oracle_rows)

    summary_rows = []
    for fraction in fractions:
        for method in methods:
            samples = [deterministic[(event, fraction, method)] for event in events]
            low, high = bootstrap_mean(samples, seed)
            summary_rows.append(
                {
                    "budget_fraction": fraction,
                    "method": method,
                    "events": len(samples),
                    "mean_recovered_fraction": float(np.mean(samples)),
                    "median_recovered_fraction": float(np.median(samples)),
                    "ci95_low": low,
                    "ci95_high": high,
                }
            )
    with (results_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    contrast_rows = []
    for fraction in fractions:
        for baseline in ("bundle_greedy", "peeling", "impact"):
            differences = [
                deterministic[(event, fraction, "factor_hybrid")]
                - deterministic[(event, fraction, baseline)]
                for event in events
            ]
            low, high = bootstrap_mean(differences, seed)
            contrast_rows.append(
                {
                    "budget_fraction": fraction,
                    "baseline": baseline,
                    "events": len(differences),
                    "mean_paired_gain": float(np.mean(differences)),
                    "median_paired_gain": float(np.median(differences)),
                    "events_strictly_better": sum(value > 0 for value in differences),
                    "ci95_low": low,
                    "ci95_high": high,
                }
            )
    with (results_dir / "paired_contrasts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(contrast_rows[0]))
        writer.writeheader()
        writer.writerows(contrast_rows)

    colors = {
        "factor_hybrid": "#0072B2",
        "bundle_greedy": "#009E73",
        "peeling": "#D55E00",
        "impact": "#CC79A7",
        "random": "#666666",
    }
    labels = {
        "factor_hybrid": "Exact",
        "bundle_greedy": "Bundle",
        "peeling": "Peeling",
        "impact": "Impact",
        "random": "Random",
    }
    markers = {
        "factor_hybrid": "o",
        "bundle_greedy": "s",
        "peeling": "^",
        "impact": "D",
        "random": "x",
    }
    plt.rcParams.update(
        {
            "font.size": 18,
            "axes.labelsize": 18,
            "xtick.labelsize": 18,
            "ytick.labelsize": 18,
            "legend.fontsize": 18,
            "text.usetex": True,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    x = np.asarray([float(value) * 100 for value in fractions])
    for method in methods:
        method_rows = [row for row in summary_rows if row["method"] == method]
        y = np.asarray([row["mean_recovered_fraction"] for row in method_rows])
        low = np.asarray([row["ci95_low"] for row in method_rows])
        high = np.asarray([row["ci95_high"] for row in method_rows])
        ax.plot(
            x,
            y,
            label=labels[method],
            color=colors[method],
            marker=markers[method],
            linewidth=2.5,
            markersize=9,
        )
        ax.fill_between(x, low, high, color=colors[method], alpha=0.10)
    ax.set_xlabel(r"Mirror budget (\% of candidates)")
    ax.set_ylabel("Recovered lineage fraction")
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout()
    fig.savefig(
        figures_dir / "recovery_curve.pdf",
        metadata={"CreationDate": None, "ModDate": None},
    )
    fig.savefig(figures_dir / "recovery_curve.png", dpi=220)
    plt.close(fig)

    primary_fraction = f"{float(protocol['estimands']['primary_budget_fraction']):.4f}"
    primary = next(
        row
        for row in contrast_rows
        if row["budget_fraction"] == primary_fraction and row["baseline"] == "impact"
    )
    diagnostics = json.loads(
        (results_dir / "instance_diagnostics.json").read_text(encoding="utf-8")
    )
    headline = {
        "events": len(events),
        "oracle_checks": len(oracle_rows),
        "oracle_agreement": all(row["agree"] for row in oracle_rows),
        "total_affected_targets": sum(row["affected_targets"] for row in diagnostics),
        "events_with_multi_ancestor_targets": sum(
            row["multi_ancestor_targets"] > 0 for row in diagnostics
        ),
        "largest_interaction_component": max(
            row["largest_component"] for row in diagnostics
        ),
        "bundle_greedy_exact_pairs": sum(
            values[(event, fraction, "bundle_greedy")]
            == values[(event, fraction, "milp_exact")]
            for event in events
            for fraction in fractions
        ),
        "total_event_budget_pairs": len(events) * len(fractions),
        "primary_contrast": primary,
    }
    (results_dir / "headline.json").write_text(
        json.dumps(headline, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(headline, indent=2))


if __name__ == "__main__":
    main()
