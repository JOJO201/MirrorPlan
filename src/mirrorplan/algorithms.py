"""Exact and heuristic solvers for budgeted lineage preservation."""

from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass

from mirrorplan.instance import (
    PreservationInstance,
    complementarity_core,
    interaction_components,
    objective,
)


@dataclass(frozen=True)
class Solution:
    method: str
    budget: int
    selected: tuple[str, ...]
    value: int
    runtime_seconds: float
    optimal: bool = False


def _solution(
    method: str,
    instance: PreservationInstance,
    budget: int,
    selected: set[str],
    started: float,
    optimal: bool = False,
) -> Solution:
    if len(selected) > budget:
        raise AssertionError(f"{method} exceeded budget {budget}: {len(selected)}")
    return Solution(
        method=method,
        budget=budget,
        selected=tuple(sorted(selected)),
        value=objective(instance, selected),
        runtime_seconds=time.perf_counter() - started,
        optimal=optimal,
    )


def impact_ranking(instance: PreservationInstance, budget: int) -> Solution:
    started = time.perf_counter()
    scores = {candidate: 0 for candidate in instance.candidates}
    for group in instance.groups:
        for candidate in group.members:
            scores[candidate] += group.weight
    ranked = sorted(scores, key=lambda candidate: (-scores[candidate], candidate))
    selected = set(ranked[: min(budget, len(ranked))])
    return _solution("impact", instance, budget, selected, started)


def singleton_only_ranking(instance: PreservationInstance, budget: int) -> Solution:
    """Optimize the additive ablation that drops non-singleton requirements."""
    started = time.perf_counter()
    scores = {candidate: 0 for candidate in instance.candidates}
    for group in instance.groups:
        if len(group.members) == 1:
            scores[group.members[0]] += group.weight
    ranked = sorted(scores, key=lambda candidate: (-scores[candidate], candidate))
    selected = set(ranked[: min(budget, len(ranked))])
    return _solution("additive_ablation", instance, budget, selected, started)


def random_selection(
    instance: PreservationInstance, budget: int, seed: int
) -> Solution:
    started = time.perf_counter()
    generator = random.Random(seed)
    count = min(budget, len(instance.candidates))
    selected = set(generator.sample(list(instance.candidates), count))
    return _solution("random", instance, budget, selected, started)


def bundle_greedy(instance: PreservationInstance, budget: int) -> Solution:
    """Add the most efficient requirement bundle at each step."""
    started = time.perf_counter()
    selected: set[str] = set()
    while len(selected) < min(budget, len(instance.candidates)):
        best: tuple[float, int, tuple[str, ...], set[str]] | None = None
        current_value = objective(instance, selected)
        for group in instance.groups:
            additions = set(group.members) - selected
            if not additions or len(selected) + len(additions) > budget:
                continue
            candidate_value = objective(instance, selected | additions)
            gain = candidate_value - current_value
            if gain <= 0:
                continue
            key = (
                gain / len(additions),
                gain,
                tuple(sorted(additions)),
                additions,
            )
            if best is None or key[:3] > best[:3]:
                best = key
        if best is None:
            break
        selected.update(best[3])

    if len(selected) < min(budget, len(instance.candidates)):
        impact = impact_ranking(instance, len(instance.candidates)).selected
        for candidate in impact:
            if len(selected) >= budget:
                break
            selected.add(candidate)
    return _solution("bundle_greedy", instance, budget, selected, started)


