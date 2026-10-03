#!/usr/bin/env python3
"""Verify complete branch-charge proofs without numerical optimization."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from mirrorplan.certificates import (
    audit_branch_charge_certificate,
    read_branch_certificate,
)
from mirrorplan.instance import load_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--instance", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    if bool(args.certificate) != bool(args.instance):
        raise SystemExit("Provide both --certificate and --instance, or neither")
    if args.certificate:
        proof_rows = [
            {
                "proof_file": str(args.certificate),
                "event": args.certificate.name.split("_", 1)[0],
                "proof_sha256": sha256_file(args.certificate),
                "frozen_exact_value": "",
            }
        ]
    else:
        raw_path = root / "results" / "raw" / "complete_certificate_runs.csv"
        with raw_path.open(newline="", encoding="utf-8") as handle:
            proof_rows = list(csv.DictReader(handle))
    if not proof_rows:
        raise SystemExit("No complete certificates found")

    audits = []
    for row in proof_rows:
        proof_path = Path(row["proof_file"])
        if not proof_path.is_absolute():
            proof_path = root / proof_path
        if sha256_file(proof_path) != row["proof_sha256"]:
            raise ValueError(f"Proof hash mismatch: {proof_path}")
        event = row["event"]
        instance_path = (
            args.instance
            if args.instance
            else root / "data" / "instances" / f"event_{event}.json.gz"
        )
        proof = read_branch_certificate(proof_path)
        instance = load_instance(instance_path)
        audit = audit_branch_charge_certificate(instance, proof)
        if row["frozen_exact_value"] and audit.lower_value != int(
            row["frozen_exact_value"]
        ):
            raise ValueError(f"Verified value mismatch: {proof_path}")
        audits.append(audit)

    payload = {
        "status": "passed",
        "certificates": len(audits),
        "certified_optimal": sum(audit.certified_optimal for audit in audits),
        "total_nodes": sum(audit.nodes for audit in audits),
        "largest_nodes": max(audit.nodes for audit in audits),
        "largest_depth": max(audit.maximum_depth for audit in audits),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
