"""Run both certified workflows on a small synthetic preservation instance."""

import json

from mirrorplan.instance import PreservationInstance, RequirementGroup
from mirrorplan.planner import certify_or_escalate, milp_then_certify


def main() -> None:
    instance = PreservationInstance(
        snapshot="synthetic-before",
        event="synthetic-event",
        deleted_count=4,
        candidates=("a", "b", "c", "d"),
        groups=(
            RequirementGroup(("a", "b"), tuple(f"ab{i}" for i in range(5))),
            RequirementGroup(("b", "c"), tuple(f"bc{i}" for i in range(3))),
            RequirementGroup(("d",), ("d0", "d1")),
        ),
    )
    reports = []
    for planner in (certify_or_escalate, milp_then_certify):
        result = planner(instance, budget=2)
        reports.append({
            "workflow": planner.__name__,
            "selected": result.selected,
            "value": result.value,
            "proof_stage": result.proof_stage,
            "status": "independently checked optimal",
        })
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
