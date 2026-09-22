# Architecture

This document explains how whatsapp-Narwal is put together, so a contributor (human or AI) can change
it safely. For the robot protocol itself, see `NARWAL_RESEARCH.md`.

## The problem shape

Two hard constraints drive the whole design:

1. **The robot is LAN-only.** A Narwal Flow/AX12 answers on `ws://<robot-ip>:9002` on the home
   network, with no cloud and no authentication. Whatever controls it must sit on that LAN.
2. **WhatsApp is Node-only.** The practical way to read a WhatsApp group as a linked device is
   Baileys, which is a Node/TypeScript library. There is no comparable maintained Python client.

So the system is split into a **Node bridge** (WhatsApp → localhost HTTP) and a **Python agent**
(HTTP → understanding → robot). The seam between them is a single POST of `{id, text}`.

```
┌────────────┐   linked device    ┌───────────┐   POST /whatsapp {id,text}   ┌───────────────┐   ws://ip:9002   ┌────────────┐
│  WhatsApp  │ ─────────────────► │  bridge/  │ ───────────────────────────► │ narwal_agent  │ ───────────────► │  Narwal    │
│   group    │                    │  (Node)   │        localhost              │  (Python)     │   protobuf       │  Flow/AX12 │
└────────────┘                    └───────────┘                               └───────────────┘                  └────────────┘
                                                                                     │
                                                                     narwal_commands.parse_command()
                                                                     (pure: text -> clean intent)
```

## Components

### `narwal_local.py` — the robot client (transport + protocol)

A self-contained async client for the Narwal 9002 protocol, plus a guarded CLI. Responsibilities:

- **Framing** (`build_frame`/`parse_frame`): the 4-byte Narwal envelope around a protobuf payload.
- **Schema-less protobuf** (`decode_protobuf`): length-delimited values stay raw bytes unless the
  protocol is established, so unknown fields are never mis-typed.
- **Session** (`NarwalClient`): one serialized WebSocket, identity discovery, wake burst, subscription
  renewal, and a command lock (field-5 responses carry no topic, so commands must not overlap).
- **Cleaning** (`build_room_clean_payload`, `clean_rooms`, `clean_all`): reads the live map, builds a
  `CleanTask` with the real `map_id` and ordered room IDs, and sends `clean/start_clean` (never
  `clean/plan/start`). A docked-state preflight guards new cleans.

It knows nothing about WhatsApp or rooms-by-name. It is the same code the CLI and the agent share.

Key result-code note: `clean/start_clean` answers with the robot's **new state**, not a plain ack.
Codes `3/4/5` are "cleaning" states — the clean started — even though `CommandResponse.accepted`
(which is `1/6`) is False. The agent treats `3/4/5` as "started".

### `narwal_commands.py` — the parser (pure understanding)

`parse_command(text, rooms, all_aliases, verbs) -> CleanIntent | None`. This is the entire "does this
message mean anything, and what?" layer, and it is deliberately **pure** (no I/O) so it is trivially
testable and language-agnostic:

- A **clean verb** must be present (else `None`). This is the command/chatter separator.
- **Whole-home** aliases win over room matches.
- **Rooms** are matched longest-first and consumed, so `"living-room toilet"` is one room, not two.
- Normalization folds Hebrew niqqud and geresh; harmless for other scripts.

Everything home-specific (room names, their numeric IDs, the verbs, the whole-home phrases) lives in
the config, not in code.

### `narwal_agent.py` — the agent (glue + policy)

- `create_app(config)` builds a small Flask app with `POST /whatsapp` and `GET /health`.
- Per message: optional shared-token check → dedup by `id` (a bounded set, so redelivery is a no-op)
  → `parse_command` → if a command, drive the robot behind a **robot lock** (one socket per source IP).
- `clean.mode` (default `vacuum-then-mop`) plus fan/water/mop-strength/passes/route come from config.
- CLI: `serve` (run the receiver) and `simulate` (feed one message, `--dry-run` to preview) so you can
  test end-to-end on the hardware without the bridge.

### `bridge/` — the WhatsApp bridge (Node)

Baileys linked device. Watches one group (by title or JID), extracts each live message's text, and
POSTs `{id, text}` to the agent. Read-only: never sends, never marks read. Pairs once by QR; stores
credentials in `bridge/auth/`.

### `narwal_dashboard.py` — optional manual control

A localhost-only Flask UI to drive the robot by hand (status, rooms, clean, dock tasks). Independent
of the WhatsApp path; shares `narwal_local.py` and the same `config.json`.

## Data flow of one command

1. A member sends `נקה את המטבח` in the group.
2. The bridge sees a live `notify` message in the matched group, extracts `"נקה את המטבח"`, and POSTs
   `{"id": "<waid>", "text": "נקה את המטבח"}` to the agent.
3. The agent dedups the `id`, calls `parse_command` → `CleanIntent(scope="rooms", room_ids=(5,))`.
4. Behind the robot lock, it opens a session, reads the live map, builds a `CleanTask` for room 5 in
   `vacuum-then-mop` mode, and sends `clean/start_clean`.
5. The robot returns `result_code 3` ("cleaning") and starts. The agent logs "started cleaning".

## Extension points

- **Another chat platform:** POST `{id, text}` to `/whatsapp` from anything (Telegram bot, MQTT rule,
  `curl`). No agent change needed.
- **Another language / more rooms:** edit `config.json` (`commands.verbs`, `commands.all_aliases`,
  `commands.rooms`). No code change.
- **Different clean policy:** `config.clean` (mode/fan/water/mop_strength/passes/route).
- **New robot capability:** add a method to `NarwalClient` following the existing command pattern; keep
  raw/unknown protobuf fields rather than guessing semantics (see `NARWAL_RESEARCH.md` on why).

## Deliberate non-goals

- No map editing, no-go zones, or camera/video (not reliably reverse-engineered — see the research).
- No cloud fallback (this project is LAN-only by design).
- The parser does not do fuzzy/NLP matching; it is an explicit, auditable verb+room rule.