def loss_aware_peeling(instance: PreservationInstance, budget: int) -> Solution:
    """Start with all candidates and peel the least damaging one repeatedly."""
    started = time.perf_counter()
    selected = set(instance.candidates)
    target_budget = min(budget, len(selected))
    active_groups = set(range(len(instance.groups)))
    incident: dict[str, list[int]] = {candidate: [] for candidate in selected}
    losses = {candidate: 0 for candidate in selected}
    versions = {candidate: 0 for candidate in selected}
    for index, group in enumerate(instance.groups):
        for candidate in group.members:
            incident[candidate].append(index)
            losses[candidate] += group.weight

    heap = [(losses[candidate], candidate, 0) for candidate in selected]
    heapq.heapify(heap)
    while len(selected) > target_budget:
        while True:
            loss, candidate, version = heapq.heappop(heap)
            if candidate in selected and version == versions[candidate]:
                break
        selected.remove(candidate)
        for group_index in incident[candidate]:
            if group_index not in active_groups:
                continue
            active_groups.remove(group_index)
            group = instance.groups[group_index]
            for other in group.members:
                if other in selected:
                    losses[other] -= group.weight
                    versions[other] += 1
                    heapq.heappush(
                        heap, (losses[other], other, versions[other])
                    )
    return _solution("peeling", instance, budget, selected, started)


def _component_frontier(
    candidates: list[str],
    weighted_groups: list[tuple[tuple[str, ...], int]],
    budget: int,
) -> list[tuple[int, int]]:
    """Return (value, subset mask) for each local cardinality."""
    size = len(candidates)
    index = {candidate: position for position, candidate in enumerate(candidates)}
    values = [0] * (1 << size)
    for members, weight in weighted_groups:
        mask = 0
        for member in members:
            mask |= 1 << index[member]
        values[mask] += weight

    # Subset zeta transform: values[S] = sum of weights of all groups E subset S.
    for bit in range(size):
        bit_mask = 1 << bit
        for mask in range(1 << size):
            if mask & bit_mask:
                values[mask] += values[mask ^ bit_mask]

    limit = min(budget, size)
    frontier = [(-1, 0) for _ in range(limit + 1)]
    for mask, value in enumerate(values):
        count = mask.bit_count()
        if count <= limit and value > frontier[count][0]:
            frontier[count] = (value, mask)
    return frontier


def factor_exact(
    instance: PreservationInstance,
    budget: int,
    component_limit: int = 22,
) -> Solution:
    """Solve exactly by interaction components and a global knapsack DP."""
    started = time.perf_counter()
    components = interaction_components(instance)
    if any(len(component) > component_limit for component in components):
        largest = max(map(len, components), default=0)
        raise ValueError(
            f"Largest interaction component {largest} exceeds limit {component_limit}"
        )

    component_data: list[tuple[list[str], list[tuple[int, int]]]] = []
    for component in components:
        candidates = sorted(component)
        groups = [
            (group.members, group.weight)
            for group in instance.groups
            if group.members and group.members[0] in component
        ]
        component_data.append(
            (candidates, _component_frontier(candidates, groups, budget))
        )

    effective_budget = min(budget, len(instance.candidates))
    dp = [-math.inf] * (effective_budget + 1)
    choices: list[list[tuple[int, int] | None]] = []
    dp[0] = 0
    for _, frontier in component_data:
        next_dp = [-math.inf] * (effective_budget + 1)
        choice_row: list[tuple[int, int] | None] = [None] * (
            effective_budget + 1
        )
        for previous_budget, previous_value in enumerate(dp):
            if previous_value == -math.inf:
                continue
            for local_budget, (local_value, local_mask) in enumerate(frontier):
                total_budget = previous_budget + local_budget
                if total_budget > effective_budget or local_value < 0:
                    continue
                total_value = previous_value + local_value
                if total_value > next_dp[total_budget]:
                    next_dp[total_budget] = total_value
                    choice_row[total_budget] = (previous_budget, local_mask)
        dp = next_dp
        choices.append(choice_row)

    used_budget = max(range(effective_budget + 1), key=lambda value: dp[value])
    selected: set[str] = set()
    for component_index in range(len(component_data) - 1, -1, -1):
        choice = choices[component_index][used_budget]
        if choice is None:
            raise AssertionError("Broken component-DP backpointer")
        previous_budget, local_mask = choice
        candidates, _ = component_data[component_index]
        selected.update(
            candidate
            for index, candidate in enumerate(candidates)
            if local_mask & (1 << index)
        )
        used_budget = previous_budget
    return _solution(
        "factor_exact", instance, budget, selected, started, optimal=True
    )


