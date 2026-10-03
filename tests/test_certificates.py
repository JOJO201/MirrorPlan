import itertools
from dataclasses import replace

import pytest

from mirrorplan.algorithms import bundle_greedy
from mirrorplan.certificates import (
    BranchChargeCertificate,
    BranchChargeNode,
    ChargeCertificate,
    audit_branch_charge_certificate,
    audit_charge_certificate,
    equal_charge_certificate,
    generate_branch_charge_certificate,
    optimized_charge_certificate,
    read_branch_certificate,
    read_certificate,
    write_branch_certificate,
    write_certificate,
)
from mirrorplan.instance import PreservationInstance, RequirementGroup, objective


def certificate_instance() -> PreservationInstance:
    return PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=4,
        candidates=("a", "b", "c", "d"),
        groups=(
            RequirementGroup(("a", "b"), tuple(f"ab{i}" for i in range(5))),
            RequirementGroup(("b", "c"), tuple(f"bc{i}" for i in range(3))),
            RequirementGroup(("d",), tuple(f"d{i}" for i in range(2))),
        ),
    )


def brute_force(instance: PreservationInstance, budget: int) -> int:
    return max(
        objective(instance, selected)
        for size in range(budget + 1)
        for selected in itertools.combinations(instance.candidates, size)
    )


@pytest.mark.parametrize("budget", range(5))
def test_equal_charge_is_valid_upper_bound(budget: int) -> None:
    instance = certificate_instance()
    selected = bundle_greedy(instance, budget).selected
    certificate = equal_charge_certificate(instance, budget, selected, scale=1000)
    audit = audit_charge_certificate(instance, certificate)
    assert audit.lower_value == objective(instance, selected)
    assert audit.integer_upper_bound >= brute_force(instance, budget)


@pytest.mark.parametrize("budget", range(5))
def test_optimized_charge_is_valid_upper_bound(budget: int) -> None:
    instance = certificate_instance()
    selected = bundle_greedy(instance, budget).selected
    certificate = optimized_charge_certificate(
        instance, budget, selected, scale=1_000_000
    )
    audit = audit_charge_certificate(instance, certificate)
    assert audit.integer_upper_bound >= brute_force(instance, budget)
    assert 0.0 <= audit.certified_ratio <= 1.0


def test_singletons_receive_exact_optimality_certificate() -> None:
    instance = PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=3,
        candidates=("a", "b", "c"),
        groups=(
            RequirementGroup(("a",), ("a1", "a2", "a3")),
            RequirementGroup(("b",), ("b1", "b2")),
            RequirementGroup(("c",), ("c1",)),
        ),
    )
    selected = bundle_greedy(instance, 2).selected
    certificate = optimized_charge_certificate(instance, 2, selected)
    assert audit_charge_certificate(instance, certificate).certified_optimal


def test_tampered_charge_is_rejected() -> None:
    instance = certificate_instance()
    certificate = equal_charge_certificate(
        instance, 2, bundle_greedy(instance, 2).selected, scale=100
    )
    rows = [list(row) for row in certificate.charge_units]
    rows[0][0] -= 1
    tampered = ChargeCertificate(
        event=certificate.event,
        budget=certificate.budget,
        scale=certificate.scale,
        instance_digest=certificate.instance_digest,
        method=certificate.method,
        selected_indices=certificate.selected_indices,
        charge_units=tuple(tuple(row) for row in rows),
    )
    with pytest.raises(ValueError, match="Charge conservation failed"):
        audit_charge_certificate(instance, tampered)


def test_certificate_serialization_is_deterministic(tmp_path) -> None:
    instance = certificate_instance()
    certificate = equal_charge_certificate(
        instance, 2, bundle_greedy(instance, 2).selected
    )
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"
    write_certificate(certificate, first)
    write_certificate(certificate, second)
    assert first.read_bytes() == second.read_bytes()
    assert read_certificate(first) == certificate


def triangle_instance() -> PreservationInstance:
    return PreservationInstance(
        snapshot="0001",
        event="triangle",
        deleted_count=3,
        candidates=("a", "b", "c"),
        groups=(
            RequirementGroup(("a", "b"), ("ab",)),
            RequirementGroup(("a", "c"), ("ac",)),
            RequirementGroup(("b", "c"), ("bc",)),
        ),
    )


def test_branch_certificate_closes_lp_integrality_gap() -> None:
    instance = triangle_instance()
    certificate = generate_branch_charge_certificate(
        instance, 2, ("a", "b"), scale=1_000_000
    )
    audit = audit_branch_charge_certificate(instance, certificate)
    assert audit.lower_value == brute_force(instance, 2) == 1
    assert audit.certified_optimal
    assert audit.nodes >= 3
    assert audit.leaves >= 2
    assert audit.maximum_depth >= 1


def _tamper_first_leaf(
    node: BranchChargeNode,
) -> tuple[BranchChargeNode, bool]:
    if node.kind == "bound" and node.charge_units:
        rows = [list(row) for row in node.charge_units]
        rows[0][0] -= 1
        return (
            replace(
                node,
                charge_units=tuple(tuple(row) for row in rows),
            ),
            True,
        )
    if node.kind == "branch" and node.include and node.exclude:
        include, changed = _tamper_first_leaf(node.include)
        if changed:
            return replace(node, include=include), True
        exclude, changed = _tamper_first_leaf(node.exclude)
        return replace(node, exclude=exclude), changed
    return node, False


def test_tampered_branch_leaf_is_rejected() -> None:
    instance = triangle_instance()
    certificate = generate_branch_charge_certificate(
        instance, 2, ("a", "b"), scale=10_000
    )
    root, changed = _tamper_first_leaf(certificate.root)
    assert changed
    tampered = BranchChargeCertificate(
        event=certificate.event,
        budget=certificate.budget,
        scale=certificate.scale,
        instance_digest=certificate.instance_digest,
        selected_indices=certificate.selected_indices,
        root=root,
    )
    with pytest.raises(ValueError, match="Leaf charge conservation failed"):
        audit_branch_charge_certificate(instance, tampered)


def test_branch_certificate_serialization_is_deterministic(tmp_path) -> None:
    instance = triangle_instance()
    certificate = generate_branch_charge_certificate(
        instance, 2, ("a", "b"), scale=10_000
    )
    first = tmp_path / "first.branch.json.gz"
    second = tmp_path / "second.branch.json.gz"
    write_branch_certificate(certificate, first)
    write_branch_certificate(certificate, second)
    assert first.read_bytes() == second.read_bytes()
    assert read_branch_certificate(first) == certificate
