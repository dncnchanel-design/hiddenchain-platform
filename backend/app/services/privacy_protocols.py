from __future__ import annotations

import hashlib
import secrets
from typing import Sequence

from .mpc import AdditiveSecretSharingMPC


# A fixed prime-sized group keeps the local protocol dependency-free. The
# protocol remains a single-host experimental implementation until each party
# owns an authenticated transport and independent key material.
PSI_GROUP_MODULUS = (2**521) - 1


def _hash_to_group(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return 2 + int.from_bytes(digest, "big") % (PSI_GROUP_MODULUS - 3)


def _normalize_set(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("PSI input must be a sequence of identifiers")
    normalized = sorted({item.strip() for item in values if isinstance(item, str) and item.strip()})
    if not normalized:
        raise ValueError("PSI input must contain at least one identifier")
    return normalized


def private_set_intersection(left: Sequence[str], right: Sequence[str]) -> dict[str, object]:
    """Run a commutative-exponent PSI transcript without exposing raw IDs.

    Each side blinds the same group hash with a private exponent. The
    coordinator compares only re-blinded group elements. This is a
    semi-honest, single-process protocol and is deliberately not labelled as
    a malicious-party-resistant production MPC deployment.
    """

    left_values = _normalize_set(left)
    right_values = _normalize_set(right)
    left_exponent = secrets.randbelow(PSI_GROUP_MODULUS - 2) + 1
    right_exponent = secrets.randbelow(PSI_GROUP_MODULUS - 2) + 1
    left_blinded = [pow(_hash_to_group(item), left_exponent, PSI_GROUP_MODULUS) for item in left_values]
    right_blinded = [pow(_hash_to_group(item), right_exponent, PSI_GROUP_MODULUS) for item in right_values]
    left_reblinded = {pow(item, right_exponent, PSI_GROUP_MODULUS) for item in left_blinded}
    right_reblinded = {pow(item, left_exponent, PSI_GROUP_MODULUS) for item in right_blinded}
    matched_tokens = sorted(left_reblinded & right_reblinded)
    transcript = {
        "protocol": "COMMUTATIVE_DH_PSI_V1",
        "left_count": len(left_values),
        "right_count": len(right_values),
        "matched_token_hashes": [hashlib.sha256(str(item).encode()).hexdigest() for item in matched_tokens],
    }
    return {
        **transcript,
        "intersection_count": len(matched_tokens),
        "transcript_hash": hashlib.sha256(repr(sorted(transcript.items())).encode()).hexdigest(),
        "raw_identifiers_exposed": False,
        "capability_status": "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST",
    }


def secure_federated_average(
    updates: Sequence[Sequence[float]], participant_ids: Sequence[str], *, scale: int = 1000
) -> dict[str, object]:
    if not updates or len(updates) != len(participant_ids):
        raise ValueError("federated updates and participant IDs must be non-empty and aligned")
    width = len(updates[0])
    if width == 0 or any(len(update) != width for update in updates):
        raise ValueError("federated updates must have the same non-zero width")
    aggregate: list[int] = []
    transcripts: list[str] = []
    for index in range(width):
        integer_updates = [round(float(update[index]) * scale) for update in updates]
        result = AdditiveSecretSharingMPC.sum(integer_updates, participant_ids, max_abs_input=10**12)
        aggregate.append(result.value)
        transcripts.append(result.transcript_hash)
    averaged = [round(value / scale / len(updates), 6) for value in aggregate]
    return {
        "protocol": "FEDERATED_AVERAGING_SECURE_AGGREGATION_V1",
        "aggregated_update": averaged,
        "contribution_count": len(updates),
        "coordinate_transcript_hashes": transcripts,
        "raw_updates_exposed": False,
        "capability_status": "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST",
    }
