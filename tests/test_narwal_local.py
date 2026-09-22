"""Offline protocol regression tests for the Narwal local controller."""

import struct

import pytest

from narwal_local import (
    CommandResponse,
    Fixed32,
    NarwalProtocolError,
    build_frame,
    build_room_clean_payload,
    decode_protobuf,
    parse_frame,
    parse_map_response,
    parse_status_response,
    parse_working_status_payload,
)


def test_frame_round_trip_uses_required_header_length():
    frame = build_frame("/QoEsI5qYXO/device/common/yell", b"\x08\x01")

    parsed = parse_frame(frame)

    assert frame[1] == len(parsed.topic.encode()) + 2
    assert parsed.topic == "/QoEsI5qYXO/device/common/yell"
    assert parsed.payload == b"\x08\x01"
    assert parsed.field_tag == 0x22


def test_frame_rejects_header_length_mismatch():
    frame = bytearray(build_frame("/x", b""))
    frame[1] = 99

    with pytest.raises(NarwalProtocolError, match="header byte"):
        parse_frame(bytes(frame))


def test_schema_less_protobuf_keeps_binary_fields_as_bytes():
    fields = decode_protobuf(b"\x08\x96\x01\x12\x03abc\x1d" + struct.pack("<f", 42.5))

    assert fields[1] == [150]
    assert fields[2] == [b"abc"]
    assert isinstance(fields[3][0], Fixed32)
    assert fields[3][0].as_float == pytest.approx(42.5)


def test_clean_task_preserves_room_order_and_settings():
    payload = build_room_clean_payload(
        9, [42, 7], mode="vacuum-and-mop", fan="strong", water="wet",
        mop_strength="high", passes=2, route="meticulous",
    )

    outer = decode_protobuf(payload)
    task = decode_protobuf(outer[1][0])
    first_item, second_item = (decode_protobuf(item) for item in task[2])
    first_zone = decode_protobuf(first_item[1][0])
    first_parameters = decode_protobuf(first_item[2][0])
    second_zone = decode_protobuf(second_item[1][0])

    assert task[1] == [9]
    assert task[5] == [4]
    assert first_zone[2] == [42]
    assert second_zone[2] == [7]
    assert first_item[3] == [1]
    assert second_item[3] == [2]
    assert first_parameters[1] == [4]
    assert first_parameters[2] == [3]
    assert first_parameters[3] == [2]
    assert first_parameters[4] == [3]
    assert first_parameters[7] == [2]
    assert first_parameters[8] == [2]


def test_map_and_status_parse_only_documented_fields():
    room = b"\x08\x07\x10\x03\x1a\x07Kitchen"
    map_payload = b"\x08\x09" + b"\x62" + bytes((len(room),)) + room
    map_response = CommandResponse(None, {2: [map_payload]}, map_payload)
    parsed_map = parse_map_response(map_response)

    task_status = b"\x08\x0a\x18\x01"  # docked; explicit dock presence
    status_payload = (
        b"\x15" + struct.pack("<f", 87.5)
        + b"\x1a" + bytes((len(task_status),)) + task_status
        + b"\xf8\x02\x01"
    )
    status_response = CommandResponse(None, {2: [status_payload]}, status_payload)
    parsed_status = parse_status_response(status_response)

    assert parsed_map.map_id == 9
    assert parsed_map.rooms[0].as_dict() == {"id": 7, "type": 3, "name": "Kitchen"}
    assert parsed_status["state"] == "docked"
    assert parsed_status["docked"] is True
    assert parsed_status["battery_percent"] == pytest.approx(87.5)
    assert parsed_status["charging_status"] == 1


def test_working_status_reports_live_clean_metrics_without_guessing_the_schema():
    payload = (
        b"\x0d" + struct.pack("<f", 54.0)
        + b"\x15" + struct.pack("<f", 8.28)
        + b"\x18\xee\x02"  # 366 elapsed seconds
        + b"\x30\x05"       # current room ID 5
    )

    parsed = parse_working_status_payload(payload)

    assert parsed == {
        "progress_percent": 54.0,
        "covered_area_m2": pytest.approx(8.28),
        "elapsed_seconds": 366,
        "current_room_id": 5,
    }
