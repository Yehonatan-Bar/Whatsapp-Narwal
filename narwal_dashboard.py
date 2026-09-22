"""Local-only Hebrew dashboard for a Narwal Flow / AX12 vacuum.

Run ``python narwal_dashboard.py --config narwal_config.json`` and open the
printed localhost URL.  The HTTP server never binds to the network; it is only
an interface to the local WebSocket client in :mod:`narwal_local`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from flask import Flask, Response, jsonify, request, send_from_directory

from narwal_local import (
    FAN_LEVELS,
    FLOW_PRODUCT_KEY,
    MOP_STRENGTHS,
    ROUTES,
    WATER_LEVELS,
    WORK_MODES,
    DEFAULT_PORT,
    NarwalClient,
    NarwalError,
)


LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class RobotSettings:
    """Connection values for the one robot controlled by this dashboard."""

    host: str
    port: int = DEFAULT_PORT
    product_key: str = FLOW_PRODUCT_KEY
    device_id: str = ""
    timeout: float = 15.0
    # The robot map may contain no user-visible room names.  These aliases are
    # local dashboard labels only; room IDs sent in cleaning commands are not
    # changed.
    room_names: dict[int, str] = field(default_factory=dict)


def _map_with_local_room_names(
    map_data: dict[str, Any], room_names: Mapping[int, str]
) -> dict[str, Any]:
    """Return map data with optional local aliases applied to its rooms.

    Narwal's local map response frequently has empty room names.  Copy the
    response before decorating it so this presentation-only step cannot alter
    the model used by the protocol client.
    """
    rooms = map_data.get("rooms")
    if not isinstance(rooms, list) or not room_names:
        return map_data
    decorated = dict(map_data)
    decorated_rooms: list[dict[str, Any]] = []
    for room in rooms:
        if not isinstance(room, dict):
            decorated_rooms.append(room)
            continue
        display_room = dict(room)
        room_id = display_room.get("id")
        if isinstance(room_id, int) and not isinstance(room_id, bool):
            local_name = room_names.get(room_id)
            if local_name:
                display_room["name"] = local_name
        decorated_rooms.append(display_room)
    decorated["rooms"] = decorated_rooms
    return decorated


def _clean_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the documented CleanTask options supplied by the UI."""
    values: dict[str, Any] = {}
    allowed = {
        "mode": WORK_MODES,
        "fan": FAN_LEVELS,
        "water": WATER_LEVELS,
        "mop_strength": MOP_STRENGTHS,
    }
    for name, choices in allowed.items():
        value = data.get(name, "vacuum-and-mop" if name == "mode" else "normal")
        if not isinstance(value, str) or value not in choices:
            raise NarwalError(f"invalid {name} setting")
        values[name] = value
    route = data.get("route")
    if route is not None and (not isinstance(route, str) or route not in ROUTES):
        raise NarwalError("invalid route setting")
    values["route"] = route
    passes = data.get("passes", 1)
    if not isinstance(passes, int) or isinstance(passes, bool) or not 1 <= passes <= 3:
        raise NarwalError("passes must be an integer from 1 through 3")
    values["passes"] = passes
    return values


