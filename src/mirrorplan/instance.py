"""Build compact preservation instances from dependency graphs and deletions."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RequirementGroup:
    members: tuple[str, ...]
    targets: tuple[str, ...]

    @property
    def weight(self) -> int:
        return len(self.targets)


@dataclass(frozen=True)
class PreservationInstance:
    snapshot: str
    event: str
    deleted_count: int
    candidates: tuple[str, ...]
    groups: tuple[RequirementGroup, ...]
    relation_sha256: str = ""
    deletion_sha256: str = ""

    @property
    def affected_targets(self) -> int:
        return sum(group.weight for group in self.groups)

    @property
    def max_rank(self) -> int:
        return max((len(group.members) for group in self.groups), default=0)

    @property
    def multi_ancestor_targets(self) -> int:
        return sum(group.weight for group in self.groups if len(group.members) > 1)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "snapshot": self.snapshot,
            "event": self.event,
            "deleted_count": self.deleted_count,
            "relation_sha256": self.relation_sha256,
            "deletion_sha256": self.deletion_sha256,
            "candidates": list(self.candidates),
            "groups": [
                {"members": list(group.members), "targets": list(group.targets)}
                for group in self.groups
            ],
            "diagnostics": {
                "deleted_count": self.deleted_count,
                "candidate_count": len(self.candidates),
                "affected_targets": self.affected_targets,
                "requirement_groups": len(self.groups),
                "max_rank": self.max_rank,
                "multi_ancestor_targets": self.multi_ancestor_targets,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PreservationInstance":
        if payload.get("schema_version") != 1:
            raise ValueError(f"Unsupported schema: {payload.get('schema_version')}")
        return cls(
            snapshot=payload["snapshot"],
            event=payload["event"],
            deleted_count=int(payload["deleted_count"]),
            relation_sha256=payload.get("relation_sha256", ""),
            deletion_sha256=payload.get("deletion_sha256", ""),
            candidates=tuple(payload["candidates"]),
            groups=tuple(
                RequirementGroup(tuple(group["members"]), tuple(group["targets"]))
                for group in payload["groups"]
            ),
        )


def build_instance(
    children: dict[str, set[str]],
    deleted: set[str],
    snapshot: str,
    event: str,
    relation_sha256: str = "",
    deletion_sha256: str = "",
) -> PreservationInstance:
    """Propagate each deleted prerequisite to every surviving descendant."""
    requirements: dict[str, set[str]] = defaultdict(set)
    for source in sorted(deleted):
        if source not in children:
            continue
        queue = deque(children[source])
        visited: set[str] = set()
        while queue:
            target = queue.popleft()
            if target in visited:
                continue
            visited.add(target)
            if target not in deleted:
                requirements[target].add(source)
            queue.extend(children.get(target, ()))

    grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for target, members in requirements.items():
        if members:
            grouped[tuple(sorted(members))].append(target)

    groups = tuple(
        RequirementGroup(members, tuple(sorted(targets)))
        for members, targets in sorted(grouped.items())
    )
    candidates = tuple(sorted({member for group in groups for member in group.members}))
    return PreservationInstance(
        snapshot=snapshot,
        event=event,
        deleted_count=len(deleted),
        candidates=candidates,
        groups=groups,
        relation_sha256=relation_sha256,
        deletion_sha256=deletion_sha256,
    )


def objective(instance: PreservationInstance, selected: Iterable[str]) -> int:
    selected_set = set(selected)
    return sum(
        group.weight
        for group in instance.groups
        if set(group.members).issubset(selected_set)
    )


def complementarity_core(instance: PreservationInstance) -> set[str]:
    """Return candidates that participate in a non-singleton requirement."""
    return {
        member
        for group in instance.groups
        if len(group.members) > 1
        for member in group.members
    }


def save_instance(instance: PreservationInstance, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(instance.to_dict(), handle, indent=2)
        handle.write("\n")


def load_instance(path: Path) -> PreservationInstance:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return PreservationInstance.from_dict(json.load(handle))


def interaction_components(instance: PreservationInstance) -> list[set[str]]:
    adjacency = {candidate: set() for candidate in instance.candidates}
    for group in instance.groups:
        members = set(group.members)
        for member in members:
            adjacency[member].update(members - {member})

    components: list[set[str]] = []
    unseen = set(instance.candidates)
    while unseen:
        root = min(unseen)
        component = {root}
        queue = deque([root])
        unseen.remove(root)
        while queue:
            node = queue.popleft()
            neighbors = adjacency[node] & unseen
            unseen.difference_update(neighbors)
            component.update(neighbors)
            queue.extend(neighbors)
        components.append(component)
    return components
