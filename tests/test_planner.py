import pytest

from mirrorplan.certificates import (
    BranchChargeCertificate,
    audit_branch_charge_certificate,
    audit_charge_certificate,
)
from mirrorplan.instance import PreservationInstance, RequirementGroup
from mirrorplan.planner import certify_or_escalate, milp_then_certify


@pytest.mark.parametrize(
    "groups,budget,expected,stage",
    [
        (((("a",), 3),), 1, 3, "bundle_root"),
        (((("a",), 3), (("b", "c"), 5)), 2, 5, "exact_root"),
        (((("a", "b"), 1), (("a", "c"), 1), (("b", "c"), 1)),
         2, 1, "branch_charge"),
    ],
)
def test_planner_paths(groups, budget, expected, stage):
    instance = PreservationInstance(
        "before", "after", 3, ("a", "b", "c"),
        tuple(RequirementGroup(members, tuple(f"t{i}_{j}" for j in range(weight)))
              for i, (members, weight) in enumerate(groups)),
    )
    result = certify_or_escalate(instance, budget, scale=1_000_000)
    assert result.value == expected
    assert result.proof_stage == stage
    checker = (audit_branch_charge_certificate
               if isinstance(result.proof, BranchChargeCertificate)
               else audit_charge_certificate)
    assert checker(instance, result.proof).certified_optimal
    assert sum(result.stage_seconds.values()) <= result.total_seconds


def test_planner_rejects_invalid_budget():
    instance = PreservationInstance("before", "after", 0, (), ())
    with pytest.raises(ValueError):
        certify_or_escalate(instance, -1)


@pytest.mark.parametrize(
    "groups,budget,expected,stage",
    [
        (((("a",), 3),), 1, 3, "exact_root"),
        (((("a",), 3), (("b", "c"), 5)), 2, 5, "exact_root"),
        (((("a", "b"), 1), (("a", "c"), 1), (("b", "c"), 1)),
         2, 1, "branch_charge"),
    ],
)
def test_milp_first_planner_paths(groups, budget, expected, stage):
    instance = PreservationInstance(
        "before", "after", 3, ("a", "b", "c"),
        tuple(RequirementGroup(members, tuple(f"t{i}_{j}" for j in range(weight)))
              for i, (members, weight) in enumerate(groups)),
    )
    result = milp_then_certify(instance, budget, scale=1_000_000)
    assert result.value == expected and result.proof_stage == stage
    checker = (audit_branch_charge_certificate
               if isinstance(result.proof, BranchChargeCertificate)
               else audit_charge_certificate)
    assert checker(instance, result.proof).certified_optimal
    assert "milp" in result.stage_seconds and "bundle" not in result.stage_seconds
    assert sum(result.stage_seconds.values()) <= result.total_seconds


@pytest.mark.parametrize("budget,scale,node_limit", [(-1, 1, 1), (0, 0, 1), (0, 1, 0)])
def test_milp_first_rejects_invalid_parameters(budget, scale, node_limit):
    instance = PreservationInstance("before", "after", 0, (), ())
    with pytest.raises(ValueError):
        milp_then_certify(instance, budget, scale, node_limit)
