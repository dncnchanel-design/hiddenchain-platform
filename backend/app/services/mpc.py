from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


FIELD_MODULUS = (2**127) - 1
ALGORITHM_CODE = "ADDITIVE_SECRET_SHARING_SUM_V1"
CAPABILITY_LABEL = "LOCAL_REAL"
CAPABILITY_STATUS = "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST"


class MPCValidationError(ValueError):
    pass


class RandomSource(Protocol):
    def randrange(self, stop: int) -> int: ...


@dataclass(frozen=True, slots=True)
class PartyShare:
    participant_id: str
    value: int


@dataclass(frozen=True, slots=True)
class SharedSecret:
    owner_id: str
    participant_order: tuple[str, ...]
    shares: tuple[PartyShare, ...]
    modulus: int
    absolute_bound: int
    transcript_hash: str


@dataclass(frozen=True, slots=True)
class AggregateShares:
    participant_order: tuple[str, ...]
    shares: tuple[PartyShare, ...]
    modulus: int
    contribution_count: int
    absolute_bound: int
    input_transcript_hashes: tuple[str, ...]
    transcript_hash: str


@dataclass(frozen=True, slots=True)
class MPCSumResult:
    value: int
    participant_order: tuple[str, ...]
    aggregate_shares: tuple[PartyShare, ...]
    contribution_count: int
    transcript_hash: str
    algorithm_code: str = ALGORITHM_CODE
    capability_label: str = CAPABILITY_LABEL
    capability_status: str = CAPABILITY_STATUS


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_participants(participant_ids: Sequence[str]) -> tuple[str, ...]:
    if isinstance(participant_ids, (str, bytes)):
        raise MPCValidationError("participant_ids must be a sequence of identifiers")
    normalized: list[str] = []
    for participant_id in participant_ids:
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise MPCValidationError("participant identifiers must be non-empty strings")
        value = participant_id.strip()
        if len(value) > 160:
            raise MPCValidationError("participant identifier exceeds 160 characters")
        normalized.append(value)
    if len(normalized) < 2:
        raise MPCValidationError("additive sharing requires at least two participants")
    if len(set(normalized)) != len(normalized):
        raise MPCValidationError("participant identifiers must be unique")
    return tuple(sorted(normalized))


