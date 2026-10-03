from solar_server.store import _state_data, _state_document


def test_firestore_state_round_trips_nested_arrays():
    plan = {
        "generated_at": 1791060000,
        "windows": [[1791063600, 1791067200]],
        "forecast": [[1791060000, 215.4], [1791060300, 210.1]],
    }

    document = _state_document(plan)

    assert list(document) == ["data_json"]
    assert _state_data(document) == plan


def test_firestore_state_reads_legacy_documents():
    document = {"generated_at": 1791060000, "windows": []}

    assert _state_data(document) == document
