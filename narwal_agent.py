#!/usr/bin/env python3
"""The agent: turn incoming chat messages into robot cleans.

It runs a tiny local HTTP server that the WhatsApp bridge (see bridge/) posts each group message to.
For every message it decides -- with narwal_commands.parse_command and the room map in the config --
whether the message is a clean command, and if so drives the Narwal robot over the LAN
(narwal_local.NarwalClient) to clean the requested rooms, or the whole home. "Clean" means whatever
`clean.mode` says in the config; the shipped default is vacuum-then-mop.

    python narwal_agent.py serve    --config config.json
    python narwal_agent.py simulate --config config.json --text "clean the kitchen"
    python narwal_agent.py simulate --config config.json --text "clean the kitchen" --dry-run

Why HTTP + a separate bridge: the robot speaks only on the home LAN, and WhatsApp's linked-device
protocol is Node-only (Baileys). Keeping the WhatsApp side in a small Node bridge that just forwards
message text over localhost keeps this Python agent simple, testable, and reusable with any message
source (post the same JSON from Telegram, an MQTT rule, curl, ...).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from narwal_local import (
    FAN_LEVELS,
    MOP_STRENGTHS,
    ROUTES,
    WATER_LEVELS,
    WORK_MODES,
    NarwalClient,
    NarwalError,
)
from narwal_commands import CleanIntent, parse_command

DEFAULT_AGENT_PORT = 8799
DEFAULT_DEDUP_SIZE = 200
DEFAULT_CLEAN = {"mode": "vacuum-then-mop", "fan": "normal", "water": "normal", "mop_strength": "normal", "passes": 1, "route": None}

_LOG_FILE: str | None = None


class AgentError(RuntimeError):
    pass


def log(message: str) -> None:
    line = f"{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')} {message}"
    if _LOG_FILE:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return
        except OSError:
            pass
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except (ValueError, OSError):
            pass


# --------------------------------------------------------------------------------------- config


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        raise AgentError("a --config JSON file is required (start from config.example.json)")
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise AgentError(f"could not read configuration {config_path}: {error}")
    except json.JSONDecodeError as error:
        raise AgentError(f"configuration {config_path} is not valid JSON: {error}")
    if not isinstance(config, dict):
        raise AgentError("configuration must be a JSON object")
    return config


def _commands(config: dict[str, Any]) -> dict[str, Any]:
    commands = config.get("commands")
    if not isinstance(commands, dict) or not isinstance(commands.get("rooms"), dict) or not commands["rooms"]:
        raise AgentError("config.commands.rooms must map room names to lists of numeric room IDs")
    return commands


def _clean_settings(config: dict[str, Any]) -> dict[str, Any]:
    clean = {**DEFAULT_CLEAN, **(config.get("clean") if isinstance(config.get("clean"), dict) else {})}
    for name, table in (("mode", WORK_MODES), ("fan", FAN_LEVELS), ("water", WATER_LEVELS), ("mop_strength", MOP_STRENGTHS)):
        if clean[name] not in table:
            raise AgentError(f"config.clean.{name}={clean[name]!r} is not one of {sorted(table)}")
    if clean["route"] is not None and clean["route"] not in ROUTES:
        raise AgentError(f"config.clean.route must be null or one of {sorted(ROUTES)}")
    if not isinstance(clean["passes"], int) or isinstance(clean["passes"], bool) or not 1 <= clean["passes"] <= 3:
        raise AgentError("config.clean.passes must be an integer from 1 to 3")
    return clean


def _robot_client(config: dict[str, Any]) -> NarwalClient:
    host = config.get("host")
    if not isinstance(host, str) or not host.strip():
        raise AgentError("set the robot IP as top-level 'host' in --config")
    port = config.get("port", 9002)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise AgentError("port must be an integer between 1 and 65535")
    product_key = config.get("product_key", "")
    device_id = config.get("device_id", "")
    if not isinstance(product_key, str) or not isinstance(device_id, str):
        raise AgentError("product_key and device_id must be strings")
    return NarwalClient(host.strip(), port=port, product_key=product_key.strip(), device_id=device_id.strip())


def resolve_intent(config: dict[str, Any], text: str) -> CleanIntent | None:
    commands = _commands(config)
    return parse_command(
        text,
        rooms=commands["rooms"],
        all_aliases=commands.get("all_aliases", []),
        verbs=commands.get("verbs", []),
    )


# --------------------------------------------------------------------------------- robot action


async def _drive_clean(config: dict[str, Any], intent: CleanIntent) -> dict[str, Any]:
    settings = {**_clean_settings(config), "force": False}
    client = _robot_client(config)
    await client.connect()
    try:
        if intent.scope == "all":
            response = await client.clean_all(**settings)
        else:
            response = await client.clean_rooms(list(intent.room_ids), **settings)
        return response.summary()
    finally:
        await client.close()


def clean_for_message(config: dict[str, Any], robot_lock: threading.Lock, text: str) -> dict[str, Any]:
    """Resolve a message and, if it is a command, drive the robot. Returns a small result dict.

    The robot allows one local socket per source IP, so every clean is serialized behind `robot_lock`
    -- two messages arriving together can never open two sockets."""
    intent = resolve_intent(config, text)
    if intent is None:
        return {"recognized": False}
    target = "all" if intent.scope == "all" else list(intent.room_ids)
    mode = _clean_settings(config)["mode"]
    log(f"command recognized: scope={intent.scope} rooms={list(intent.room_ids)} mode={mode}: {text!r}")
    try:
        with robot_lock:
            result = asyncio.run(_drive_clean(config, intent))
    except NarwalError as error:
        log(f"robot did not start the clean: {error}")
        return {"recognized": True, "scope": intent.scope, "room_ids": list(intent.room_ids), "started": False, "error": str(error)}
    # clean/start_clean answers with the robot's new state, not a plain ack: codes 3/4/5 are
    # "cleaning" states, so the robot has started even though `accepted` (1/6 only) is False.
    code = result.get("result_code")
    started = bool(result.get("accepted")) or code in (3, 4, 5)
    log(f"robot {'started cleaning' if started else 'did NOT accept the clean'} (result_code={code}); target={target}")
    return {"recognized": True, "scope": intent.scope, "room_ids": list(intent.room_ids), "started": started, "result_code": code}


# ----------------------------------------------------------------------------------- HTTP server


def create_app(config: dict[str, Any]):
    from flask import Flask, Response, jsonify, request

    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    token = agent.get("token")
    dedup_size = int(agent.get("dedup_size", DEFAULT_DEDUP_SIZE))
    _commands(config)  # validate the room map once at startup, not on the first message
    _clean_settings(config)

    app = Flask(__name__)
    robot_lock = threading.Lock()
    dedup_lock = threading.Lock()
    seen_ids: deque[str] = deque(maxlen=max(1, dedup_size))
    seen_set: set[str] = set()

    def already_handled(message_id: str) -> bool:
        with dedup_lock:
            if message_id in seen_set:
                return True
            if len(seen_ids) == seen_ids.maxlen:
                seen_set.discard(seen_ids[0])
            seen_ids.append(message_id)
            seen_set.add(message_id)
            return False

    @app.after_request
    def _headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> Response:
        return jsonify({"ok": True})

    @app.post("/whatsapp")
    def whatsapp() -> Response:
        if token and request.headers.get("X-Auth-Token") != token:
            return jsonify({"error": "unauthorized"}), 401
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            return jsonify({"error": "expected JSON {id, text}"}), 400
        message_id = str(payload.get("id") or payload["text"])
        if already_handled(message_id):
            return jsonify({"recognized": False, "duplicate": True})
        return jsonify(clean_for_message(config, robot_lock, payload["text"]))

    return app


# --------------------------------------------------------------------------------------- commands


def command_serve(args: argparse.Namespace) -> int:
    global _LOG_FILE
    config = load_config(args.config)
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    if getattr(args, "log_file", None) or agent.get("log_file"):
        _LOG_FILE = str(Path(args.log_file or agent["log_file"]).expanduser())
    host = args.host or agent.get("host") or "127.0.0.1"
    port = int(args.port or agent.get("port") or DEFAULT_AGENT_PORT)
    app = create_app(config)
    log(f"agent listening on http://{host}:{port}  (POST /whatsapp)")
    app.run(host=host, port=port, debug=False, threaded=True)
    return 0


def command_simulate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    intent = resolve_intent(config, args.text)
    if intent is None:
        print(json.dumps({"text": args.text, "recognized": False}, ensure_ascii=False, indent=2))
        return 1
    summary = {"text": args.text, "recognized": True, "scope": intent.scope, "room_ids": list(intent.room_ids), "mode": _clean_settings(config)["mode"]}
    if args.dry_run:
        print(json.dumps({**summary, "dry_run": True}, ensure_ascii=False, indent=2))
        return 0
    result = clean_for_message(config, threading.Lock(), args.text)
    print(json.dumps({**summary, **result}, ensure_ascii=False, indent=2))
    return 0 if result.get("started") else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WhatsApp -> Narwal robot-vacuum agent")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the local HTTP receiver that the WhatsApp bridge posts to")
    serve.add_argument("--config", required=True, help="JSON config (start from config.example.json)")
    serve.add_argument("--host", help="bind address (default: config.agent.host or 127.0.0.1)")
    serve.add_argument("--port", type=int, help="bind port (default: config.agent.port or 8799)")
    serve.add_argument("--log-file", help="append logs here instead of stdout")
    serve.set_defaults(handler=command_serve)

    simulate = commands.add_parser("simulate", help="feed one message locally and drive the robot (no bridge needed)")
    simulate.add_argument("--config", required=True, help="JSON config (start from config.example.json)")
    simulate.add_argument("--text", required=True, help='the message text, e.g. "clean the kitchen" / "נקה את המטבח"')
    simulate.add_argument("--dry-run", action="store_true", help="only resolve and print the intent; do not move the robot")
    simulate.set_defaults(handler=command_simulate)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except AgentError as error:
        log(f"error: {error}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