def _component_instance(
    instance: PreservationInstance, component: set[str]
) -> PreservationInstance:
    groups = tuple(
        group
        for group in instance.groups
        if group.members and group.members[0] in component
    )
    return PreservationInstance(
        snapshot=instance.snapshot,
        event=instance.event,
        deleted_count=instance.deleted_count,
        candidates=tuple(sorted(component)),
        groups=groups,
        relation_sha256=instance.relation_sha256,
        deletion_sha256=instance.deletion_sha256,
    )


def factor_hybrid(
    instance: PreservationInstance,
    budget: int,
    component_limit: int = 22,
) -> Solution:
    """Exact component DP with local MILP frontiers for large components."""
    started = time.perf_counter()
    component_data: list[tuple[list[str], list[tuple[int, int]]]] = []
    for component in interaction_components(instance):
        candidates = sorted(component)
        local_limit = min(budget, len(candidates))
        if len(component) <= component_limit:
            weighted_groups = [
                (group.members, group.weight)
                for group in instance.groups
                if group.members and group.members[0] in component
            ]
            frontier = _component_frontier(
                candidates, weighted_groups, local_limit
            )
        else:
            local_instance = _component_instance(instance, component)
            index = {candidate: position for position, candidate in enumerate(candidates)}
            frontier = []
            for local_budget in range(local_limit + 1):
                solution = milp_exact(local_instance, local_budget)
                mask = 0
                for candidate in solution.selected:
                    mask |= 1 << index[candidate]
                frontier.append((solution.value, mask))
        component_data.append((candidates, frontier))

    effective_budget = min(budget, len(instance.candidates))
    dp = [-math.inf] * (effective_budget + 1)
    choices: list[list[tuple[int, int] | None]] = []
    dp[0] = 0
    for _, frontier in component_data:
        next_dp = [-math.inf] * (effective_budget + 1)
        choice_row: list[tuple[int, int] | None] = [None] * (
            effective_budget + 1
        )
        for previous_budget, previous_value in enumerate(dp):
            if previous_value == -math.inf:
                continue
            for local_budget, (local_value, local_mask) in enumerate(frontier):
                total_budget = previous_budget + local_budget
                if total_budget > effective_budget:
                    continue
                total_value = previous_value + local_value
                if total_value > next_dp[total_budget]:
                    next_dp[total_budget] = total_value
                    choice_row[total_budget] = (previous_budget, local_mask)
        dp = next_dp
        choices.append(choice_row)

    used_budget = max(range(effective_budget + 1), key=lambda value: dp[value])
    selected: set[str] = set()
    for component_index in range(len(component_data) - 1, -1, -1):
        choice = choices[component_index][used_budget]
        if choice is None:
            raise AssertionError("Broken hybrid-DP backpointer")
        previous_budget, local_mask = choice
        candidates, _ = component_data[component_index]
        selected.update(
            candidate
            for index, candidate in enumerate(candidates)
            if local_mask & (1 << index)
        )
        used_budget = previous_budget
    return _solution(
        "factor_hybrid", instance, budget, selected, started, optimal=True
    )


