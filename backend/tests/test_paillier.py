from app.services.paillier import PaillierError, encrypted_sum, encrypted_vector_sum, generate_keypair


def test_paillier_ciphertext_addition_reconstructs_signed_sum():
    keypair = generate_keypair(512)
    ciphertexts = [keypair.public.encrypt(value) for value in (125, -40, 7)]
    aggregate = keypair.public.add(*ciphertexts)

    assert keypair.private.decrypt(aggregate) == 92
    assert keypair.public.fingerprint


def test_paillier_vector_receipt_excludes_plaintext_values():
    receipt = encrypted_vector_sum(
        [[1.25, 2.5], [3.75, -1.5]],
        ["provider-a", "provider-b"],
    )

    assert receipt["values"] == [5.0, 1.0]
    assert receipt["raw_values_exposed"] is False
    assert receipt["ciphertext_count"] == 4
    assert "ciphertexts" not in receipt


def test_paillier_rejects_unsafe_key_size():
    try:
        generate_keypair(256)
    except PaillierError as exc:
        assert "at least 512" in str(exc)
    else:
        raise AssertionError("small Paillier keys must be rejected")


def test_encrypted_sum_records_only_ciphertext_commitments():
    receipt = encrypted_sum([10, 20], ["a", "b"])

    assert receipt["value"] == 30
    assert receipt["raw_values_exposed"] is False
    assert len(receipt["ciphertext_hashes"]) == 2