async def run_robot_operation(
    settings: RobotSettings, operation: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Open one serialized local session, execute an operation, then close it."""
    client = NarwalClient(
        settings.host,
        port=settings.port,
        product_key=settings.product_key,
        device_id=settings.device_id,
        timeout=settings.timeout,
    )
    info = await client.connect()
    try:
        if operation == "status":
            return {"identity": info.as_dict(), "status": await client.get_status()}
        if operation == "rooms":
            map_data = (await client.get_map()).as_dict()
            return {
                "identity": info.as_dict(),
                "map": _map_with_local_room_names(map_data, settings.room_names),
            }

        if operation == "clean-rooms":
            room_ids = payload.get("rooms")
            if (
                not isinstance(room_ids, list)
                or not room_ids
                or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in room_ids)
            ):
                raise NarwalError("בחר לפחות חדר אחד עם מזהה מספרי תקין")
            response = await client.clean_rooms(room_ids, force=False, **_clean_settings(payload))
        elif operation == "clean-all":
            response = await client.clean_all(force=False, **_clean_settings(payload))
        elif operation in {"quick-clean", "wash-mops", "dry-mops", "empty-bin"}:
            await client.require_docked(force=False)
            topic = {
                "quick-clean": "clean/easy_clean/start",
                "wash-mops": "supply/wash_mop",
                "dry-mops": "supply/dry_mop",
                "empty-bin": "supply/dust_gathering",
            }[operation]
            response = await client.send_command(topic)
        elif operation == "set-fan":
            fan = payload.get("fan")
            if not isinstance(fan, str) or fan not in FAN_LEVELS:
                raise NarwalError("invalid fan setting")
            response = await client.send_command("clean/set_fan_level", bytes((8, FAN_LEVELS[fan])))
        elif operation == "set-water":
            water = payload.get("water")
            if not isinstance(water, str) or water not in WATER_LEVELS:
                raise NarwalError("invalid water setting")
            response = await client.send_command("clean/set_mop_humidity", bytes((8, WATER_LEVELS[water])))
        else:
            topics = {
                "locate": "common/yell",
                "pause": "task/pause",
                "resume": "task/resume",
                "stop": "task/force_end",
                "cancel": "task/cancel",
                "home": "supply/recall",
            }
            if operation not in topics:
                raise NarwalError(f"unsupported dashboard action: {operation}")
            response = await client.send_command(
                topics[operation], timeout=20.0 if operation == "stop" else None
            )
        return {"identity": info.as_dict(), "command": operation, **response.summary()}
    finally:
        await client.close()


Runner = Callable[[RobotSettings, str, dict[str, Any]], Awaitable[dict[str, Any]]]


def create_app(settings: RobotSettings, *, runner: Runner = run_robot_operation) -> Flask:
    """Create the local dashboard app without exposing a network listener."""
    app = Flask(__name__)
    # The robot accepts one socket per source IP.  Serializing *all* page
    # refreshes and actions avoids an automatic refresh closing an active action.
    robot_lock = threading.Lock()

    def run_serialized(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        with robot_lock:
            return asyncio.run(runner(settings, operation, payload))

    @app.after_request
    def local_only_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def dashboard() -> Response:
        return send_from_directory(ROOT, "narwal_dashboard.html")

    @app.get("/api/status")
    def status() -> Response:
        try:
            return jsonify(run_serialized("status", {}))
        except NarwalError as error:
            return jsonify({"error": str(error)}), 502
        except Exception:  # noqa: BLE001 - avoid leaking a local traceback to the page
            LOG.exception("Unexpected error reading Narwal status")
            return jsonify({"error": "שגיאה פנימית בעת קריאת סטטוס הרובוט"}), 500

    @app.get("/api/rooms")
    def rooms() -> Response:
        try:
            return jsonify(run_serialized("rooms", {}))
        except NarwalError as error:
            return jsonify({"error": str(error)}), 502
        except Exception:  # noqa: BLE001 - avoid leaking a local traceback to the page
            LOG.exception("Unexpected error reading Narwal rooms")
            return jsonify({"error": "שגיאה פנימית בעת קריאת מפת החדרים"}), 500

    @app.post("/api/actions/<operation>")
    def action(operation: str) -> Response:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "נדרש גוף JSON"}), 400
        # A request must opt in explicitly.  This protects against an accidental
        # click/navigation and applies even to relatively harmless locate.
        if payload.get("confirm") is not True:
            return jsonify({"error": "נדרש אישור מפורש לפעולה"}), 400
        try:
            return jsonify(run_serialized(operation, payload))
        except NarwalError as error:
            return jsonify({"error": str(error)}), 422
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except Exception:  # noqa: BLE001 - same local, non-leaky error contract
            LOG.exception("Unexpected error while executing Narwal action %s", operation)
            return jsonify({"error": "שגיאה פנימית בעת שליחת הפקודה לרובוט"}), 500

    return app


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise NarwalError(f"could not read configuration {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise NarwalError(f"configuration {path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise NarwalError("Narwal configuration must be a JSON object")
    return data


def _robot_settings(args: argparse.Namespace) -> RobotSettings:
    config = _load_config(args.config)
    host = args.host or config.get("host")
    if not isinstance(host, str) or not host.strip():
        raise NarwalError("set the robot IP with --host or in --config")
    robot_port = args.robot_port if args.robot_port is not None else config.get("port", DEFAULT_PORT)
    if not isinstance(robot_port, int) or not 1 <= robot_port <= 65535:
        raise NarwalError("robot port must be an integer between 1 and 65535")
    product_key = args.product_key or config.get("product_key", FLOW_PRODUCT_KEY)
    device_id = args.device_id or config.get("device_id", "")
    if not isinstance(product_key, str) or not isinstance(device_id, str):
        raise NarwalError("product_key and device_id in config must be strings")
    raw_room_names = config.get("room_names", {})
    if not isinstance(raw_room_names, dict):
        raise NarwalError("room_names in config must be an object mapping room IDs to names")
    room_names: dict[int, str] = {}
    for raw_room_id, raw_name in raw_room_names.items():
        try:
            room_id = int(raw_room_id)
        except (TypeError, ValueError) as error:
            raise NarwalError("each room_names key must be a positive room ID") from error
        if room_id <= 0 or isinstance(raw_name, bool) or not isinstance(raw_name, str) or not raw_name.strip():
            raise NarwalError("each room_names entry needs a positive ID and a non-empty name")
        room_names[room_id] = raw_name.strip()
    return RobotSettings(
        host=host.strip(), port=robot_port, product_key=product_key.strip(),
        device_id=device_id.strip(), timeout=args.timeout, room_names=room_names,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="JSON configuration; start from narwal_config.template.json")
    parser.add_argument("--host", help="robot IP; overrides the config")
    parser.add_argument("--robot-port", type=int, help="robot WebSocket port; defaults to 9002")
    parser.add_argument("--product-key", help="robot product key; defaults to Narwal Flow AX12")
    parser.add_argument("--device-id", help="optional known robot device ID")
    parser.add_argument("--timeout", type=float, default=15.0, help="robot command timeout in seconds")
    parser.add_argument("--port", type=int, default=8790, help="local dashboard port (default: 8790)")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        settings = _robot_settings(args)
        if not 1 <= args.port <= 65535:
            raise NarwalError("dashboard port must be an integer between 1 and 65535")
    except NarwalError as error:
        print(f"Narwal dashboard error: {error}")
        return 2
    url = f"http://127.0.0.1:{args.port}"
    print(f"Narwal dashboard: {url}")
    print("The server listens only on 127.0.0.1. Press Ctrl+C to stop it.")
    create_app(settings).run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
