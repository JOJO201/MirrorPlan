"""Solver-independent upper-bound certificates for preservation plans."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from mirrorplan.instance import PreservationInstance, objective


CERTIFICATE_SCHEMA_VERSION = 1
BRANCH_CERTIFICATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ChargeCertificate:
    """A nonnegative requirement-to-candidate charge assignment.

    Charges are integer numerators over ``scale`` and align with the instance's
    requirement-group and member order. Each group distributes exactly its
    integer weight. Candidate loads then give an upper bound by summing the
    largest ``budget`` loads.
    """

    event: str
    budget: int
    scale: int
    instance_digest: str
    method: str
    selected_indices: tuple[int, ...]
    charge_units: tuple[tuple[int, ...], ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": CERTIFICATE_SCHEMA_VERSION,
            "event": self.event,
            "budget": self.budget,
            "scale": self.scale,
            "instance_digest": self.instance_digest,
            "method": self.method,
            "selected_indices": list(self.selected_indices),
            "charge_units": [list(row) for row in self.charge_units],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ChargeCertificate":
        if payload.get("schema_version") != CERTIFICATE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported certificate schema: {payload.get('schema_version')}"
            )
        return cls(
            event=str(payload["event"]),
            budget=int(payload["budget"]),
            scale=int(payload["scale"]),
            instance_digest=str(payload["instance_digest"]),
            method=str(payload["method"]),
            selected_indices=tuple(map(int, payload["selected_indices"])),
            charge_units=tuple(
                tuple(map(int, row)) for row in payload["charge_units"]
            ),
        )


@dataclass(frozen=True)
class CertificateAudit:
    lower_value: int
    upper_units: int
    scale: int
    integer_upper_bound: int
    certified_ratio: float
    certified_optimal: bool

    @property
    def upper_bound(self) -> float:
        return self.upper_units / self.scale


@dataclass(frozen=True)
class BranchChargeNode:
    kind: str
    candidate_index: int | None = None
    charge_units: tuple[tuple[int, ...], ...] = ()
    include: BranchChargeNode | None = None
    exclude: BranchChargeNode | None = None

    def to_dict(self) -> dict:
        if self.kind == "bound":
            return {
                "kind": "bound",
                "charge_units": [list(row) for row in self.charge_units],
            }
        if self.kind == "branch":
            if (
                self.candidate_index is None
                or self.include is None
                or self.exclude is None
            ):
                raise ValueError("Incomplete branch node")
            return {
                "kind": "branch",
                "candidate_index": self.candidate_index,
                "include": self.include.to_dict(),
                "exclude": self.exclude.to_dict(),
            }
        raise ValueError(f"Unknown branch node kind: {self.kind}")

    @classmethod
    def from_dict(cls, payload: dict) -> BranchChargeNode:
        kind = str(payload.get("kind"))
        if kind == "bound":
            return cls(
                kind=kind,
                charge_units=tuple(
                    tuple(map(int, row)) for row in payload["charge_units"]
                ),
            )
        if kind == "branch":
            return cls(
                kind=kind,
                candidate_index=int(payload["candidate_index"]),
                include=cls.from_dict(payload["include"]),
                exclude=cls.from_dict(payload["exclude"]),
            )
        raise ValueError(f"Unknown branch node kind: {kind}")


@dataclass(frozen=True)
class BranchChargeCertificate:
    event: str
    budget: int
    scale: int
    instance_digest: str
    selected_indices: tuple[int, ...]
    root: BranchChargeNode

    def to_dict(self) -> dict:
        return {
            "schema_version": BRANCH_CERTIFICATE_SCHEMA_VERSION,
            "event": self.event,
            "budget": self.budget,
            "scale": self.scale,
            "instance_digest": self.instance_digest,
            "selected_indices": list(self.selected_indices),
            "root": self.root.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> BranchChargeCertificate:
        if payload.get("schema_version") != BRANCH_CERTIFICATE_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported branch certificate schema: "
                f"{payload.get('schema_version')}"
            )
        return cls(
            event=str(payload["event"]),
            budget=int(payload["budget"]),
            scale=int(payload["scale"]),
            instance_digest=str(payload["instance_digest"]),
            selected_indices=tuple(map(int, payload["selected_indices"])),
            root=BranchChargeNode.from_dict(payload["root"]),
        )


@dataclass(frozen=True)
class BranchCertificateAudit:
    lower_value: int
    nodes: int
    leaves: int
    maximum_depth: int
    maximum_leaf_integer_upper: int
    certified_optimal: bool


def instance_digest(instance: PreservationInstance) -> str:
    """Hash exactly the candidate and weighted-requirement optimization input."""
    payload = {
        "snapshot": instance.snapshot,
        "event": instance.event,
        "candidates": list(instance.candidates),
        "groups": [
            {"members": list(group.members), "weight": group.weight}
            for group in instance.groups
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _selected_indices(
    instance: PreservationInstance, selected: tuple[str, ...]
) -> tuple[int, ...]:
    index = {candidate: position for position, candidate in enumerate(instance.candidates)}
    try:
        return tuple(sorted(index[candidate] for candidate in selected))
    except KeyError as error:
        raise ValueError(f"Selected unknown candidate: {error.args[0]}") from error


def _apportion_exact(values: list[float], total_units: int) -> tuple[int, ...]:
    """Convert nonnegative floating shares to exact nonnegative integer shares."""
    if total_units < 0:
        raise ValueError("Charge total must be nonnegative")
    if not values:
        if total_units:
            raise ValueError("Cannot assign positive charge to an empty group")
        return ()
    clipped = [max(0.0, float(value)) for value in values]
    total = sum(clipped)
    if total <= 0.0:
        quotient, remainder = divmod(total_units, len(values))
        return tuple(
            quotient + (1 if index < remainder else 0)
            for index in range(len(values))
        )
    ideal = [value * total_units / total for value in clipped]
    units = [math.floor(value) for value in ideal]
    remainder = total_units - sum(units)
    order = sorted(
        range(len(values)),
        key=lambda index: (-(ideal[index] - units[index]), index),
    )
    for index in order[:remainder]:
        units[index] += 1
    if sum(units) != total_units or any(value < 0 for value in units):
        raise AssertionError("Failed to apportion charge exactly")
    return tuple(units)


def equal_charge_certificate(
    instance: PreservationInstance,
    budget: int,
    selected: tuple[str, ...],
    scale: int = 1_000_000_000,
) -> ChargeCertificate:
    if scale <= 0:
        raise ValueError("Certificate scale must be positive")
    rows = []
    for group in instance.groups:
        rows.append(
            _apportion_exact(
                [1.0] * len(group.members), group.weight * scale
            )
        )
    return ChargeCertificate(
        event=instance.event,
        budget=budget,
        scale=scale,
        instance_digest=instance_digest(instance),
        method="equal_charge",
        selected_indices=_selected_indices(instance, selected),
        charge_units=tuple(rows),
    )


def optimized_charge_certificate(
    instance: PreservationInstance,
    budget: int,
    selected: tuple[str, ...],
    scale: int = 1_000_000_000,
) -> ChargeCertificate:
    """Minimize the top-B candidate load and return a quantized certificate."""
    if scale <= 0:
        raise ValueError("Certificate scale must be positive")
    if budget < 0:
        raise ValueError("Budget must be nonnegative")

    import numpy as np
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix

    candidates = list(instance.candidates)
    candidate_index = {
        candidate: index for index, candidate in enumerate(candidates)
    }
    effective_budget = min(budget, len(candidates))
    incidence: list[tuple[int, int]] = []
    group_variables: list[list[int]] = []
    for group_index, group in enumerate(instance.groups):
        variables = []
        for member in group.members:
            variables.append(len(incidence))
            incidence.append((candidate_index[member], group_index))
        group_variables.append(variables)

    incidence_count = len(incidence)
    candidate_count = len(candidates)
    threshold_index = incidence_count
    excess_start = threshold_index + 1
    variable_count = excess_start + candidate_count

    objective_vector = np.zeros(variable_count)
    objective_vector[threshold_index] = effective_budget
    objective_vector[excess_start:] = 1.0

    upper_matrix = lil_matrix(
        (candidate_count, variable_count), dtype=float
    )
    for variable, (candidate, _) in enumerate(incidence):
        upper_matrix[candidate, variable] = 1.0
    for candidate in range(candidate_count):
        upper_matrix[candidate, threshold_index] = -1.0
        upper_matrix[candidate, excess_start + candidate] = -1.0

    equality_matrix = lil_matrix(
        (len(instance.groups), variable_count), dtype=float
    )
    equality_rhs = np.zeros(len(instance.groups))
    for group_index, (group, variables) in enumerate(
        zip(instance.groups, group_variables, strict=True)
    ):
        equality_matrix[group_index, variables] = 1.0
        equality_rhs[group_index] = group.weight

    result = linprog(
        objective_vector,
        A_ub=upper_matrix.tocsr(),
        b_ub=np.zeros(candidate_count),
        A_eq=equality_matrix.tocsr(),
        b_eq=equality_rhs,
        bounds=(0.0, None),
        method="highs",
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"Charge LP failed: {result.message}")

    rows = []
    for group, variables in zip(
        instance.groups, group_variables, strict=True
    ):
        values = [float(result.x[variable]) for variable in variables]
        rows.append(_apportion_exact(values, group.weight * scale))

    certificate = ChargeCertificate(
        event=instance.event,
        budget=budget,
        scale=scale,
        instance_digest=instance_digest(instance),
        method="optimized_charge",
        selected_indices=_selected_indices(instance, selected),
        charge_units=tuple(rows),
    )
    audit_charge_certificate(instance, certificate)
    return certificate


def audit_charge_certificate(
    instance: PreservationInstance, certificate: ChargeCertificate
) -> CertificateAudit:
    """Verify a charge certificate using only integer arithmetic."""
    if certificate.event != instance.event:
        raise ValueError(
            f"Certificate event {certificate.event} != {instance.event}"
        )
    if certificate.instance_digest != instance_digest(instance):
        raise ValueError("Certificate instance digest mismatch")
    if certificate.scale <= 0:
        raise ValueError("Certificate scale must be positive")
    if certificate.budget < 0:
        raise ValueError("Certificate budget must be nonnegative")
    if len(certificate.charge_units) != len(instance.groups):
        raise ValueError("Certificate group count mismatch")

    loads = [0] * len(instance.candidates)
    candidate_index = {
        candidate: index
        for index, candidate in enumerate(instance.candidates)
    }
    for group_index, (group, charges) in enumerate(
        zip(instance.groups, certificate.charge_units, strict=True)
    ):
        if len(charges) != len(group.members):
            raise ValueError(
                f"Certificate member count mismatch in group {group_index}"
            )
        if any(charge < 0 for charge in charges):
            raise ValueError(f"Negative charge in group {group_index}")
        expected = group.weight * certificate.scale
        if sum(charges) != expected:
            raise ValueError(
                f"Charge conservation failed in group {group_index}: "
                f"expected {expected}, got {sum(charges)}"
            )
        for member, charge in zip(group.members, charges, strict=True):
            loads[candidate_index[member]] += charge

    selected_indices = certificate.selected_indices
    if len(set(selected_indices)) != len(selected_indices):
        raise ValueError("Certificate selection contains duplicate indices")
    if any(index < 0 or index >= len(instance.candidates) for index in selected_indices):
        raise ValueError("Certificate selection index out of range")
    if len(selected_indices) > certificate.budget:
        raise ValueError("Certificate selection exceeds its budget")
    selected = tuple(instance.candidates[index] for index in selected_indices)
    lower_value = objective(instance, selected)

    effective_budget = min(certificate.budget, len(loads))
    upper_units = sum(sorted(loads, reverse=True)[:effective_budget])
    lower_units = lower_value * certificate.scale
    if lower_units > upper_units:
        raise ValueError(
            f"Invalid upper bound: lower {lower_units} > upper {upper_units}"
        )
    integer_upper = upper_units // certificate.scale
    ratio = lower_units / upper_units if upper_units else 1.0
    return CertificateAudit(
        lower_value=lower_value,
        upper_units=upper_units,
        scale=certificate.scale,
        integer_upper_bound=integer_upper,
        certified_ratio=ratio,
        certified_optimal=lower_value == integer_upper,
    )


def _residual_instance(
    instance: PreservationInstance,
    included_indices: frozenset[int],
    excluded_indices: frozenset[int],
) -> tuple[PreservationInstance, int]:
    index = {
        candidate: position
        for position, candidate in enumerate(instance.candidates)
    }
    groups = []
    constant_value = 0
    for group in instance.groups:
        member_indices = {index[member] for member in group.members}
        if member_indices.intersection(excluded_indices):
            continue
        remaining = tuple(
            member
            for member in group.members
            if index[member] not in included_indices
        )
        if not remaining:
            constant_value += group.weight
        else:
            groups.append(
                type(group)(members=remaining, targets=group.targets)
            )
    candidates = tuple(
        sorted({member for group in groups for member in group.members})
    )
    return (
        PreservationInstance(
            snapshot=instance.snapshot,
            event=instance.event,
            deleted_count=instance.deleted_count,
            candidates=candidates,
            groups=tuple(groups),
            relation_sha256=instance.relation_sha256,
            deletion_sha256=instance.deletion_sha256,
        ),
        constant_value,
    )


def _natural_lp_candidate_values(
    instance: PreservationInstance, budget: int
) -> tuple[float, ...]:
    if not instance.candidates:
        return ()

    import numpy as np
    from scipy.optimize import linprog
    from scipy.sparse import lil_matrix

    candidates = list(instance.candidates)
    candidate_index = {
        candidate: index for index, candidate in enumerate(candidates)
    }
    candidate_count = len(candidates)
    group_count = len(instance.groups)
    variable_count = candidate_count + group_count
    row_count = 1 + sum(len(group.members) for group in instance.groups)
    matrix = lil_matrix((row_count, variable_count), dtype=float)
    upper = np.zeros(row_count)
    matrix[0, :candidate_count] = 1.0
    upper[0] = min(budget, candidate_count)
    row = 1
    for group_index, group in enumerate(instance.groups):
        target_variable = candidate_count + group_index
        for member in group.members:
            matrix[row, target_variable] = 1.0
            matrix[row, candidate_index[member]] = -1.0
            row += 1
    objective_vector = np.zeros(variable_count)
    for group_index, group in enumerate(instance.groups):
        objective_vector[candidate_count + group_index] = -group.weight
    result = linprog(
        objective_vector,
        A_ub=matrix.tocsr(),
        b_ub=upper,
        bounds=(0.0, 1.0),
        method="highs",
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"Natural LP failed: {result.message}")
    return tuple(float(value) for value in result.x[:candidate_count])


def generate_branch_charge_certificate(
    instance: PreservationInstance,
    budget: int,
    selected: tuple[str, ...],
    scale: int = 1_000_000_000,
    node_limit: int = 100_000,
) -> BranchChargeCertificate:
    """Generate a complete include/exclude proof with charge-bounded leaves."""
    if budget < 0:
        raise ValueError("Budget must be nonnegative")
    if scale <= 0:
        raise ValueError("Certificate scale must be positive")
    if node_limit <= 0:
        raise ValueError("Node limit must be positive")
    selected_indices = _selected_indices(instance, selected)
    if len(selected_indices) > budget:
        raise ValueError("Selected plan exceeds budget")
    lower_value = objective(instance, selected)
    original_index = {
        candidate: index
        for index, candidate in enumerate(instance.candidates)
    }
    nodes_generated = 0

    def build(
        included: frozenset[int],
        excluded: frozenset[int],
    ) -> BranchChargeNode:
        nonlocal nodes_generated
        nodes_generated += 1
        if nodes_generated > node_limit:
            raise RuntimeError(f"Branch certificate exceeded {node_limit} nodes")

        residual, constant_value = _residual_instance(
            instance, included, excluded
        )
        remaining_budget = max(0, budget - len(included))
        if remaining_budget == 0 or not residual.groups:
            if constant_value > lower_value:
                raise ValueError("Selected plan is not globally optimal")
            return BranchChargeNode(kind="bound")

        charge = optimized_charge_certificate(
            residual,
            min(remaining_budget, len(residual.candidates)),
            (),
            scale=scale,
        )
        audit = audit_charge_certificate(residual, charge)
        total_upper_units = constant_value * scale + audit.upper_units
        if total_upper_units // scale <= lower_value:
            return BranchChargeNode(
                kind="bound", charge_units=charge.charge_units
            )

        values = _natural_lp_candidate_values(residual, remaining_budget)
        branch_candidate = min(
            zip(residual.candidates, values, strict=True),
            key=lambda item: (abs(item[1] - 0.5), item[0]),
        )[0]
        branch_index = original_index[branch_candidate]
        if branch_index in included or branch_index in excluded:
            raise AssertionError("Residual LP returned a decided candidate")
        return BranchChargeNode(
            kind="branch",
            candidate_index=branch_index,
            include=build(included | {branch_index}, excluded),
            exclude=build(included, excluded | {branch_index}),
        )

    certificate = BranchChargeCertificate(
        event=instance.event,
        budget=budget,
        scale=scale,
        instance_digest=instance_digest(instance),
        selected_indices=selected_indices,
        root=build(frozenset(), frozenset()),
    )
    audit_branch_charge_certificate(instance, certificate)
    return certificate


def audit_branch_charge_certificate(
    instance: PreservationInstance,
    certificate: BranchChargeCertificate,
) -> BranchCertificateAudit:
    """Verify complete branch coverage and every leaf using integer arithmetic."""
    if certificate.event != instance.event:
        raise ValueError(
            f"Certificate event {certificate.event} != {instance.event}"
        )
    if certificate.instance_digest != instance_digest(instance):
        raise ValueError("Certificate instance digest mismatch")
    if certificate.scale <= 0:
        raise ValueError("Certificate scale must be positive")
    if certificate.budget < 0:
        raise ValueError("Certificate budget must be nonnegative")
    if len(set(certificate.selected_indices)) != len(
        certificate.selected_indices
    ):
        raise ValueError("Certificate selection contains duplicate indices")
    if any(
        index < 0 or index >= len(instance.candidates)
        for index in certificate.selected_indices
    ):
        raise ValueError("Certificate selection index out of range")
    if len(certificate.selected_indices) > certificate.budget:
        raise ValueError("Certificate selection exceeds its budget")
    selected = tuple(
        instance.candidates[index] for index in certificate.selected_indices
    )
    lower_value = objective(instance, selected)

    def visit(
        node: BranchChargeNode,
        included: frozenset[int],
        excluded: frozenset[int],
        depth: int,
    ) -> tuple[int, int, int, int]:
        if node.kind == "branch":
            if (
                node.candidate_index is None
                or node.include is None
                or node.exclude is None
            ):
                raise ValueError("Incomplete branch node")
            candidate = node.candidate_index
            if candidate < 0 or candidate >= len(instance.candidates):
                raise ValueError("Branch candidate index out of range")
            if candidate in included or candidate in excluded:
                raise ValueError("Branch candidate was already decided")
            if len(included) >= certificate.budget:
                raise ValueError("Cannot include another candidate beyond budget")
            include_stats = visit(
                node.include, included | {candidate}, excluded, depth + 1
            )
            exclude_stats = visit(
                node.exclude, included, excluded | {candidate}, depth + 1
            )
            return (
                1 + include_stats[0] + exclude_stats[0],
                include_stats[1] + exclude_stats[1],
                max(include_stats[2], exclude_stats[2]),
                max(include_stats[3], exclude_stats[3]),
            )
        if node.kind != "bound":
            raise ValueError(f"Unknown branch node kind: {node.kind}")
        if node.candidate_index is not None or node.include or node.exclude:
            raise ValueError("Bound node contains branch fields")

        residual, constant_value = _residual_instance(
            instance, included, excluded
        )
        if len(node.charge_units) != len(residual.groups):
            raise ValueError("Bound leaf group count mismatch")
        candidate_index = {
            candidate: index
            for index, candidate in enumerate(residual.candidates)
        }
        loads = [0] * len(residual.candidates)
        for group_index, (group, charges) in enumerate(
            zip(residual.groups, node.charge_units, strict=True)
        ):
            if len(charges) != len(group.members):
                raise ValueError(
                    f"Bound leaf member count mismatch in group {group_index}"
                )
            if any(charge < 0 for charge in charges):
                raise ValueError(f"Negative leaf charge in group {group_index}")
            expected = group.weight * certificate.scale
            if sum(charges) != expected:
                raise ValueError(
                    f"Leaf charge conservation failed in group {group_index}"
                )
            for member, charge in zip(group.members, charges, strict=True):
                loads[candidate_index[member]] += charge
        remaining_budget = max(0, certificate.budget - len(included))
        residual_upper = sum(
            sorted(loads, reverse=True)[
                : min(remaining_budget, len(residual.candidates))
            ]
        )
        total_upper_units = constant_value * certificate.scale + residual_upper
        integer_upper = total_upper_units // certificate.scale
        if integer_upper > lower_value:
            raise ValueError(
                f"Unclosed branch leaf: upper {integer_upper} > lower "
                f"{lower_value}"
            )
        return (1, 1, depth, integer_upper)

    nodes, leaves, maximum_depth, maximum_leaf_upper = visit(
        certificate.root, frozenset(), frozenset(), 0
    )
    return BranchCertificateAudit(
        lower_value=lower_value,
        nodes=nodes,
        leaves=leaves,
        maximum_depth=maximum_depth,
        maximum_leaf_integer_upper=maximum_leaf_upper,
        certified_optimal=True,
    )


def write_certificate(certificate: ChargeCertificate, path: Path) -> None:
    """Write deterministic JSON, optionally gzip-compressed by suffix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            certificate.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("ascii")
    if path.suffix == ".gz":
        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0
            ) as handle:
                handle.write(payload)
    else:
        path.write_bytes(payload)


def read_certificate(path: Path) -> ChargeCertificate:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="ascii") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(path.read_text(encoding="ascii"))
    return ChargeCertificate.from_dict(payload)


def write_branch_certificate(
    certificate: BranchChargeCertificate, path: Path
) -> None:
    """Write a deterministic branch-charge certificate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            certificate.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("ascii")
    if path.suffix == ".gz":
        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0
            ) as handle:
                handle.write(payload)
    else:
        path.write_bytes(payload)


def read_branch_certificate(path: Path) -> BranchChargeCertificate:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="ascii") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(path.read_text(encoding="ascii"))
    return BranchChargeCertificate.from_dict(payload)
