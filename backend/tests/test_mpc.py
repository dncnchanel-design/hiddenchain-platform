from __future__ import annotations

import random

import pytest

from app.services.mpc import (
    CAPABILITY_STATUS,
    FIELD_MODULUS,
    AdditiveSecretSharingMPC,
    MPCValidationError,
    PartyShare,
    SharedSecret,
)


def test_additive_secret_sharing_reconstructs_signed_sum_in_fixed_order():
    result = AdditiveSecretSharingMPC.sum(
        [7, 10, -3],
        ["participant-c", "participant-a", "participant-b"],
        random_source=random.Random(20260820),
        allow_insecure_deterministic_for_tests=True,
    )

    assert result.value == 14
    assert result.participant_order == (
        "participant-a",
        "participant-b",
        "participant-c",
    )
    assert result.contribution_count == 3
    assert result.capability_status == "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST"
    assert result.capability_status == CAPABILITY_STATUS


def test_test_only_rng_is_reproducible_after_canonical_participant_sorting():
    first = AdditiveSecretSharingMPC.sum(
        [5, 11, -2],
        ["z", "a", "m"],
        random_source=random.Random(7),
        allow_insecure_deterministic_for_tests=True,
    )
    second = AdditiveSecretSharingMPC.sum(
        [-2, 5, 11],
        ["m", "z", "a"],
        random_source=random.Random(7),
        allow_insecure_deterministic_for_tests=True,
    )

    assert first.value == second.value == 14
    assert first.aggregate_shares == second.aggregate_shares
    assert first.transcript_hash == second.transcript_hash


def test_share_aggregate_and_reconstruct_protocol_steps():
    participants = ["node-b", "node-a", "node-c"]
    rng = random.Random(42)
    shared = [
        AdditiveSecretSharingMPC.share(
            value,
            participants,
            owner_id=owner,
            random_source=rng,
            allow_insecure_deterministic_for_tests=True,
        )
        for owner, value in (("owner-1", 120), ("owner-2", -35), ("owner-3", 4))
    ]
    aggregate = AdditiveSecretSharingMPC.aggregate(shared)

    assert AdditiveSecretSharingMPC.reconstruct(aggregate) == 89
    assert [share.participant_id for share in aggregate.shares] == [
        "node-a",
        "node-b",
        "node-c",
    ]


@pytest.mark.parametrize(
    ("values", "participants", "message"),
    [
        ([1], ["only-one"], "at least two"),
        ([1, 2], ["duplicate", "duplicate"], "unique"),
        ([1], ["a", "b"], "same length"),
        ([True, 2], ["a", "b"], "integer"),
        ([10**18 + 1, 0], ["a", "b"], "max_abs_input"),
    ],
)
def test_invalid_mpc_inputs_are_rejected(values, participants, message):
    with pytest.raises(MPCValidationError, match=message):
        AdditiveSecretSharingMPC.sum(values, participants)


def test_injected_reproducible_rng_requires_explicit_test_only_flag():
    with pytest.raises(MPCValidationError, match="test-only"):
        AdditiveSecretSharingMPC.sum(
            [1, 2],
            ["a", "b"],
            random_source=random.Random(1),
        )


def test_malformed_or_out_of_field_shares_are_rejected():
    malformed = SharedSecret(
        owner_id="owner",
        participant_order=("a", "b"),
        shares=(PartyShare("a", 1), PartyShare("b", FIELD_MODULUS)),
        modulus=FIELD_MODULUS,
        absolute_bound=1,
        transcript_hash="0" * 64,
    )

    with pytest.raises(MPCValidationError, match="outside the finite field"):
        AdditiveSecretSharingMPC.aggregate([malformed])


def test_tampered_shared_secret_transcript_is_rejected():
    valid = AdditiveSecretSharingMPC.share(
        3,
        ["a", "b"],
        owner_id="owner",
        random_source=random.Random(3),
        allow_insecure_deterministic_for_tests=True,
    )
    tampered = SharedSecret(
        owner_id=valid.owner_id,
        participant_order=valid.participant_order,
        shares=valid.shares,
        modulus=valid.modulus,
        absolute_bound=valid.absolute_bound,
        transcript_hash="0" * 64,
    )

    with pytest.raises(MPCValidationError, match="transcript hash mismatch"):
        AdditiveSecretSharingMPC.aggregate([tampered])


def test_status_does_not_claim_cross_domain_production_privacy():
    status = AdditiveSecretSharingMPC.status()

    assert status["capability_label"] == "LOCAL_REAL"
    assert status["capability_status"] == "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST"
    assert status["cross_domain_production_privacy"] is False
    assert status["independent_nodes"] is False
