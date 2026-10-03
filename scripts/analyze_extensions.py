#!/usr/bin/env python3
"""Regenerate all post-main extension summaries from retained numeric rows."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml

from deterministic_plots import configure_deterministic_pdf


configure_deterministic_pdf()


ROOT = Path(__file__).parents[1]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def protocol(path: Path) -> tuple[dict, str]:
    return (
        yaml.safe_load(path.read_text(encoding="utf-8")),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bootstrap_mean(
    values: list[float], seed: int = 20260716
) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    indices = generator.integers(0, len(array), size=(10000, len(array)))
    return tuple(np.percentile(array[indices].mean(axis=1), [2.5, 97.5]))


def analyze_core() -> dict:
    config, protocol_hash = protocol(ROOT / "protocols" / "core_extension.yaml")
    rows = read_rows(ROOT / "results" / "raw" / "core_extension_runs.csv")
    if {row["protocol_sha256"] for row in rows} != {protocol_hash}:
        raise SystemExit("Core extension protocol hash mismatch")
    measurements: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    values: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in rows:
        measurements[(row["event"], row["budget_fraction"], row["method"])].append(
            float(row["runtime_seconds"])
        )
        values[(row["event"], row["budget_fraction"])].add(int(row["value"]))
    if len(values) != 80 or any(len(pair_values) != 1 for pair_values in values.values()):
        raise SystemExit("Core exact methods do not agree on all 80 pairs")
    runtime_rows = []
    for method in config["methods"]:
        pair_medians = [
            statistics.median(samples)
            for (_, _, row_method), samples in measurements.items()
            if row_method == method
        ]
        runtime_rows.append(
            {
                "method": method,
                "event_budget_pairs": len(pair_medians),
                "repetitions_per_pair": int(
                    config["runtime"]["measured_repetitions"]
                ),
                "median_pair_runtime_seconds": statistics.median(pair_medians),
                "p95_pair_runtime_seconds": float(np.percentile(pair_medians, 95)),
                "max_pair_runtime_seconds": max(pair_medians),
                "sum_pair_medians_seconds": sum(pair_medians),
            }
        )
    write_rows(ROOT / "results" / "core_runtime_summary.csv", runtime_rows)
    structure = read_rows(ROOT / "results" / "core_structure.csv")
    total_candidates = sum(int(row["candidates"]) for row in structure)
    total_core = sum(int(row["core_candidates"]) for row in structure)
    payload = {
        "protocol_sha256": protocol_hash,
        "events": len(structure),
        "event_budget_pairs": len(values),
        "runtime_rows": len(rows),
        "all_objectives_agree": True,
        "total_candidates": total_candidates,
        "total_core_candidates": total_core,
        "core_candidate_fraction": total_core / total_candidates,
        "events_with_empty_core": sum(int(row["core_candidates"]) == 0 for row in structure),
        "events_with_core_at_most_39": sum(int(row["core_candidates"]) <= 39 for row in structure),
        "largest_core_candidates": max(int(row["core_candidates"]) for row in structure),
        "largest_core_component": max(int(row["max_core_component"]) for row in structure),
        "runtime": runtime_rows,
    }
    (ROOT / "results" / "core_extension_summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def analyze_alert_stress() -> dict:
    config, protocol_hash = protocol(ROOT / "protocols" / "alert_stress.yaml")
    rows = read_rows(ROOT / "results" / "raw" / "alert_stress_runs.csv")
    if {row["protocol_sha256"] for row in rows} != {protocol_hash}:
        raise SystemExit("Alert stress protocol hash mismatch")
    per_event: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        per_event[(row["event"], row["mechanism"], row["alert_recall"])].append(
            float(row["restored_fraction"])
        )
    events = list(map(str, config["events"]))
    mechanisms = list(config["mechanisms"])
    recalls = [f"{float(value):.2f}" for value in config["alert_recall"]]
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
    write_rows(ROOT / "results" / "alert_stress_summary.csv", summary_rows)
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
    write_rows(ROOT / "results" / "alert_stress_contrasts.csv", contrast_rows)
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
        method_rows = [row for row in summary_rows if row["mechanism"] == mechanism]
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
    figures = ROOT / "results" / "figures"
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
    (ROOT / "results" / "alert_stress_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def analyze_gap() -> dict:
    config, protocol_hash = protocol(ROOT / "protocols" / "gap_extension.yaml")
    rows = read_rows(ROOT / "results" / "raw" / "gap_extension_runs.csv")
    expected_rows = int(config["completeness_gate"]["expected_rows"])
    if len(rows) != expected_rows:
        raise SystemExit(f"Gap extension expected {expected_rows} rows, got {len(rows)}")
    if {row["protocol_sha256"] for row in rows} != {protocol_hash}:
        raise SystemExit("Gap extension protocol hash mismatch")

    components = (
        "recovered_fraction",
        "allocation_gap_fraction",
        "capacity_gap_fraction",
        "alert_gap_fraction",
    )
    per_event: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(
        list
    )
    for row in rows:
        total = int(row["all_affected_targets"])
        integer_sum = sum(
            int(row[column])
            for column in (
                "recovered_value",
                "allocation_gap",
                "capacity_gap",
                "alert_gap",
            )
        )
        if integer_sum != total:
            raise SystemExit("Gap extension decomposition identity failed")
        if int(row["exact_value"]) < int(row["bundle_value"]):
            raise SystemExit("Gap extension exact value is below Bundle")
        fraction_sum = sum(float(row[column]) for column in components)
        if abs(fraction_sum - 1.0) > 1e-12:
            raise SystemExit("Gap extension fractional decomposition failed")
        key = (
            row["event"],
            row["mechanism"],
            row["alert_recall"],
            row["budget_fraction"],
        )
        per_event[key].append(row)

    events = list(map(str, config["events"]))
    mechanisms = list(config["mechanisms"])
    recalls = [f"{float(value):.2f}" for value in config["alert_recall"]]
    budgets = [f"{float(value):.4f}" for value in config["budget_fractions"]]
    expected_cells = len(events) * len(mechanisms) * len(recalls) * len(budgets)
    if len(per_event) != expected_cells:
        raise SystemExit(
            f"Gap extension expected {expected_cells} event cells, got {len(per_event)}"
        )

    event_rows = []
    event_values: dict[tuple[str, str, str], dict[str, list[float]]] = {}
    for mechanism in mechanisms:
        expected_seeds = int(config["mechanisms"][mechanism]["seeds"])
        for recall in recalls:
            for budget in budgets:
                by_component = {component: [] for component in components}
                for event in events:
                    samples = per_event[(event, mechanism, recall, budget)]
                    if len(samples) != expected_seeds:
                        raise SystemExit(
                            f"Expected {expected_seeds} seeds for "
                            f"{event}/{mechanism}/{recall}/{budget}, got {len(samples)}"
                        )
                    means = {
                        component: statistics.mean(
                            float(sample[component]) for sample in samples
                        )
                        for component in components
                    }
                    event_rows.append(
                        {
                            "event": event,
                            "mechanism": mechanism,
                            "alert_recall": recall,
                            "budget_fraction": budget,
                            "seeds": len(samples),
                            **means,
                        }
                    )
                    for component in components:
                        by_component[component].append(means[component])
                event_values[(mechanism, recall, budget)] = by_component
    write_rows(ROOT / "results" / "gap_event_means.csv", event_rows)

    summary_rows = []
    for mechanism in mechanisms:
        for recall in recalls:
            for budget in budgets:
                values = event_values[(mechanism, recall, budget)]
                summary = {
                    "mechanism": mechanism,
                    "alert_recall": recall,
                    "budget_fraction": budget,
                    "events": len(events),
                }
                for component in components:
                    low, high = bootstrap_mean(
                        values[component], int(config["bootstrap_seed"])
                    )
                    stem = component.removesuffix("_fraction")
                    summary[f"mean_{component}"] = statistics.mean(values[component])
                    summary[f"median_{component}"] = statistics.median(
                        values[component]
                    )
                    summary[f"{stem}_ci95_low"] = low
                    summary[f"{stem}_ci95_high"] = high
                summary_rows.append(summary)
    write_rows(ROOT / "results" / "gap_decomposition_summary.csv", summary_rows)

    contrast_rows = []
    for mechanism in ("owner_clustered", "impact_targeted"):
        for recall in recalls:
            for budget in budgets:
                candidate = event_values[(mechanism, recall, budget)]
                reference = event_values[("uniform", recall, budget)]
                for component in components:
                    differences = [
                        left - right
                        for left, right in zip(
                            candidate[component], reference[component], strict=True
                        )
                    ]
                    low, high = bootstrap_mean(
                        differences, int(config["bootstrap_seed"])
                    )
                    contrast_rows.append(
                        {
                            "mechanism": mechanism,
                            "reference": "uniform",
                            "alert_recall": recall,
                            "budget_fraction": budget,
                            "component": component,
                            "events": len(differences),
                            "mean_paired_difference": statistics.mean(differences),
                            "median_paired_difference": statistics.median(differences),
                            "ci95_low": low,
                            "ci95_high": high,
                        }
                    )
    write_rows(ROOT / "results" / "gap_contrasts.csv", contrast_rows)

    focus_budget = "0.1000"
    focus_rows = [
        row for row in summary_rows if row["budget_fraction"] == focus_budget
    ]
    labels = {
        "uniform": "Uniform",
        "owner_clustered": "Owner-clustered",
        "impact_targeted": "Impact-targeted",
    }
    component_labels = {
        "recovered_fraction": "Recovered",
        "allocation_gap_fraction": "Allocation gap",
        "capacity_gap_fraction": "Capacity gap",
        "alert_gap_fraction": "Alert gap",
    }
    colors = {
        "recovered_fraction": "#009E73",
        "allocation_gap_fraction": "#E69F00",
        "capacity_gap_fraction": "#56B4E9",
        "alert_gap_fraction": "#D55E00",
    }
    hatches = {
        "recovered_fraction": "",
        "allocation_gap_fraction": "///",
        "capacity_gap_fraction": "...",
        "alert_gap_fraction": "xx",
    }
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "text.usetex": True,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    # Match the final AAAI text width so 10 pt labels remain above 9 pt in print.
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.5), sharey=True)
    x = np.arange(len(recalls))
    for axis, mechanism in zip(axes, mechanisms, strict=True):
        bottoms = np.zeros(len(recalls))
        selected = {
            row["alert_recall"]: row
            for row in focus_rows
            if row["mechanism"] == mechanism
        }
        for component in components:
            heights = np.asarray(
                [selected[recall][f"mean_{component}"] for recall in recalls]
            )
            axis.bar(
                x,
                heights,
                bottom=bottoms,
                width=0.72,
                color=colors[component],
                edgecolor="#222222",
                linewidth=0.35,
                hatch=hatches[component],
                label=component_labels[component],
            )
            bottoms += heights
        axis.set_title(labels[mechanism])
        axis.set_xticks(x, [rf"{100 * float(recall):.0f}\%" for recall in recalls])
        axis.set_xlabel("Alert recall")
        axis.set_ylim(0, 1.0)
        axis.grid(axis="y", alpha=0.22)
        axis.set_axisbelow(True)
    axes[0].set_ylabel("Fraction of affected lineages")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        legend_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=4,
        frameon=False,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    figures = ROOT / "results" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        figures / "gap_decomposition.pdf",
        metadata={"CreationDate": None, "ModDate": None},
    )
    fig.savefig(figures / "gap_decomposition.png", dpi=220)
    plt.close(fig)

    payload = {
        "protocol_sha256": protocol_hash,
        "rows": len(rows),
        "event_cells": len(per_event),
        "decomposition_identity_verified": True,
        "exact_dominates_bundle_verified": True,
        "focus_budget_fraction": focus_budget,
        "focus_summary": focus_rows,
        "summary": summary_rows,
    }
    (ROOT / "results" / "gap_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def analyze_complete_certificates() -> dict:
    config, protocol_hash = protocol(
        ROOT / "protocols" / "complete_certificate_extension.yaml"
    )
    rows = read_rows(
        ROOT / "results" / "raw" / "complete_certificate_runs.csv"
    )
    expected = int(
        config["completeness_gate"]["expected_event_budget_pairs"]
    )
    if len(rows) != expected:
        raise SystemExit(
            f"Complete certificates expected {expected} rows, got {len(rows)}"
        )
    if {row["protocol_sha256"] for row in rows} != {protocol_hash}:
        raise SystemExit("Complete certificate protocol hash mismatch")
    for row in rows:
        if int(row["verified_lower_value"]) != int(row["frozen_exact_value"]):
            raise SystemExit("Complete certificate lower-value mismatch")
        if int(row["maximum_leaf_integer_upper"]) > int(
            row["verified_lower_value"]
        ):
            raise SystemExit("Complete certificate has an unclosed leaf")
        proof_path = ROOT / row["proof_file"]
        if not proof_path.exists() or sha256_file(proof_path) != row["proof_sha256"]:
            raise SystemExit(f"Complete certificate hash mismatch: {proof_path}")

    stages = ("bundle_root", "exact_root", "branch_charge")
    stage_rows = [
        {
            "proof_stage": stage,
            "event_budget_pairs": sum(row["proof_stage"] == stage for row in rows),
            "total_nodes": sum(
                int(row["proof_nodes"])
                for row in rows
                if row["proof_stage"] == stage
            ),
            "total_proof_bytes": sum(
                int(row["proof_bytes"])
                for row in rows
                if row["proof_stage"] == stage
            ),
        }
        for stage in stages
    ]
    write_rows(
        ROOT / "results" / "complete_certificate_summary.csv", stage_rows
    )
    payload = {
        "protocol_sha256": protocol_hash,
        "event_budget_pairs": len(rows),
        "all_exact_objectives_independently_verified": True,
        "bundle_root": sum(row["proof_stage"] == "bundle_root" for row in rows),
        "exact_root": sum(row["proof_stage"] == "exact_root" for row in rows),
        "branch_charge": sum(
            row["proof_stage"] == "branch_charge" for row in rows
        ),
        "milp_calls": sum(int(row["milp_called"]) for row in rows),
        "total_nodes": sum(int(row["proof_nodes"]) for row in rows),
        "largest_proof_nodes": max(int(row["proof_nodes"]) for row in rows),
        "largest_proof_leaves": max(int(row["proof_leaves"]) for row in rows),
        "largest_proof_depth": max(int(row["maximum_depth"]) for row in rows),
        "total_compressed_bytes": sum(int(row["proof_bytes"]) for row in rows),
        "median_verification_runtime_seconds": statistics.median(
            float(row["verification_runtime_seconds"]) for row in rows
        ),
        "maximum_verification_runtime_seconds": max(
            float(row["verification_runtime_seconds"]) for row in rows
        ),
        "stages": stage_rows,
    }
    (
        ROOT / "results" / "complete_certificate_headline.json"
    ).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def analyze_mechanism() -> dict:
    config, protocol_hash = protocol(ROOT / "protocols" / "mechanism_extension.yaml")
    rows = read_rows(ROOT / "results" / "mechanism_runs.csv")
    if {row["protocol_sha256"] for row in rows} != {protocol_hash}:
        raise SystemExit("Mechanism protocol hash mismatch")
    summary_rows = []
    for fraction_value in config["budget_fractions"]:
        fraction = f"{float(fraction_value):.4f}"
        selected = [row for row in rows if row["budget_fraction"] == fraction]
        gains = [float(row["paired_recovery_gain"]) for row in selected]
        low, high = bootstrap_mean(gains, int(config["bootstrap_seed"]))
        summary_rows.append(
            {
                "budget_fraction": fraction,
                "events": len(selected),
                "mean_exact_core_budget_fraction": statistics.mean(
                    float(row["exact_core_budget_fraction"]) for row in selected
                ),
                "mean_exact_multi_value_fraction": statistics.mean(
                    float(row["exact_multi_value_fraction"]) for row in selected
                ),
                "mean_paired_recovery_gain": statistics.mean(gains),
                "median_paired_recovery_gain": statistics.median(gains),
                "events_strictly_better": sum(gain > 0 for gain in gains),
                "gain_ci95_low": low,
                "gain_ci95_high": high,
            }
        )
    write_rows(ROOT / "results" / "mechanism_summary.csv", summary_rows)
    payload = {
        "protocol_sha256": protocol_hash,
        "rows": len(rows),
        "summary": summary_rows,
    }
    (ROOT / "results" / "mechanism_headline.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main() -> None:
    payload = {
        "core": analyze_core(),
        "alert_stress": analyze_alert_stress(),
        "gap": analyze_gap(),
        "complete_certificates": analyze_complete_certificates(),
        "mechanism": analyze_mechanism(),
    }
    print(
        json.dumps(
            {
                "status": "passed",
                "core_rows": payload["core"]["runtime_rows"],
                "alert_stress_rows": payload["alert_stress"]["rows"],
                "gap_rows": payload["gap"]["rows"],
                "complete_certificates": payload[
                    "complete_certificates"
                ]["event_budget_pairs"],
                "mechanism_rows": payload["mechanism"]["rows"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
