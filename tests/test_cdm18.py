from ca3.cdm18 import datum_type, event_references, uuid_value


def test_datum_type() -> None:
    record = {"datum": {"com.example.Event": {"uuid": "E"}}}
    assert datum_type(record) == ("Event", {"uuid": "E"})


def test_uuid_union() -> None:
    assert uuid_value({"com.example.UUID": "ABC"}) == "ABC"
    assert uuid_value(None) is None


def test_event_references() -> None:
    body = {
        "hostId": "H",
        "subject": {"com.example.UUID": "S"},
        "predicateObject": {"com.example.UUID": "O"},
        "predicateObject2": None,
    }
    assert list(event_references(body)) == ["H", "S", "O"]
