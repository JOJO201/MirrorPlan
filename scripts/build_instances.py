#!/usr/bin/env python3
"""Download pinned sources and construct compact deletion-event instances."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mirrorplan.data import (
    EVENT_PAIRS,
    fetch_event,
    load_children,
    load_deleted,
    sha256_file,
    source_paths,
)
from mirrorplan.instance import build_instance, interaction_components, save_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--events", nargs="*", default=[])
    parser.add_argument(
        "--discard-relations",
        action="store_true",
        help="Remove large relation CSVs after compact instances are written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_dir = args.root / "data" / "raw"
    instance_dir = args.root / "data" / "instances"
    manifest_path = args.root / "data" / "source_manifest.json"
    existing_manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else []
    )
    manifest_by_path = {
        row["relative_path"]: row for row in existing_manifest
    }
    expected_by_url = {row["url"]: row for row in existing_manifest}
    requested = set(args.events)
    pairs = [pair for pair in EVENT_PAIRS if not requested or pair[1] in requested]
    if requested - {event for _, event in EVENT_PAIRS}:
        raise SystemExit(f"Unknown event(s): {sorted(requested)}")

    diagnostics_path = args.root / "results" / "instance_diagnostics.json"
    existing_diagnostics = (
        json.loads(diagnostics_path.read_text(encoding="utf-8"))
        if diagnostics_path.exists()
        else []
    )
    diagnostics_by_event = {
        str(row["event"]): row for row in existing_diagnostics
    }
    for snapshot, event in pairs:
        records = fetch_event(raw_dir, snapshot, event)
        for record in records:
            expected = expected_by_url.get(record.url)
            if expected and (
                expected["sha256"] != record.sha256
                or int(expected["bytes"]) != record.bytes
            ):
                raise SystemExit(
                    "Pinned source hash mismatch for "
                    f"{record.url}: expected {expected['sha256']}, got {record.sha256}"
                )
            relative_path = str(Path(record.relative_path).relative_to(args.root))
            manifest_by_path[relative_path] = {
                **record.__dict__,
                "relative_path": relative_path,
            }
        relation_path, deletion_path = source_paths(raw_dir, snapshot, event)
        children = load_children(relation_path)
        deleted = load_deleted(deletion_path)
        instance = build_instance(
            children,
            deleted,
            snapshot,
            event,
            relation_sha256=sha256_file(relation_path),
            deletion_sha256=sha256_file(deletion_path),
        )
        output = instance_dir / f"event_{event}.json.gz"
        save_instance(instance, output)
        components = interaction_components(instance)
        row = instance.to_dict()["diagnostics"]
        row.update(
            {
                "snapshot": snapshot,
                "event": event,
                "interaction_components": len(components),
                "largest_component": max(map(len, components), default=0),
            }
        )
        diagnostics_by_event[event] = row
        print(json.dumps(row, sort_keys=True))
        if args.discard_relations:
            relation_path.unlink()

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = [manifest_by_path[key] for key in sorted(manifest_by_path)]
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = [
        diagnostics_by_event[key] for key in sorted(diagnostics_by_event)
    ]
    diagnostics_path.write_text(
        json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