def core_factor_hybrid(
    instance: PreservationInstance,
    budget: int,
    component_limit: int = 22,
) -> Solution:
    """Solve exactly after separating the additive singleton-only tail.

    Candidates outside the complementarity core occur only in singleton
    requirements. Their exact local frontier is therefore obtained by sorting
    singleton weights. Core components use enumeration or local MILP frontiers,
    then a knapsack DP allocates the global budget.
    """
    started = time.perf_counter()
    core = complementarity_core(instance)
    component_data: list[tuple[list[str], list[tuple[int, int]]]] = []

    for component in interaction_components(instance):
        if not component.intersection(core):
            continue
        candidates = sorted(component)
        local_limit = min(budget, len(candidates))
        if len(component) <= component_limit:
            weighted_groups = [
                (group.members, group.weight)
                for group in instance.groups
                if group.members and group.members[0] in component
            ]
            frontier = _component_frontier(
                candidates, weighted_groups, local_limit
            )
        else:
            local_instance = _component_instance(instance, component)
            index = {
                candidate: position for position, candidate in enumerate(candidates)
            }
            frontier = []
            for local_budget in range(local_limit + 1):
                solution = milp_exact(local_instance, local_budget)
                mask = 0
                for candidate in solution.selected:
                    mask |= 1 << index[candidate]
                frontier.append((solution.value, mask))
        component_data.append((candidates, frontier))

    tail_weights = {candidate: 0 for candidate in instance.candidates if candidate not in core}
    for group in instance.groups:
        if len(group.members) == 1 and group.members[0] in tail_weights:
            tail_weights[group.members[0]] += group.weight
    if tail_weights:
        tail = sorted(tail_weights, key=lambda item: (-tail_weights[item], item))
        tail_limit = min(budget, len(tail))
        frontier = [(0, 0)]
        value = 0
        mask = 0
        for index, candidate in enumerate(tail[:tail_limit]):
            value += tail_weights[candidate]
            mask |= 1 << index
            frontier.append((value, mask))
        component_data.append((tail, frontier))

    effective_budget = min(budget, len(instance.candidates))
    dp = [-math.inf] * (effective_budget + 1)
    choices: list[list[tuple[int, int] | None]] = []
    dp[0] = 0
    for _, frontier in component_data:
        next_dp = [-math.inf] * (effective_budget + 1)
        choice_row: list[tuple[int, int] | None] = [None] * (
            effective_budget + 1
        )
        for previous_budget, previous_value in enumerate(dp):
            if previous_value == -math.inf:
                continue
            for local_budget, (local_value, local_mask) in enumerate(frontier):
                total_budget = previous_budget + local_budget
                if total_budget > effective_budget or local_value < 0:
                    continue
                total_value = previous_value + local_value
                if total_value > next_dp[total_budget]:
                    next_dp[total_budget] = total_value
                    choice_row[total_budget] = (previous_budget, local_mask)
        dp = next_dp
        choices.append(choice_row)

    used_budget = max(range(effective_budget + 1), key=lambda value: dp[value])
    selected: set[str] = set()
    for component_index in range(len(component_data) - 1, -1, -1):
        choice = choices[component_index][used_budget]
        if choice is None:
            raise AssertionError("Broken core-factor DP backpointer")
        previous_budget, local_mask = choice
        candidates, _ = component_data[component_index]
        selected.update(
            candidate
            for index, candidate in enumerate(candidates)
            if local_mask & (1 << index)
        )
        used_budget = previous_budget
    return _solution(
        "core_factor", instance, budget, selected, started, optimal=True
    )


def milp_exact(instance: PreservationInstance, budget: int) -> Solution:
    """Independent global MILP oracle used to validate FactorExact."""
    started = time.perf_counter()
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    candidates = list(instance.candidates)
    candidate_index = {candidate: index for index, candidate in enumerate(candidates)}
    candidate_count = len(candidates)
    group_count = len(instance.groups)
    variable_count = candidate_count + group_count
    row_count = 1 + sum(len(group.members) for group in instance.groups)
    matrix = lil_matrix((row_count, variable_count), dtype=float)
    lower = np.full(row_count, -np.inf)
    upper = np.zeros(row_count)
    matrix[0, :candidate_count] = 1
    upper[0] = min(budget, candidate_count)
    row = 1
    for group_index, group in enumerate(instance.groups):
        target_variable = candidate_count + group_index
        for member in group.members:
            matrix[row, target_variable] = 1
            matrix[row, candidate_index[member]] = -1
            row += 1

    objective_vector = np.zeros(variable_count)
    for group_index, group in enumerate(instance.groups):
        objective_vector[candidate_count + group_index] = -group.weight
    result = milp(
        c=objective_vector,
        integrality=np.ones(variable_count),
        bounds=Bounds(np.zeros(variable_count), np.ones(variable_count)),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": 600, "mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"MILP failed: {result.message}")
    selected = {
        candidate
        for index, candidate in enumerate(candidates)
        if result.x[index] >= 0.5
    }
    return _solution("milp_exact", instance, budget, selected, started, optimal=True)
