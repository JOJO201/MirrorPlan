#!/usr/bin/env python3
"""Independently verify generated charge certificates with integer arithmetic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mirrorplan.certificates import audit_charge_certificate, read_certificate
from mirrorplan.instance import load_instance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--instance", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if bool(args.certificate) != bool(args.instance):
        raise SystemExit("Provide both --certificate and --instance, or neither")
    if args.certificate:
        pairs = [(args.certificate, args.instance)]
    else:
        pairs = []
        for certificate_path in sorted(
            (args.root / "results" / "certificates").glob("*.json.gz")
        ):
            event = certificate_path.name.split("_", 1)[0]
            pairs.append(
                (
                    certificate_path,
                    args.root / "data" / "instances" / f"event_{event}.json.gz",
                )
            )
    if not pairs:
        raise SystemExit("No charge certificates found")

    audits = []
    for certificate_path, instance_path in pairs:
        certificate = read_certificate(certificate_path)
        instance = load_instance(instance_path)
        audit = audit_charge_certificate(instance, certificate)
        audits.append(
            {
                "certificate": str(certificate_path),
                "event": certificate.event,
                "budget": certificate.budget,
                "lower_value": audit.lower_value,
                "upper_bound": audit.upper_bound,
                "integer_upper_bound": audit.integer_upper_bound,
                "certified_ratio": audit.certified_ratio,
                "certified_optimal": audit.certified_optimal,
            }
        )
    payload = {
        "status": "passed",
        "certificates": len(audits),
        "certified_optimal": sum(row["certified_optimal"] for row in audits),
        "minimum_certified_ratio": min(row["certified_ratio"] for row in audits),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
