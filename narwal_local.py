"""Local LAN controller for Narwal Flow / AX12 robot vacuums.

The controller talks only to ``ws://<robot-ip>:9002``.  It does not require a
Narwal account, cloud token, or a pairing key, but it does require that the
robot has already joined the home Wi-Fi network.

This is a deliberately small, standalone client.  It implements the verified
Narwal WebSocket envelope and only the protobuf fields needed for identity,
status, room discovery, and cleaning.  All mutating CLI commands require
``--yes`` so that a copied command cannot start a robot unexpectedly.

Protocol behaviour was independently implemented from the public, MIT-licensed
reverse-engineering notes in sjmotew/NarwalIntegration.  No Narwal app code is
included here.  See Kingdom_of_Claudes_Beloved_MDs/NARWAL_LOCAL.md.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PORT = 9002
FLOW_PRODUCT_KEY = "QoEsI5qYXO"

# Used only while bootstrapping identity.  Once the robot responds, the client
# locks onto the product key returned by common/get_device_info.
KNOWN_PRODUCT_KEYS = (
    FLOW_PRODUCT_KEY,
    "QxMSPG6VSO",  # Flow 2
    "iSuVlI1If2",  # Flow 2 alternate identity
    "mkbqaprvrb",  # Flow 2 alternate identity
    "DrzDKQ0MU8",  # Freo Z10 Ultra
    "qV6BujoYLz",  # Freo Z10 Pro / Turbo
    "hEA7OEshlx",  # Freo Z Ultra
    "fjhpiem4ba",  # Freo 20
    "BYWBPqSxeC",  # CX7 alternate identity
    "CGjuB6dzq7",  # Narwal JX
    # Kept for discovery coverage.  Some are cloud-only or APK-derived, but
    # probing get_device_info is harmless and identifies an unfamiliar model.
    "LnugwMG9ss",  # AX18 / Freo X Ultra (cloud-only on known variants)
    "5OMbqk58Sc",  # AX19 / Freo X Ultra
    "tPQJmoIbEC",  # AX6
    "HgArZ7KuJL",  # AX7
    "Uuug39n0fD",  # AX8
    "CNbforyZWI",  # AX15 / Freo X10 Pro
    "E9Q8aDzUbp",  # AX17
    "jI5rHi4mKa",  # AX24
    "UuTSLsMce4",  # AX25
    "88OLXLpkjT",  # BX4
    "3rIGshGNAj",  # BX4 / Y1 alternate identity
    "7sSZZ4XfTI",  # CX2
    "OlkUn3oUCu",  # CX3 / CX3Pure
    "mvlduyye85",  # X30
    "pcbfh2ldvx",  # X31
    "EHf6cRNRGT",  # J4 / J4Pure
    "6NjIDYxBXb",  # J4Lite
    "cUlfJN5JYP",  # unknown APK identity
)

STATE_NAMES = {
    1: "standby",
    2: "docked_v2",
    3: "cleaning_v2",
    4: "cleaning",
    5: "cleaning_or_stuck",
    7: "remapping",
    10: "docked",
    14: "charged",
    17: "custom_cleaning",
    19: "task_completed_returning",
}
DOCKED_STATES = frozenset((2, 10, 14))

WORK_MODES: dict[str, tuple[int, int, tuple[int, ...]]] = {
    # CLI name: (CleanTask.taskType, CleanParam.mode, pass-count field numbers)
    "vacuum": (1, 2, (5,)),
    "mop": (2, 3, (6,)),
    "vacuum-then-mop": (3, 5, (5, 6)),
    "vacuum-and-mop": (4, 4, (7,)),
}
FAN_LEVELS = {"mute": 1, "normal": 2, "strong": 3, "deep": 4, "super": 5}
WATER_LEVELS = {"dry": 1, "normal": 2, "wet": 3}
MOP_STRENGTHS = {"normal": 1, "high": 2}
ROUTES = {"standard": 1, "meticulous": 2}

MUTATING_COMMANDS = frozenset(
    (
        "locate",
        "pause",
        "resume",
        "stop",
        "cancel",
        "home",
        "quick-clean",
        "clean-all",
        "clean-rooms",
        "wash-mops",
        "dry-mops",
        "empty-bin",
        "set-fan",
        "set-water",
    )
)

LOG = logging.getLogger(__name__)


class NarwalError(RuntimeError):
    """Base error for local Narwal control failures."""


class NarwalConnectionError(NarwalError):
    """The robot's local WebSocket could not be reached."""


