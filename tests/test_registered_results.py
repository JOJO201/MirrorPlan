import csv
import hashlib
import importlib
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def test_matched_certification_rows_and_summaries(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    verifier = importlib.import_module("verify_artifact")
    report = verifier.verify_matched_certification(ROOT)
    assert report == {"matched_certification_rows": 2240, "matched_certification_pairs": 80}


def test_confirmatory_rows_match_frozen_protocol_and_oracle() -> None:
    protocol_path = ROOT / "protocols" / "main.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(ROOT / "results" / "raw" / "main_runs.csv")
    events = {str(event) for event in protocol["population"]["events"]}
    fractions = {f"{float(value):.4f}" for value in protocol["budgets"]["fractions"]}
    methods = {"factor_hybrid", "milp_exact", "bundle_greedy", "peeling", "impact"}

    assert protocol["status"] == "frozen"
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    assert {row["event"] for row in rows} == events
    assert {row["budget_fraction"] for row in rows} == fractions
    assert len(rows) == len(events) * len(fractions) * (
        len(methods) + int(protocol["methods"]["random_seeds"])
    )

    values = {
        (row["event"], row["budget_fraction"], row["method"]): int(row["value"])
        for row in rows
        if row["method"] in methods
    }
    for event in events:
        for fraction in fractions:
            assert values[(event, fraction, "factor_hybrid")] == values[
                (event, fraction, "milp_exact")
            ]


def test_registered_robustness_rows_are_complete() -> None:
    protocol = yaml.safe_load(
        (ROOT / "protocols" / "alert_recall.yaml").read_text(encoding="utf-8")
    )
    rows = read_rows(ROOT / "results" / "raw" / "alert_recall_runs.csv")
    assert len(rows) == (
        len(protocol["events"])
        * len(protocol["alert_recall"])
        * int(protocol["seeds"])
    )
    assert {int(row["seed"]) for row in rows} == set(range(int(protocol["seeds"])))


def test_core_extension_is_complete_and_exact() -> None:
    protocol_path = ROOT / "protocols" / "core_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(ROOT / "results" / "raw" / "core_extension_runs.csv")
    expected = (
        len(protocol["events"])
        * len(protocol["budget_fractions"])
        * len(protocol["methods"])
        * int(protocol["runtime"]["measured_repetitions"])
    )
    assert len(rows) == expected
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    values: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        key = (row["event"], row["budget_fraction"])
        values.setdefault(key, set()).add(int(row["value"]))
    assert len(values) == len(protocol["events"]) * len(protocol["budget_fractions"])
    assert all(len(pair_values) == 1 for pair_values in values.values())


def test_structured_alert_stress_rows_match_protocol() -> None:
    protocol_path = ROOT / "protocols" / "alert_stress.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(ROOT / "results" / "raw" / "alert_stress_runs.csv")
    seeds_per_recall = sum(
        int(settings["seeds"])
        for settings in protocol["mechanisms"].values()
    )
    assert len(rows) == (
        len(protocol["events"])
        * len(protocol["alert_recall"])
        * seeds_per_recall
    )
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    for row in rows:
        expected_alerts = round(
            float(row["alert_recall"]) * int(row["original_candidates"])
        )
        assert int(row["alerted_candidates"]) == expected_alerts


def test_mechanism_ablation_rows_match_protocol() -> None:
    protocol_path = ROOT / "protocols" / "mechanism_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(ROOT / "results" / "mechanism_runs.csv")
    assert len(rows) == len(protocol["events"]) * len(protocol["budget_fractions"])
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    assert all(int(row["exact_value"]) >= int(row["additive_value"]) for row in rows)


def test_root_certificate_extension_matches_protocol() -> None:
    protocol_path = ROOT / "protocols" / "certificate_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(ROOT / "results" / "raw" / "certificate_runs.csv")
    expected = int(
        protocol["completeness_gate"]["expected_event_budget_pairs"]
    )
    assert len(rows) == expected
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    assert sum(int(row["bundle_certified_optimal"]) for row in rows) == 76
    assert sum(int(row["escalated_to_milp"]) for row in rows) == 4
    for row in rows:
        certificate = ROOT / row["certificate_file"]
        assert sha256_file(certificate) == row["certificate_sha256"]


def test_gap_extension_has_exact_complete_decomposition() -> None:
    protocol_path = ROOT / "protocols" / "gap_extension.yaml"
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(ROOT / "results" / "raw" / "gap_extension_runs.csv")
    assert len(rows) == int(protocol["completeness_gate"]["expected_rows"])
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    for row in rows:
        total = int(row["all_affected_targets"])
        assert int(row["exact_value"]) >= int(row["bundle_value"])
        assert total == sum(
            int(row[column])
            for column in (
                "recovered_value",
                "allocation_gap",
                "capacity_gap",
                "alert_gap",
            )
        )


def test_complete_certificates_match_frozen_exact_and_hashes() -> None:
    protocol_path = (
        ROOT / "protocols" / "complete_certificate_extension.yaml"
    )
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    rows = read_rows(
        ROOT / "results" / "raw" / "complete_certificate_runs.csv"
    )
    expected = int(
        protocol["completeness_gate"]["expected_event_budget_pairs"]
    )
    assert len(rows) == expected
    assert {row["protocol_sha256"] for row in rows} == {protocol_hash}
    assert {row["proof_stage"] for row in rows} == {
        "bundle_root",
        "exact_root",
        "branch_charge",
    }
    assert sum(row["proof_stage"] == "bundle_root" for row in rows) == 76
    assert sum(row["proof_stage"] == "exact_root" for row in rows) == 2
    assert sum(row["proof_stage"] == "branch_charge" for row in rows) == 2
    for row in rows:
        assert int(row["verified_lower_value"]) == int(
            row["frozen_exact_value"]
        )
        assert int(row["maximum_leaf_integer_upper"]) <= int(
            row["verified_lower_value"]
        )
        proof = ROOT / row["proof_file"]
        assert sha256_file(proof) == row["proof_sha256"]


def test_fse_revision_retains_objectives_and_covers_the_full_cascade() -> None:
    protocol = yaml.safe_load((ROOT / "protocols/fse_revision.yaml").read_text())
    assert protocol["status"] == "frozen"
    assert protocol["prior_outcomes_known"] is True
    raw = read_rows(ROOT / "results/raw/fse_decision_runtime.csv")
    frozen = {
        (r["event"], r["budget_fraction"], r["method"]): int(r["value"])
        for r in read_rows(ROOT / "results/raw/main_runs.csv")
        if r["method"] != "random"
    }
    coverage = {}
    for row in raw:
        key = (row["event"], row["budget_fraction"], row["method"])
        coverage.setdefault(key, set()).add(int(row["repetition"]))
        reference = "bundle_greedy" if row["method"] == "bundle_greedy" else "factor_hybrid"
        assert int(row["value"]) == frozen[(key[0], key[1], reference)]
    assert len(raw) == 1680
    assert len(coverage) == 240
    assert all(repetitions == set(range(7)) for repetitions in coverage.values())
    audited = [r for r in raw if r["method"] == "certify_or_escalate"]
    assert sum(r["proof_stage"] == "bundle_root" for r in audited) == 76 * 7
    assert sum(r["proof_stage"] == "exact_root" for r in audited) == 2 * 7
    assert sum(r["proof_stage"] == "branch_charge" for r in audited) == 2 * 7
    cases = read_rows(ROOT / "results/fse_escalation_cases.csv")
    assert len(cases) == 4
    assert sum(int(r["exact_value"]) - int(r["bundle_value"]) for r in cases) == 2
    assert all(int(r["gained_target_weight"]) - int(r["lost_target_weight"]) ==
               int(r["exact_value"]) - int(r["bundle_value"]) for r in cases)