def _validate_integer(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MPCValidationError(f"{field} must be an integer")
    return value


def _validate_share_vector(
    shares: Sequence[PartyShare],
    participant_order: tuple[str, ...],
    modulus: int,
) -> None:
    if len(shares) != len(participant_order):
        raise MPCValidationError("share vector length does not match participant order")
    for index, (share, expected_id) in enumerate(zip(shares, participant_order, strict=True)):
        if not isinstance(share, PartyShare):
            raise MPCValidationError(f"share[{index}] must be a PartyShare")
        if share.participant_id != expected_id:
            raise MPCValidationError("share vector does not follow the fixed participant order")
        value = _validate_integer(share.value, field=f"share[{index}].value")
        if value < 0 or value >= modulus:
            raise MPCValidationError("share value is outside the finite field")


def _shared_secret_transcript(shared: SharedSecret) -> str:
    return _hash(
        {
            "absolute_bound": shared.absolute_bound,
            "algorithm": ALGORITHM_CODE,
            "modulus": shared.modulus,
            "owner_id": shared.owner_id,
            "participant_order": shared.participant_order,
            "shares": [
                {"participant_id": share.participant_id, "value": share.value}
                for share in shared.shares
            ],
        }
    )


def _aggregate_transcript(aggregate: AggregateShares) -> str:
    return _hash(
        {
            "absolute_bound": aggregate.absolute_bound,
            "algorithm": ALGORITHM_CODE,
            "contribution_count": aggregate.contribution_count,
            "input_transcript_hashes": aggregate.input_transcript_hashes,
            "modulus": aggregate.modulus,
            "participant_order": aggregate.participant_order,
            "aggregate_shares": [
                {"participant_id": share.participant_id, "value": share.value}
                for share in aggregate.shares
            ],
        }
    )


class AdditiveSecretSharingMPC:
    """A real additive-sharing sum protocol constrained to one local host.

    This implementation performs actual finite-field secret sharing and share
    aggregation. It is *not* a production cross-domain MPC deployment: every
    share currently exists in one Python process, with no authenticated
    transport, independently operated node, malicious-party protection, or
    threshold recovery. The precise status is therefore
    ``LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST``.
    """

    modulus = FIELD_MODULUS
    algorithm_code = ALGORITHM_CODE
    capability_label = CAPABILITY_LABEL
    capability_status = CAPABILITY_STATUS

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "algorithm_code": cls.algorithm_code,
            "capability_label": cls.capability_label,
            "capability_status": cls.capability_status,
            "implemented_operations": ["INTEGER_SUM"],
            "field_modulus": cls.modulus,
            "cross_domain_production_privacy": False,
            "independent_nodes": False,
            "limitations": [
                "all shares coexist in one host process",
                "no authenticated inter-party transport",
                "no malicious-party or collusion resistance",
                "no threshold recovery or distributed key management",
                "integer inputs only; fixed-point scaling is caller-owned",
            ],
        }

    @classmethod
    def share(
        cls,
        value: int,
        participant_ids: Sequence[str],
        *,
        owner_id: str,
        max_abs_input: int = 10**18,
        random_source: RandomSource | None = None,
        allow_insecure_deterministic_for_tests: bool = False,
    ) -> SharedSecret:
        value = _validate_integer(value, field="value")
        max_abs_input = _validate_integer(max_abs_input, field="max_abs_input")
        if max_abs_input < 0 or max_abs_input >= cls.modulus // 2:
            raise MPCValidationError("max_abs_input is outside the safe signed field range")
        if abs(value) > max_abs_input:
            raise MPCValidationError("value exceeds max_abs_input")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise MPCValidationError("owner_id must be a non-empty string")
        participant_order = _normalize_participants(participant_ids)

        if random_source is not None and not allow_insecure_deterministic_for_tests:
            raise MPCValidationError(
                "an injected random source is allowed only with the explicit test-only flag"
            )
        rng: RandomSource = random_source or secrets.SystemRandom()
        encoded_value = value % cls.modulus
        share_values = [rng.randrange(cls.modulus) for _ in participant_order[:-1]]
        if any(isinstance(item, bool) or not isinstance(item, int) for item in share_values):
            raise MPCValidationError("random source returned a non-integer share")
        if any(item < 0 or item >= cls.modulus for item in share_values):
            raise MPCValidationError("random source returned a value outside the finite field")
        share_values.append((encoded_value - sum(share_values)) % cls.modulus)
        shares = tuple(
            PartyShare(participant_id=participant_id, value=share_value)
            for participant_id, share_value in zip(
                participant_order, share_values, strict=True
            )
        )
        _validate_share_vector(shares, participant_order, cls.modulus)
        shared = SharedSecret(
            owner_id=owner_id.strip(),
            participant_order=participant_order,
            shares=shares,
            modulus=cls.modulus,
            absolute_bound=abs(value),
            transcript_hash="",
        )
        return SharedSecret(
            owner_id=shared.owner_id,
            participant_order=shared.participant_order,
            shares=shared.shares,
            modulus=shared.modulus,
            absolute_bound=shared.absolute_bound,
            transcript_hash=_shared_secret_transcript(shared),
        )

    @classmethod
    def aggregate(cls, shared_secrets: Sequence[SharedSecret]) -> AggregateShares:
        if not shared_secrets:
            raise MPCValidationError("at least one shared secret is required")
        first = shared_secrets[0]
        if not isinstance(first, SharedSecret):
            raise MPCValidationError("shared secret entries must be SharedSecret instances")
        participant_order = first.participant_order
        modulus = first.modulus
        if modulus != cls.modulus:
            raise MPCValidationError("shared secret uses an unsupported field modulus")

        owners: set[str] = set()
        aggregate_values = [0] * len(participant_order)
        absolute_bound = 0
        transcript_hashes: list[str] = []
        for shared in shared_secrets:
            if not isinstance(shared, SharedSecret):
                raise MPCValidationError("shared secret entries must be SharedSecret instances")
            if shared.modulus != modulus or shared.participant_order != participant_order:
                raise MPCValidationError("shared secrets use incompatible MPC sessions")
            if not isinstance(shared.owner_id, str) or not shared.owner_id.strip():
                raise MPCValidationError("shared secret owner_id must be non-empty")
            if shared.owner_id in owners:
                raise MPCValidationError("duplicate contribution owner")
            owners.add(shared.owner_id)
            _validate_share_vector(shared.shares, participant_order, modulus)
            if shared.transcript_hash != _shared_secret_transcript(shared):
                raise MPCValidationError("shared secret transcript hash mismatch")
            contribution_bound = _validate_integer(
                shared.absolute_bound, field="shared_secret.absolute_bound"
            )
            if contribution_bound < 0 or contribution_bound >= modulus // 2:
                raise MPCValidationError("shared secret bound is outside the safe signed field range")
            absolute_bound += contribution_bound
            if absolute_bound >= modulus // 2:
                raise MPCValidationError("aggregate bound could wrap the signed finite field")
            for index, share in enumerate(shared.shares):
                aggregate_values[index] = (aggregate_values[index] + share.value) % modulus
            transcript_hashes.append(shared.transcript_hash)

        aggregate_shares = tuple(
            PartyShare(participant_id=participant_id, value=value)
            for participant_id, value in zip(
                participant_order, aggregate_values, strict=True
            )
        )
        _validate_share_vector(aggregate_shares, participant_order, modulus)
        aggregate = AggregateShares(
            participant_order=participant_order,
            shares=aggregate_shares,
            modulus=modulus,
            contribution_count=len(shared_secrets),
            absolute_bound=absolute_bound,
            input_transcript_hashes=tuple(sorted(transcript_hashes)),
            transcript_hash="",
        )
        return AggregateShares(
            participant_order=aggregate.participant_order,
            shares=aggregate.shares,
            modulus=aggregate.modulus,
            contribution_count=aggregate.contribution_count,
            absolute_bound=aggregate.absolute_bound,
            input_transcript_hashes=aggregate.input_transcript_hashes,
            transcript_hash=_aggregate_transcript(aggregate),
        )

    @classmethod
    def reconstruct(cls, aggregate: AggregateShares) -> int:
        if not isinstance(aggregate, AggregateShares):
            raise MPCValidationError("aggregate must be an AggregateShares instance")
        if aggregate.modulus != cls.modulus:
            raise MPCValidationError("aggregate uses an unsupported field modulus")
        participant_order = _normalize_participants(aggregate.participant_order)
        if participant_order != aggregate.participant_order:
            raise MPCValidationError("aggregate participant order is not canonical")
        _validate_share_vector(aggregate.shares, participant_order, aggregate.modulus)
        encoded = sum(share.value for share in aggregate.shares) % aggregate.modulus
        decoded = encoded if encoded <= aggregate.modulus // 2 else encoded - aggregate.modulus
        absolute_bound = _validate_integer(aggregate.absolute_bound, field="absolute_bound")
        if absolute_bound < 0 or absolute_bound >= aggregate.modulus // 2:
            raise MPCValidationError("aggregate bound is outside the safe signed field range")
        if abs(decoded) > absolute_bound:
            raise MPCValidationError("reconstructed value violates the declared aggregate bound")
        contribution_count = _validate_integer(
            aggregate.contribution_count, field="contribution_count"
        )
        if contribution_count < 1 or contribution_count != len(aggregate.input_transcript_hashes):
            raise MPCValidationError("aggregate contribution count is inconsistent")
        if any(
            not isinstance(item, str)
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item.lower())
            for item in aggregate.input_transcript_hashes
        ):
            raise MPCValidationError("aggregate input transcript hash is invalid")
        if aggregate.transcript_hash != _aggregate_transcript(aggregate):
            raise MPCValidationError("aggregate transcript hash mismatch")
        return decoded

    @classmethod
    def sum(
        cls,
        values: Sequence[int],
        participant_ids: Sequence[str],
        *,
        max_abs_input: int = 10**18,
        random_source: RandomSource | None = None,
        allow_insecure_deterministic_for_tests: bool = False,
    ) -> MPCSumResult:
        if isinstance(values, (str, bytes)):
            raise MPCValidationError("values must be an integer sequence")
        if len(values) != len(participant_ids):
            raise MPCValidationError("values and participant_ids must have the same length")
        canonical_ids = _normalize_participants(participant_ids)
        contributions: dict[str, int] = {}
        for participant_id, value in zip(participant_ids, values, strict=True):
            normalized_id = participant_id.strip() if isinstance(participant_id, str) else ""
            contributions[normalized_id] = _validate_integer(value, field="value")

        shared = [
            cls.share(
                contributions[participant_id],
                canonical_ids,
                owner_id=participant_id,
                max_abs_input=max_abs_input,
                random_source=random_source,
                allow_insecure_deterministic_for_tests=allow_insecure_deterministic_for_tests,
            )
            for participant_id in canonical_ids
        ]
        aggregate = cls.aggregate(shared)
        value = cls.reconstruct(aggregate)
        return MPCSumResult(
            value=value,
            participant_order=aggregate.participant_order,
            aggregate_shares=aggregate.shares,
            contribution_count=aggregate.contribution_count,
            transcript_hash=aggregate.transcript_hash,
        )