class NarwalProtocolError(NarwalError):
    """A received frame or protobuf message was malformed."""


class NarwalCommandError(NarwalError):
    """The robot did not accept a command or did not answer it."""


@dataclass(frozen=True)
class NarwalFrame:
    """One parsed Narwal binary WebSocket frame."""

    topic: str
    payload: bytes
    field_tag: int
    raw: bytes

    @property
    def short_topic(self) -> str:
        """Return the topic after ``/<product>/<device>/`` when present."""
        parts = self.topic.split("/")
        return "/".join(parts[3:]) if len(parts) >= 4 else self.topic


@dataclass(frozen=True)
class Fixed32:
    """A protobuf fixed32 value, retained because its schema is unknown."""

    raw: bytes

    @property
    def as_float(self) -> float:
        return struct.unpack("<f", self.raw)[0]


@dataclass(frozen=True)
class CommandResponse:
    """One field-5 command response from the robot."""

    result_code: int | None
    fields: dict[int, list[Any]]
    raw_payload: bytes

    @property
    def accepted(self) -> bool:
        # Queries return data in field 1 rather than a numeric result code.
        return self.result_code is None or self.result_code in (1, 6)

    def summary(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "result_code": self.result_code}


@dataclass(frozen=True)
class DeviceInfo:
    product_key: str
    device_id: str
    firmware: str

    def as_dict(self) -> dict[str, str]:
        return {
            "product_key": self.product_key,
            "device_id": self.device_id,
            "firmware": self.firmware,
        }


@dataclass(frozen=True)
class Room:
    """A cleanable map room as exposed by map/get_map."""

    room_id: int
    room_type: int | None
    name: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.room_id, "type": self.room_type, "name": self.name}


@dataclass(frozen=True)
class MapInfo:
    map_id: int
    rooms: tuple[Room, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"map_id": self.map_id, "rooms": [room.as_dict() for room in self.rooms]}


def _encode_varint(value: int) -> bytes:
    """Encode a non-negative protobuf varint."""
    if value < 0:
        raise ValueError("this controller only emits non-negative protobuf integers")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _encode_varint_field(field_number: int, value: int) -> bytes:
    return _encode_varint(field_number << 3) + _encode_varint(value)


def _encode_bytes_field(field_number: int, value: bytes) -> bytes:
    return _encode_varint((field_number << 3) | 2) + _encode_varint(len(value)) + value


def _encode_string_field(field_number: int, value: str) -> bytes:
    return _encode_bytes_field(field_number, value.encode("utf-8"))


def build_frame(topic: str, payload: bytes = b"") -> bytes:
    """Build a Narwal field-4 request frame.

    The second byte must be exactly ``len(topic UTF-8 bytes) + 2``.  A mismatch
    causes the robot to drop the socket without a protocol-level error.
    """
    topic_bytes = topic.encode("utf-8")
    if len(topic_bytes) > 253:
        raise ValueError("Narwal topic is too long for its one-byte frame header")
    return bytes((1, len(topic_bytes) + 2, 0x22, len(topic_bytes))) + topic_bytes + payload


def parse_frame(data: bytes) -> NarwalFrame:
    """Parse a field-4 request/broadcast or field-5 response frame."""
    if len(data) < 4:
        raise NarwalProtocolError(f"frame is {len(data)} bytes; expected at least 4")
    if data[0] != 1:
        raise NarwalProtocolError(f"unexpected frame type 0x{data[0]:02x}")
    if data[2] not in (0x22, 0x2A):
        raise NarwalProtocolError(f"unexpected protobuf field tag 0x{data[2]:02x}")
    topic_len = data[3]
    if len(data) < 4 + topic_len:
        raise NarwalProtocolError("frame ended inside its topic")
    if data[1] != topic_len + 2:
        raise NarwalProtocolError("frame header byte does not match topic length")
    try:
        topic = data[4 : 4 + topic_len].decode("utf-8")
    except UnicodeDecodeError as error:
        raise NarwalProtocolError("topic is not UTF-8") from error
    return NarwalFrame(topic, data[4 + topic_len :], data[2], data)


