#!/usr/bin/env python3
"""Describe interaction structure and mechanisms behind optimization gaps."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

from deterministic_plots import configure_deterministic_pdf
from mirrorplan.instance import interaction_components, load_instance


ROOT = Path(__file__).parents[1]
configure_deterministic_pdf()


def main() -> None:
    diagnostics = json.loads(
        (ROOT / "results" / "instance_diagnostics.json").read_text(encoding="utf-8")
    )
    path = ROOT / "results" / "structure_by_event.csv"
    first_instance = ROOT / "data" / "instances" / f"event_{diagnostics[0]['event']}.json.gz"
    if first_instance.is_file():
        output_rows = []
        rank_counts: Counter[int] = Counter()
        for row in diagnostics:
            event = row["event"]
            instance = load_instance(
                ROOT / "data" / "instances" / f"event_{event}.json.gz"
            )
            for group in instance.groups:
                rank_counts[len(group.members)] += group.weight
            components = interaction_components(instance)
            largest = max(components, key=len, default=set())
            owners = Counter(candidate.split("/", 1)[0] for candidate in largest)
            _, dominant_count = (
                owners.most_common(1)[0] if owners else ("", 0)
            )
            output_rows.append(
                {
                    **row,
                    "deleted_count": instance.deleted_count,
                    "multi_ancestor_fraction": (
                        row["multi_ancestor_targets"] / row["affected_targets"]
                    ),
                    "largest_component_dominant_owner": "[redacted]",
                    "largest_component_owner_share": (
                        dominant_count / len(largest) if largest else 0.0
                    ),
                }
            )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)

        total_targets = sum(rank_counts.values())
        payload = {
            "total_affected_targets": total_targets,
            "rank_counts": dict(sorted(rank_counts.items())),
            "multi_ancestor_targets": sum(
                count for rank, count in rank_counts.items() if rank > 1
            ),
            "multi_ancestor_fraction": (
                sum(count for rank, count in rank_counts.items() if rank > 1)
                / total_targets
            ),
            "largest_component_event": max(
                output_rows, key=lambda row: row["largest_component"]
            ),
        }
        (ROOT / "results" / "structure_summary.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    else:
        with path.open(newline="", encoding="utf-8") as handle:
            output_rows = list(csv.DictReader(handle))
        payload = json.loads(
            (ROOT / "results" / "structure_summary.json").read_text(
                encoding="utf-8"
            )
        )

    events = [row["event"] for row in output_rows]
    plt.rcParams.update(
        {
            "font.size": 18,
            "axes.labelsize": 18,
            "xtick.labelsize": 18,
            "ytick.labelsize": 18,
            "text.usetex": True,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, axes = plt.subplots(2, 1, figsize=(6.5, 4.0), sharex=True)
    axes[0].bar(
        events,
        [int(row["largest_component"]) for row in output_rows],
        color="#0072B2",
    )
    axes[0].set_title("Max interaction component", loc="left", pad=2)
    axes[0].grid(axis="y", alpha=0.25)
    axes[1].bar(
        events,
        [100 * float(row["multi_ancestor_fraction"]) for row in output_rows],
        color="#D55E00",
    )
    axes[1].set_title(r"Multi-ancestor targets (\%)", loc="left", pad=2)
    axes[1].grid(axis="y", alpha=0.25)
    axes[1].tick_params(axis="x", rotation=55)
    for label in axes[1].get_xticklabels():
        label.set_horizontalalignment("right")
    fig.tight_layout(h_pad=1.0)
    figures = ROOT / "results" / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        figures / "event_structure.pdf",
        metadata={"CreationDate": None, "ModDate": None},
    )
    fig.savefig(figures / "event_structure.png", dpi=220)
    plt.close(fig)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
