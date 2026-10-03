from mirrorplan.alerts import (
    construct_alert_set,
    restrict_to_alerts,
)
from mirrorplan.instance import PreservationInstance, RequirementGroup


def alert_instance() -> PreservationInstance:
    return PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=4,
        candidates=("org/a", "org/b", "x/c", "y/d"),
        groups=(
            RequirementGroup(("org/a",), tuple(f"a{i}" for i in range(5))),
            RequirementGroup(("org/a", "org/b"), ("ab",)),
            RequirementGroup(("x/c",), ("c",)),
            RequirementGroup(("y/d",), ("d",)),
        ),
    )


def test_alert_mechanisms_preserve_requested_count() -> None:
    instance = alert_instance()
    for mechanism in ("uniform", "impact_targeted", "owner_clustered"):
        assert len(construct_alert_set(instance, 0.5, mechanism, seed=7)) == 2


def test_impact_targeted_misses_highest_impact_candidate() -> None:
    alerted = construct_alert_set(alert_instance(), 0.75, "impact_targeted")
    assert "org/a" not in alerted


def test_restriction_drops_incompletely_alerted_requirements() -> None:
    restricted = restrict_to_alerts(alert_instance(), {"org/a", "x/c", "y/d"})
    assert {group.members for group in restricted.groups} == {
        ("org/a",),
        ("x/c",),
        ("y/d",),
    }


def test_unknown_alert_mechanism_is_rejected() -> None:
    try:
        construct_alert_set(alert_instance(), 0.5, "unknown")
    except ValueError as error:
        assert "Unknown alert mechanism" in str(error)
    else:
        raise AssertionError("Unknown mechanism should fail")