def _decode_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(data):
            raise NarwalProtocolError("protobuf ended inside a varint")
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
    raise NarwalProtocolError("protobuf varint is longer than 10 bytes")


def decode_protobuf(data: bytes) -> dict[int, list[Any]]:
    """Decode enough schema-less protobuf to inspect the verified fields.

    Length-delimited values intentionally remain bytes.  Without an official
    schema they could be a string, a nested message, compressed map bytes, or
    arbitrary binary data; callers opt into nested parsing only where the
    protocol has been established.
    """
    fields: dict[int, list[Any]] = {}
    position = 0
    while position < len(data):
        tag, position = _decode_varint(data, position)
        field_number, wire_type = tag >> 3, tag & 0x07
        if not field_number:
            raise NarwalProtocolError("protobuf field number 0 is invalid")
        if wire_type == 0:
            value, position = _decode_varint(data, position)
        elif wire_type == 1:
            if position + 8 > len(data):
                raise NarwalProtocolError("protobuf ended inside a fixed64 field")
            value = data[position : position + 8]
            position += 8
        elif wire_type == 2:
            length, position = _decode_varint(data, position)
            if position + length > len(data):
                raise NarwalProtocolError("protobuf ended inside a length-delimited field")
            value = data[position : position + length]
            position += length
        elif wire_type == 5:
            if position + 4 > len(data):
                raise NarwalProtocolError("protobuf ended inside a fixed32 field")
            value = Fixed32(data[position : position + 4])
            position += 4
        else:
            raise NarwalProtocolError(f"unsupported protobuf wire type {wire_type}")
        fields.setdefault(field_number, []).append(value)
    return fields


def _first(fields: dict[int, list[Any]], field_number: int) -> Any | None:
    values = fields.get(field_number, ())
    return values[0] if values else None


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return "" if value is None else str(value).strip()


def _as_int(value: Any) -> int | None:
    # bool is an int in Python, but neither a useful ID nor a status code here.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _url_host(host: str) -> str:
    """Bracket an IPv6 literal while leaving a hostname/IPv4 untouched."""
    try:
        return f"[{host}]" if ipaddress.ip_address(host).version == 6 else host
    except ValueError:
        return host


def build_topic_subscription(duration: int = 600) -> bytes:
    """Build ``common/active_robot_publish`` for the known state topics."""
    topics = (
        "status/robot_base_status",
        "status/working_status",
        "upgrade/upgrade_status",
        "status/download_status",
        "map/display_map",
        "status/time_line_status",
    )
    payload = bytearray()
    for topic in topics:
        entry = _encode_string_field(1, topic) + _encode_varint_field(2, duration)
        payload.extend(_encode_bytes_field(1, entry))
    return bytes(payload)


def build_room_clean_payload(
    map_id: int,
    room_ids: Iterable[int],
    *,
    mode: str = "vacuum-and-mop",
    fan: str = "normal",
    water: str = "normal",
    mop_strength: str = "normal",
    passes: int = 1,
    route: str | None = None,
) -> bytes:
    """Build the verified ``clean/start_clean`` StartClean/CleanTask payload."""
    ordered_room_ids = tuple(room_ids)
    if map_id <= 0:
        raise ValueError("map_id must be a positive value returned by the robot")
    if not ordered_room_ids or any(room_id <= 0 for room_id in ordered_room_ids):
        raise ValueError("at least one positive room ID is required")
    if passes < 1 or passes > 3:
        raise ValueError("passes must be between 1 and 3")
    try:
        task_type, param_mode, pass_fields = WORK_MODES[mode]
        fan_value = FAN_LEVELS[fan]
        water_value = WATER_LEVELS[water]
        strength_value = MOP_STRENGTHS[mop_strength]
        route_value = ROUTES[route] if route else None
    except KeyError as error:
        raise ValueError(f"unsupported cleaning setting: {error.args[0]}") from error

    task = bytearray(_encode_varint_field(1, map_id))
    for order, room_id in enumerate(ordered_room_ids, start=1):
        zone = _encode_varint_field(1, 1) + _encode_varint_field(2, room_id)
        parameters = bytearray(
            _encode_varint_field(1, param_mode)
            + _encode_varint_field(2, fan_value)
            + _encode_varint_field(3, strength_value)
            + _encode_varint_field(4, water_value)
        )
        for field_number in pass_fields:
            parameters.extend(_encode_varint_field(field_number, passes))
        if route_value is not None:
            parameters.extend(_encode_varint_field(8, route_value))
        item = (
            _encode_bytes_field(1, zone)
            + _encode_bytes_field(2, bytes(parameters))
            + _encode_varint_field(3, order)
        )
        task.extend(_encode_bytes_field(2, item))
    task.extend(_encode_bytes_field(3, b""))
    task.extend(_encode_varint_field(5, task_type))
    return _encode_bytes_field(1, bytes(task))


