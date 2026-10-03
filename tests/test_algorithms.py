import itertools

from mirrorplan.algorithms import (
    bundle_greedy,
    core_factor_hybrid,
    factor_exact,
    factor_hybrid,
    impact_ranking,
    loss_aware_peeling,
    singleton_only_ranking,
)
from mirrorplan.instance import PreservationInstance, RequirementGroup, objective


def sample_instance() -> PreservationInstance:
    return PreservationInstance(
        snapshot="0001",
        event="0002",
        deleted_count=5,
        candidates=("a", "b", "c", "d", "e"),
        groups=(
            RequirementGroup(("a", "b"), tuple(f"ab{i}" for i in range(8))),
            RequirementGroup(("c",), tuple(f"c{i}" for i in range(4))),
            RequirementGroup(("d", "e"), tuple(f"de{i}" for i in range(7))),
        ),
    )


def brute_force(instance: PreservationInstance, budget: int) -> int:
    return max(
        objective(instance, selection)
        for size in range(budget + 1)
        for selection in itertools.combinations(instance.candidates, size)
    )


def test_factor_exact_matches_brute_force() -> None:
    instance = sample_instance()
    for budget in range(len(instance.candidates) + 1):
        solution = factor_exact(instance, budget)
        assert solution.value == brute_force(instance, budget)
        assert len(solution.selected) <= budget


def test_factor_hybrid_milp_fallback_matches_brute_force() -> None:
    instance = sample_instance()
    for budget in range(len(instance.candidates) + 1):
        solution = factor_hybrid(instance, budget, component_limit=1)
        assert solution.value == brute_force(instance, budget)
        assert len(solution.selected) <= budget


def test_core_factor_matches_brute_force_with_singleton_tail() -> None:
    instance = sample_instance()
    for budget in range(len(instance.candidates) + 1):
        solution = core_factor_hybrid(instance, budget)
        assert solution.value == brute_force(instance, budget)
        assert len(solution.selected) <= budget


def test_core_factor_milp_fallback_matches_brute_force() -> None:
    instance = sample_instance()
    for budget in range(len(instance.candidates) + 1):
        solution = core_factor_hybrid(instance, budget, component_limit=1)
        assert solution.value == brute_force(instance, budget)


def test_heuristics_return_feasible_solutions() -> None:
    instance = sample_instance()
    for method in (impact_ranking, bundle_greedy, loss_aware_peeling):
        solution = method(instance, 2)
        assert len(solution.selected) <= 2
        assert solution.value == objective(instance, solution.selected)


def test_singleton_only_ranking_optimizes_additive_ablation() -> None:
    solution = singleton_only_ranking(sample_instance(), 2)
    assert set(solution.selected) == {"a", "c"}
    assert solution.value == 4
