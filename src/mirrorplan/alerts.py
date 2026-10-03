"""Alert-set constructions for deletion-allocation sensitivity analyses."""

from __future__ import annotations

import random
from collections import defaultdict

from mirrorplan.instance import PreservationInstance


def candidate_impact(instance: PreservationInstance) -> dict[str, int]:
    scores = {candidate: 0 for candidate in instance.candidates}
    for group in instance.groups:
        for candidate in group.members:
            scores[candidate] += group.weight
    return scores


def construct_alert_set(
    instance: PreservationInstance,
    recall: float,
    mechanism: str,
    seed: int = 0,
) -> set[str]:
    """Construct an alerted subset with a fixed number of true candidates."""
    if not 0.0 <= recall <= 1.0:
        raise ValueError(f"Recall must be in [0, 1], got {recall}")
    candidates = list(instance.candidates)
    alert_count = min(len(candidates), round(recall * len(candidates)))
    miss_count = len(candidates) - alert_count
    generator = random.Random(seed)

    if mechanism == "uniform":
        return set(generator.sample(candidates, alert_count))

    if mechanism == "impact_targeted":
        scores = candidate_impact(instance)
        missed = set(
            sorted(candidates, key=lambda item: (-scores[item], item))[:miss_count]
        )
        return set(candidates) - missed

    if mechanism == "owner_clustered":
        by_owner: dict[str, list[str]] = defaultdict(list)
        for candidate in candidates:
            by_owner[candidate.split("/", 1)[0]].append(candidate)
        owners = sorted(by_owner)
        generator.shuffle(owners)
        missed: set[str] = set()
        for owner in owners:
            if len(missed) >= miss_count:
                break
            members = sorted(by_owner[owner])
            generator.shuffle(members)
            remaining = miss_count - len(missed)
            missed.update(members[:remaining])
        return set(candidates) - missed

    raise ValueError(f"Unknown alert mechanism: {mechanism}")


def restrict_to_alerts(
    instance: PreservationInstance, alerted: set[str]
) -> PreservationInstance:
    """Remove targets whose deleted prerequisites are not all alerted."""
    groups = tuple(
        group for group in instance.groups if set(group.members).issubset(alerted)
    )
    useful = {member for group in groups for member in group.members}
    return PreservationInstance(
        snapshot=instance.snapshot,
        event=instance.event,
        deleted_count=instance.deleted_count,
        candidates=tuple(sorted(useful)),
        groups=groups,
        relation_sha256=instance.relation_sha256,
        deletion_sha256=instance.deletion_sha256,
    )