def parse_map_response(response: CommandResponse) -> MapInfo:
    """Extract the active map ID and cleanable room records from map/get_map."""
    if not response.accepted:
        raise NarwalCommandError(f"map/get_map failed (result code {response.result_code})")
    raw_map = _first(response.fields, 2)
    if not isinstance(raw_map, bytes):
        raise NarwalProtocolError("map/get_map response did not contain field 2 map data")
    map_fields = decode_protobuf(raw_map)
    map_id = _as_int(_first(map_fields, 1))
    if not map_id:
        raise NarwalProtocolError("map/get_map response did not contain an active map ID")
    rooms: list[Room] = []
    for raw_room in map_fields.get(12, ()):
        if not isinstance(raw_room, bytes):
            continue
        room_fields = decode_protobuf(raw_room)
        room_id = _as_int(_first(room_fields, 1))
        if not room_id:
            continue
        room_type = _as_int(_first(room_fields, 2))
        raw_name = _first(room_fields, 3)
        name = _as_text(raw_name) if isinstance(raw_name, bytes) else None
        rooms.append(Room(room_id, room_type, name or None))
    return MapInfo(map_id, tuple(rooms))


def parse_status_response(response: CommandResponse) -> dict[str, Any]:
    """Return the conservative, documented subset of robot_base_status."""
    if not response.accepted:
        raise NarwalCommandError(
            f"status/get_device_base_status failed (result code {response.result_code})"
        )
    raw_status = _first(response.fields, 2)
    if not isinstance(raw_status, bytes):
        return {"available": True, "state": None, "battery_percent": None, "docked": None}
    fields = decode_protobuf(raw_status)
    working_status: int | None = None
    nested_task = _first(fields, 3)
    if isinstance(nested_task, bytes):
        working_status = _as_int(_first(decode_protobuf(nested_task), 1))
    battery = _first(fields, 2)
    battery_percent = round(battery.as_float, 1) if isinstance(battery, Fixed32) else None
    task_fields = decode_protobuf(nested_task) if isinstance(nested_task, bytes) else {}
    presence = _as_int(_first(task_fields, 3))
    explicit_docked: bool | None
    if presence in (1, 6):
        explicit_docked = True
    elif presence == 2:
        explicit_docked = False
    elif working_status in DOCKED_STATES:
        explicit_docked = True
    elif working_status in (3, 4, 5, 7, 17, 19):
        explicit_docked = False
    else:
        explicit_docked = None
    errors = [value for value in fields.get(1, ()) if isinstance(value, int)]
    return {
        "available": True,
        "state": STATE_NAMES.get(working_status, "unknown" if working_status else None),
        "state_code": working_status,
        "battery_percent": battery_percent,
        "docked": explicit_docked,
        "error_codes": errors,
        "charging_status": _as_int(_first(fields, 47)),
    }


def parse_working_status_payload(payload: bytes) -> dict[str, Any]:
    """Extract the documented live metrics from a working_status broadcast."""
    fields = decode_protobuf(payload)
    progress = _first(fields, 1)
    covered_area = _first(fields, 2)
    raw_progress = progress.as_float if isinstance(progress, Fixed32) else None
    # Some firmware reports workingProgress as 0..1 and others as 0..100.
    progress_percent = (
        round(raw_progress * 100 if raw_progress is not None and raw_progress <= 1 else raw_progress, 1)
        if raw_progress is not None
        else None
    )
    return {
        "progress_percent": progress_percent,
        "covered_area_m2": round(covered_area.as_float, 2) if isinstance(covered_area, Fixed32) else None,
        "elapsed_seconds": _as_int(_first(fields, 3)),
        "current_room_id": _as_int(_first(fields, 6)),
    }


