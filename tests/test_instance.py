from mirrorplan.instance import (
    PreservationInstance,
    RequirementGroup,
    build_instance,
    interaction_components,
    load_instance,
    objective,
    save_instance,
)


def test_build_instance_propagates_all_deleted_ancestors() -> None:
    children = {
        "a": {"b", "x"},
        "b": {"c"},
        "x": {"c"},
        "c": {"d"},
    }
    instance = build_instance(children, {"a", "b"}, "0001", "0002")
    requirements = {
        target: set(group.members)
        for group in instance.groups
        for target in group.targets
    }
    assert requirements == {
        "x": {"a"},
        "c": {"a", "b"},
        "d": {"a", "b"},
    }
    assert instance.affected_targets == 3
    assert instance.multi_ancestor_targets == 2


def test_objective_is_conjunctive() -> None:
    instance = PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=2,
        candidates=("a", "b"),
        groups=(RequirementGroup(("a", "b"), ("x", "y")),),
    )
    assert objective(instance, set()) == 0
    assert objective(instance, {"a"}) == 0
    assert objective(instance, {"a", "b"}) == 2


def test_interaction_components() -> None:
    instance = PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=4,
        candidates=("a", "b", "c", "d"),
        groups=(
            RequirementGroup(("a", "b"), ("x",)),
            RequirementGroup(("c",), ("y",)),
            RequirementGroup(("d",), ("z",)),
        ),
    )
    components = {frozenset(component) for component in interaction_components(instance)}
    assert components == {frozenset({"a", "b"}), frozenset({"c"}), frozenset({"d"})}


def test_instance_round_trip_retains_hashes_and_requirements(tmp_path) -> None:
    instance = PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=2,
        candidates=("a", "b"),
        groups=(RequirementGroup(("a", "b"), ("x", "y")),),
        relation_sha256="relation-hash",
        deletion_sha256="deletion-hash",
    )
    path = tmp_path / "instance.json.gz"
    save_instance(instance, path)
    assert load_instance(path) == instance
