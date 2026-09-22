# Guide for AI coding agents

You are working in **whatsapp-Narwal**: control a Narwal Flow/AX12 robot vacuum from a WhatsApp group.
Read this before changing anything. `ARCHITECTURE.md` explains the design; `NARWAL_RESEARCH.md` is the
robot protocol reference.

## Orientation (read these first, in order)

1. `README.md` — what it does and how to run it.
2. `docs/ARCHITECTURE.md` — the two-part (Node bridge + Python agent) design and why.
3. The module you're touching: `narwal_local.py` (robot protocol), `narwal_commands.py` (parser),
   `narwal_agent.py` (glue/HTTP), `bridge/index.js` (WhatsApp).

## Run and test

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -q                    # all offline; no robot or network needed
python narwal_agent.py simulate --config config.json --text "clean the kitchen" --dry-run
```

- Tests import repo-root modules via the root `conftest.py`. Keep it.
- There is no robot in CI. Never write a test that opens a socket or needs hardware. Test pure logic
  (`narwal_commands`) and protocol framing/parsing (`narwal_local`) with fixtures.
- `--dry-run` resolves and prints an intent without moving the robot; use it to check config/parsing.

## Where things belong

| If you're changing… | Edit | And add tests to |
|---|---|---|
| Which messages count as commands, room mapping, languages | `narwal_commands.py` (keep it **pure**) | `tests/test_narwal_commands.py` |
| Robot protocol / a new robot command | `narwal_local.py` | `tests/test_narwal_local.py` |
| HTTP receiving, dedup, clean policy, CLI | `narwal_agent.py` | (add a test module if logic is non-trivial) |
| WhatsApp reading | `bridge/index.js` | manual (Node; no unit tests shipped) |
| Robot/room/language settings | `config.example.json` (and the README example) | — |

## Rules

- **Never commit secrets or personal data.** No real LAN IPs, no device IDs, no phone numbers, no
  WhatsApp `auth/`. `config.json`, `bridge/.env`, and `bridge/auth/` are git-ignored — keep them so.
  `config.example.json` uses placeholders only.
- **Keep `narwal_commands.py` pure.** No file/network/robot access in it. That is what makes the
  "understanding" testable and language-agnostic. Home-specifics go in the config, not the code.
- **Don't invent protobuf semantics.** The Narwal protocol is reverse-engineered. Preserve raw/unknown
  fields; do not map an integer to a confident name without evidence (see `NARWAL_RESEARCH.md` — this
  exact mistake caused real bugs upstream). Use `clean/start_clean`, never `clean/plan/start`, for
  room jobs, and always read the live `map_id` rather than hard-coding one.
- **Respect the robot's realities.** One local socket per source IP → keep cleans serialized behind
  the robot lock. A fresh whole-home/structured clean can be refused off-dock (`NOT_READY`); treat a
  connected idle robot as "maybe not ready", not "go". `clean/start_clean` returns the new *state*, so
  result codes `3/4/5` mean "cleaning started" even though `accepted` (1/6) is False.
- **Keep the bridge read-only.** It must never send WhatsApp messages or mark chats read
  (`markOnlineOnConnect: false`). It only forwards text from the one configured group.
- **Don't add heavy dependencies.** The agent is stdlib + `flask` + `websockets`. The bridge is
  Baileys + `qrcode-terminal`. Prefer not to grow this.
- **No emojis in code, comments, or docs.** Preserve UTF-8 (Hebrew must render correctly).

## Safety when running against real hardware

- `simulate` without `--dry-run`, and any live `serve` + bridge, will **physically move the robot**.
  Prefer `--dry-run` while developing.
- The robot's 9002 port is unauthenticated cleartext. Never expose it to the internet.

## Good first tasks

- Add rooms/verbs/aliases for a new language to `config.example.json` and a test in
  `tests/test_narwal_commands.py`.
- Add a `Telegram`/`curl` example to the README showing the platform-agnostic `POST /whatsapp {id,text}`.
- Improve model detection or discovery in `narwal_local.py` (mDNS `_narwal_sweeper._tcp.local.`), with
  fixtures — see the discovery section of `NARWAL_RESEARCH.md`.
