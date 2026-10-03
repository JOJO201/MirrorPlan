"""Heuristic-first planning with independently checked closure."""

from dataclasses import dataclass, replace
from time import perf_counter

from mirrorplan.algorithms import bundle_greedy, milp_exact
from mirrorplan.certificates import (
    BranchChargeCertificate,
    ChargeCertificate,
    audit_branch_charge_certificate,
    audit_charge_certificate,
    generate_branch_charge_certificate,
    optimized_charge_certificate,
)
from mirrorplan.instance import PreservationInstance


@dataclass(frozen=True)
class AuditedPlan:
    selected: tuple[str, ...]
    value: int
    proof_stage: str
    proof: ChargeCertificate | BranchChargeCertificate
    stage_seconds: dict[str, float]
    total_seconds: float


def certify_or_escalate(
    instance: PreservationInstance,
    budget: int,
    scale: int = 1_000_000_000,
    node_limit: int = 100_000,
) -> AuditedPlan:
    """Time the decision path from a loaded instance through final checking.

    Reuse the root charges when MILP improves the incumbent. A branch is
    generated only when the original charge bound still cannot close it.
    """
    if budget < 0 or scale <= 0 or node_limit <= 0:
        raise ValueError("Invalid budget, scale, or node limit")
    started = perf_counter()
    phases = {}

    phase = perf_counter()
    bundle = bundle_greedy(instance, budget)
    phases["bundle"] = perf_counter() - phase
    phase = perf_counter()
    root = optimized_charge_certificate(instance, budget, bundle.selected, scale)
    phases["root_generation"] = perf_counter() - phase
    phase = perf_counter()
    audit = audit_charge_certificate(instance, root)
    phases["root_audit"] = perf_counter() - phase
    selected = bundle.selected
    stage = "bundle_root"
    proof: ChargeCertificate | BranchChargeCertificate = root

    if not audit.certified_optimal:
        phase = perf_counter()
        exact = milp_exact(instance, budget)
        phases["milp"] = perf_counter() - phase
        selected = exact.selected
        candidate_index = {u: i for i, u in enumerate(instance.candidates)}
        root = replace(
            root, selected_indices=tuple(candidate_index[u] for u in selected)
        )
        phase = perf_counter()
        audit = audit_charge_certificate(instance, root)
        phases["rebind_audit"] = perf_counter() - phase
        proof = root
        stage = "exact_root"
        if not audit.certified_optimal:
            phase = perf_counter()
            proof = generate_branch_charge_certificate(
                instance, budget, selected, scale=scale, node_limit=node_limit
            )
            phases["branch_generation"] = perf_counter() - phase
            phase = perf_counter()
            audit = audit_branch_charge_certificate(instance, proof)
            phases["branch_audit"] = perf_counter() - phase
            stage = "branch_charge"

    if not audit.certified_optimal:
        raise AssertionError("Planner returned an unclosed proof")
    return AuditedPlan(
        selected, audit.lower_value, stage, proof, phases, perf_counter() - started
    )


def milp_then_certify(
    instance: PreservationInstance,
    budget: int,
    scale: int = 1_000_000_000,
    node_limit: int = 100_000,
) -> AuditedPlan:
    """Solve by global MILP, then use the same charge and branch auditor."""
    if budget < 0 or scale <= 0 or node_limit <= 0:
        raise ValueError("Invalid budget, scale, or node limit")
    started = perf_counter()
    phases = {}
    phase = perf_counter()
    exact = milp_exact(instance, budget)
    phases["milp"] = perf_counter() - phase
    phase = perf_counter()
    proof = optimized_charge_certificate(instance, budget, exact.selected, scale)
    phases["root_generation"] = perf_counter() - phase
    phase = perf_counter()
    audit = audit_charge_certificate(instance, proof)
    phases["root_audit"] = perf_counter() - phase
    stage = "exact_root"
    if not audit.certified_optimal:
        phase = perf_counter()
        proof = generate_branch_charge_certificate(
            instance, budget, exact.selected, scale=scale, node_limit=node_limit
        )
        phases["branch_generation"] = perf_counter() - phase
        phase = perf_counter()
        audit = audit_branch_charge_certificate(instance, proof)
        phases["branch_audit"] = perf_counter() - phase
        stage = "branch_charge"
    if not audit.certified_optimal:
        raise AssertionError("MILP-first planner returned an unclosed proof")
    return AuditedPlan(
        exact.selected, audit.lower_value, stage, proof, phases,
        perf_counter() - started,
    )