class NarwalClient:
    """Serialized one-socket local client for the Narwal 9002 protocol."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_PORT,
        product_key: str = FLOW_PRODUCT_KEY,
        device_id: str = "",
        timeout: float = 15.0,
    ) -> None:
        self.host = host
        self.port = port
        self.product_key = product_key or FLOW_PRODUCT_KEY
        self.device_id = device_id.strip()
        self.timeout = timeout
        self._ws: Any = None
        self._command_lock = asyncio.Lock()

    @property
    def url(self) -> str:
        return f"ws://{_url_host(self.host)}:{self.port}"

    def _topic(self, short_topic: str, *, product_key: str | None = None, device_id: str | None = None) -> str:
        key = self.product_key if product_key is None else product_key
        identifier = self.device_id if device_id is None else device_id
        return f"/{key}/{identifier}/{short_topic}"

    async def connect(self) -> DeviceInfo:
        """Open the WebSocket and discover (or validate) the robot identity."""
        try:
            import websockets
        except ImportError as error:
            raise NarwalConnectionError(
                "The Narwal client needs websockets; run: pip install -r requirements.txt"
            ) from error
        try:
            self._ws = await websockets.connect(
                self.url,
                ping_interval=30,
                ping_timeout=10,
                open_timeout=min(self.timeout, 15),
            )
        except Exception as error:  # websockets has version-specific exception classes
            raise NarwalConnectionError(f"could not connect to {self.url}: {error}") from error
        try:
            if self.device_id:
                # A known device ID lets an addressed get_device_info wake an
                # active robot by itself.  Do this first: wake commands may
                # emit anonymous field-5 acknowledgements, which otherwise
                # race with the following identity query.
                try:
                    return await self.get_device_info()
                except (NarwalCommandError, NarwalProtocolError):
                    await self.wake()
                    await self._drain_incoming()
                    return await self.get_device_info()
            return await self.discover_identity()
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def __aenter__(self) -> "NarwalClient":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _send_frame(self, topic: str, payload: bytes = b"") -> None:
        if self._ws is None:
            raise NarwalConnectionError("client is not connected")
        await self._ws.send(build_frame(topic, payload))

    async def _drain_incoming(self, quiet_period: float = 0.2) -> None:
        """Discard acknowledgements produced by the fire-and-forget wake burst."""
        if self._ws is None:
            return
        # Let the robot deliver any immediate acknowledgements first, then
        # consume until the socket has been quiet.  Limit the operation so a
        # continuous broadcast stream cannot delay a user command indefinitely.
        await asyncio.sleep(0.35)
        deadline = time.monotonic() + 1.5
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                await asyncio.wait_for(self._ws.recv(), timeout=min(quiet_period, remaining))
            except TimeoutError:
                return

    async def _next_response(self, timeout: float) -> NarwalFrame:
        if self._ws is None:
            raise NarwalConnectionError("client is not connected")
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            except TimeoutError as error:
                raise NarwalCommandError("robot did not answer before the timeout") from error
            if not isinstance(raw, bytes):
                continue
            try:
                frame = parse_frame(raw)
            except NarwalProtocolError:
                continue
            if frame.field_tag == 0x2A:
                return frame
            LOG.debug("broadcast while awaiting command response: %s", frame.short_topic)
        raise NarwalCommandError("robot did not answer before the timeout")

    async def send_command(
        self, short_topic: str, payload: bytes = b"", *, timeout: float | None = None
    ) -> CommandResponse:
        """Send exactly one command and await its anonymous field-5 response.

        Field-5 replies contain no topic, so this lock is a protocol requirement:
        no parallel commands may share this WebSocket.
        """
        async with self._command_lock:
            await self._send_frame(self._topic(short_topic), payload)
            frame = await self._next_response(timeout if timeout is not None else self.timeout)
        fields = decode_protobuf(frame.payload)
        raw_result = _first(fields, 1)
        result_code = _as_int(raw_result)
        return CommandResponse(result_code, fields, frame.payload)

    async def discover_identity(self) -> DeviceInfo:
        """Resolve product key and device ID without cloud credentials."""
        keys = tuple(dict.fromkeys((self.product_key, *KNOWN_PRODUCT_KEYS)))
        # The initial burst is intentionally parallel.  A product-key mismatch
        # is silently ignored by the robot, whereas a correct one returns the
        # identity.  Sending the first Flow-family candidates together avoids
        # wasting the only short awake window on sequential timeouts.
        candidates = [f"/{self.product_key}//common/get_device_info", "//common/get_device_info"]
        candidates.extend(
            f"/{key}//common/get_device_info" for key in keys if key != self.product_key
        )
        frames = [build_frame(topic) for topic in candidates]
        for frame in frames[: min(5, len(frames))]:
            await self._ws.send(frame)

        deadline = time.monotonic() + self.timeout
        retry_index = 0
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=min(remaining, 2.0))
            except TimeoutError:
                # Cycle every known prefix.  This matches the upstream
                # discovery strategy and is needed for models whose product
                # key is not knowable from their mDNS record.
                await self._ws.send(frames[retry_index % len(frames)])
                retry_index += 1
                continue
            if not isinstance(raw, bytes):
                continue
            try:
                frame = parse_frame(raw)
                fields = decode_protobuf(frame.payload)
            except NarwalProtocolError:
                continue
            product_key = ""
            discovered_id = ""
            firmware = ""
            if frame.field_tag == 0x2A:
                fields = decode_protobuf(frame.payload)
                product_key = _as_text(_first(fields, 1))
                discovered_id = _as_text(_first(fields, 2))
                firmware = _as_text(_first(fields, 3))
            elif frame.topic:
                # Broadcast topics use /<product-key>/<device-id>/<topic>.
                parts = frame.topic.split("/")
                if len(parts) >= 4:
                    product_key = parts[1]
                    discovered_id = parts[2]
            if discovered_id:
                self.product_key = product_key or self.product_key
                self.device_id = discovered_id
                return DeviceInfo(self.product_key, self.device_id, firmware)
        raise NarwalCommandError(
            "could not discover a Narwal identity; verify the IP/model, wake the robot, "
            "and make sure another local controller is disconnected"
        )

    async def wake(self) -> None:
        """Send the non-destructive app-open/subscription/heartbeat wake burst."""
        for topic, payload in (
            ("common/notify_app_event", _encode_varint_field(1, 1)),
            ("common/active_robot_publish", build_topic_subscription()),
            ("status/app_status_heartbeat", _encode_varint_field(1, 1)),
        ):
            await self._send_frame(self._topic(topic), payload)
            await asyncio.sleep(0.1)

    async def get_device_info(self) -> DeviceInfo:
        response = await self.send_command("common/get_device_info")
        if not response.accepted:
            raise NarwalCommandError(f"get_device_info failed (result code {response.result_code})")
        product_key = _as_text(_first(response.fields, 1))
        device_id = _as_text(_first(response.fields, 2))
        firmware = _as_text(_first(response.fields, 3))
        if not device_id:
            raise NarwalProtocolError("get_device_info response did not contain a device ID")
        self.product_key = product_key or self.product_key
        self.device_id = device_id
        return DeviceInfo(self.product_key, self.device_id, firmware)

    async def _live_working_status(self, duration: float = 3.6) -> dict[str, Any] | None:
        """Subscribe briefly and sample working_status without issuing a robot action.

        Some Flow firmware can leave robot_base_status at ``docked_v2`` during
        an active clean.  An increasing working_status.elapsed_seconds is the
        safer signal before dispatching a new clean or a station command.
        """
        await self._send_frame(
            self._topic("common/active_robot_publish"), build_topic_subscription(60)
        )
        deadline = time.monotonic() + duration
        samples: list[dict[str, Any]] = []
        while (remaining := deadline - time.monotonic()) > 0:
            if self._ws is None:
                break
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=min(remaining, 1.0))
            except TimeoutError:
                continue
            if not isinstance(raw, bytes):
                continue
            try:
                frame = parse_frame(raw)
            except NarwalProtocolError:
                continue
            if frame.field_tag == 0x22 and frame.short_topic == "status/working_status":
                try:
                    samples.append(parse_working_status_payload(frame.payload))
                except NarwalProtocolError:
                    continue
        if not samples:
            return None
        live = dict(samples[-1])
        elapsed = [sample["elapsed_seconds"] for sample in samples if sample["elapsed_seconds"] is not None]
        live["live_cleaning"] = len(elapsed) >= 2 and elapsed[-1] > elapsed[0]
        # Be conservative for command safety.  A lone fresh working_status can
        # arrive between two progress ticks, so it cannot prove motion, but an
        # elapsed session or an active room is enough to prove task context.
        live["active_task_context"] = live["live_cleaning"] or any(
            (sample["elapsed_seconds"] or 0) > 0 or sample["current_room_id"] is not None
            for sample in samples
        )
        return live

    async def get_status(self) -> dict[str, Any]:
        """Read base status and augment it with a short live-work sample."""
        status = parse_status_response(await self.send_command("status/get_device_base_status"))
        live = await self._live_working_status()
        if live is None:
            return status
        status["live"] = live
        if live["active_task_context"]:
            # Preserve the raw base report for diagnostics, but don't present
            # it as authoritative when fresh work telemetry is present.
            status["base_state"] = status["state"]
            status["base_state_code"] = status["state_code"]
            status["state"] = "cleaning" if live["live_cleaning"] else "active_task_context"
            status["state_code"] = 4
            status["docked"] = False
        return status

    async def get_map(self) -> MapInfo:
        return parse_map_response(
            await self.send_command("map/get_map", timeout=max(self.timeout, 20.0))
        )

    async def require_docked(self, *, force: bool) -> None:
        if force:
            return
        status = await self.get_status()
        live = status.get("live")
        if isinstance(live, dict) and live.get("active_task_context") is True:
            raise NarwalCommandError(
                "robot has active work telemetry; do not start another task"
            )
        if status["docked"] is True:
            return
        state = status["state"] or "unknown"
        raise NarwalCommandError(
            f"robot is not confirmed docked (state={state}); dock it first, or use --force "
            "only if you have verified the state in the official app"
        )

    async def clean_rooms(
        self,
        room_ids: Iterable[int],
        *,
        mode: str,
        fan: str,
        water: str,
        mop_strength: str,
        passes: int,
        route: str | None,
        force: bool,
    ) -> CommandResponse:
        await self.require_docked(force=force)
        map_info = await self.get_map()
        payload = build_room_clean_payload(
            map_info.map_id,
            room_ids,
            mode=mode,
            fan=fan,
            water=water,
            mop_strength=mop_strength,
            passes=passes,
            route=route,
        )
        return await self.send_command("clean/start_clean", payload, timeout=15.0)

    async def clean_all(self, **settings: Any) -> CommandResponse:
        await self.require_docked(force=bool(settings.pop("force")))
        map_info = await self.get_map()
        if not map_info.rooms:
            raise NarwalCommandError("the active map contains no cleanable rooms")
        payload = build_room_clean_payload(
            map_info.map_id,
            (room.room_id for room in map_info.rooms),
            **settings,
        )
        return await self.send_command("clean/start_clean", payload, timeout=15.0)


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise NarwalError(f"could not read configuration {config_path}: {error}") from error
    except json.JSONDecodeError as error:
        raise NarwalError(f"configuration {config_path} is not valid JSON: {error}") from error
    if not isinstance(config, dict):
        raise NarwalError("Narwal configuration must be a JSON object")
    return config


def _parse_room_ids(raw: str) -> list[int]:
    try:
        rooms = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError("rooms must be comma-separated numeric IDs") from error
    if not rooms or any(room <= 0 for room in rooms):
        raise argparse.ArgumentTypeError("rooms must contain one or more positive numeric IDs")
    return rooms


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "identify", "status", "rooms", "locate", "pause", "resume", "stop", "cancel",
        "home", "quick-clean", "clean-all", "clean-rooms", "wash-mops", "dry-mops",
        "empty-bin", "set-fan", "set-water",
    ))
    parser.add_argument("--config", help="JSON config file; start from narwal_config.template.json")
    parser.add_argument("--host", help="Narwal LAN IP address; overrides config")
    parser.add_argument("--port", type=int, help="WebSocket port; defaults to 9002")
    parser.add_argument("--product-key", help="Narwal product key; defaults to Flow AX12")
    parser.add_argument("--device-id", help="Optional known device ID; otherwise discovered locally")
    parser.add_argument("--timeout", type=float, default=15.0, help="per-command timeout in seconds")
    parser.add_argument("--yes", action="store_true", help="allow a command that changes robot state")
    parser.add_argument("--force", action="store_true", help="skip the docked-state preflight for cleaning/station actions")
    parser.add_argument("--rooms", type=_parse_room_ids, help="comma-separated room IDs for clean-rooms")
    parser.add_argument("--mode", choices=tuple(WORK_MODES), default="vacuum-and-mop")
    parser.add_argument("--fan", choices=tuple(FAN_LEVELS), default="normal")
    parser.add_argument("--water", choices=tuple(WATER_LEVELS), default="normal")
    parser.add_argument("--mop-strength", choices=tuple(MOP_STRENGTHS), default="normal")
    parser.add_argument("--passes", type=int, default=1)
    parser.add_argument("--route", choices=tuple(ROUTES))
    parser.add_argument("--verbose", action="store_true")
    return parser


def _client_from_args(args: argparse.Namespace, config: dict[str, Any]) -> NarwalClient:
    host = args.host or config.get("host")
    if not isinstance(host, str) or not host.strip():
        raise NarwalError("set the robot IP with --host or in --config")
    port = args.port if args.port is not None else config.get("port", DEFAULT_PORT)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise NarwalError("port must be an integer between 1 and 65535")
    product_key = args.product_key or config.get("product_key", FLOW_PRODUCT_KEY)
    device_id = args.device_id or config.get("device_id", "")
    if not isinstance(product_key, str) or not isinstance(device_id, str):
        raise NarwalError("product_key and device_id in config must be strings")
    return NarwalClient(
        host.strip(), port=port, product_key=product_key.strip(), device_id=device_id.strip(),
        timeout=args.timeout,
    )


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_config(args.config)
    client = _client_from_args(args, config)
    if args.command in MUTATING_COMMANDS and not args.yes:
        raise NarwalError(f"'{args.command}' changes the robot state; rerun with --yes")
    info = await client.connect()
    try:
        if args.command == "identify":
            return info.as_dict()
        if args.command == "status":
            return {"identity": info.as_dict(), "status": await client.get_status()}
        if args.command == "rooms":
            return {"identity": info.as_dict(), "map": (await client.get_map()).as_dict()}
        if args.command == "clean-rooms":
            if not args.rooms:
                raise NarwalError("clean-rooms requires --rooms ID,ID")
            response = await client.clean_rooms(
                args.rooms, mode=args.mode, fan=args.fan, water=args.water,
                mop_strength=args.mop_strength, passes=args.passes, route=args.route, force=args.force,
            )
        elif args.command == "clean-all":
            response = await client.clean_all(
                mode=args.mode, fan=args.fan, water=args.water, mop_strength=args.mop_strength,
                passes=args.passes, route=args.route, force=args.force,
            )
        elif args.command in {"quick-clean", "wash-mops", "dry-mops", "empty-bin"}:
            await client.require_docked(force=args.force)
            topic = {
                "quick-clean": "clean/easy_clean/start",
                "wash-mops": "supply/wash_mop",
                "dry-mops": "supply/dry_mop",
                "empty-bin": "supply/dust_gathering",
            }[args.command]
            response = await client.send_command(topic)
        elif args.command in {"set-fan", "set-water"}:
            value = FAN_LEVELS[args.fan] if args.command == "set-fan" else WATER_LEVELS[args.water]
            topic = "clean/set_fan_level" if args.command == "set-fan" else "clean/set_mop_humidity"
            response = await client.send_command(topic, _encode_varint_field(1, value))
        else:
            topic = {
                "locate": "common/yell",
                "pause": "task/pause",
                "resume": "task/resume",
                "stop": "task/force_end",
                "cancel": "task/cancel",
                "home": "supply/recall",
            }[args.command]
            response = await client.send_command(topic, timeout=20.0 if args.command == "stop" else None)
        result = {"identity": info.as_dict(), "command": args.command, **response.summary()}
        if not response.accepted:
            result["hint"] = "The robot rejected the command; inspect status and confirm it is docked/idle."
        return result
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        result = asyncio.run(_run(args))
    except (NarwalError, ValueError) as error:
        print(f"Narwal error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("accepted", True) else 3


if __name__ == "__main__":
    raise SystemExit(main())
