from app.services.privacy_protocols import private_set_intersection, secure_federated_average


def test_private_set_intersection_returns_only_count_and_commitments():
    result = private_set_intersection(
        ["meter-a", "meter-b", "meter-c"],
        ["meter-b", "meter-c", "meter-d"],
    )

    assert result["intersection_count"] == 2
    assert result["raw_identifiers_exposed"] is False
    assert "meter-b" not in repr(result)


def test_federated_average_uses_secret_sharing_transcripts():
    result = secure_federated_average(
        [[1.0, 2.0], [3.0, 4.0]],
        ["node-a", "node-b"],
    )

    assert result["aggregated_update"] == [2.0, 3.0]
    assert result["raw_updates_exposed"] is False
    assert len(result["coordinate_transcript_hashes"]) == 2
