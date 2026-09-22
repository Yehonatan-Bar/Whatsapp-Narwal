# whatsapp-Narwal

Control a **Narwal Flow / AX12 robot vacuum from a WhatsApp group**. Send a message like
`clean the kitchen` (or, in Hebrew, `נקה את המטבח`) to a dedicated group and the robot cleans that
room — by default **vacuum, then mop**. No Narwal cloud account is used; the robot is driven directly
over your home LAN.

The project is deliberately small, self-contained, and language-agnostic (rooms, verbs, and
whole-home phrases all come from your config), so it works in English, Hebrew, or anything else.

---

## How it works

```
WhatsApp group  ──(linked device)──►  bridge/  (Node, Baileys)
                                          │  POST http://127.0.0.1:8799/whatsapp  {id, text}
                                          ▼
                                     narwal_agent.py  (Python)
                                          │  parse_command(text)  ─►  clean intent (rooms / whole-home)
                                          ▼
                                     narwal_local.py  ──ws://<robot-ip>:9002──►  Narwal Flow / AX12
                                                                                   (vacuum, then mop)
```

Two moving parts, split for a reason:

- **The bridge** (`bridge/`) speaks WhatsApp's linked-device protocol, which is Node-only (Baileys).
  It watches one group and forwards each message's text to the agent over localhost. Nothing else.
- **The agent** (`narwal_agent.py`) is pure Python. It decides whether a message is a clean command
  (a clean *verb* plus a known *room*), then drives the robot on the LAN. The robot is only reachable
  on the home LAN, so the agent must run on a machine on that LAN.

Because the interface between them is just an HTTP POST of `{id, text}`, you can drive the robot from
**any** source — Telegram, an MQTT rule, or `curl` — not only WhatsApp.

---

## Repository layout

| Path | What it is |
|---|---|
| `narwal_local.py` | The Narwal LAN client + a guarded CLI (`identify` / `status` / `rooms` / `clean-rooms` / …). Speaks the robot's WebSocket/protobuf protocol at `ws://<ip>:9002`. Standalone. |
| `narwal_commands.py` | **Pure** parser: a chat message → a clean intent (which rooms, or whole-home). All the "understanding". No I/O. |
| `narwal_agent.py` | The agent: an HTTP receiver (`serve`) that turns incoming messages into robot cleans, plus a `simulate` command for testing on the hardware without WhatsApp. |
| `narwal_dashboard.py` + `.html` | Optional local-only (127.0.0.1) web dashboard to drive the robot by hand. |
| `bridge/` | The Node/Baileys WhatsApp bridge (pair once by QR; forwards one group to the agent). |
| `config.example.json` | Copy to `config.json` and fill in your robot IP + room map. `config.json` is git-ignored. |
| `tests/` | Offline unit tests (no robot, no network). |
| `docs/ARCHITECTURE.md` | How the pieces fit; for contributors and coding agents. |
| `docs/AGENTS.md` | A guide for AI coding agents working in this repo. |
| `docs/NARWAL_RESEARCH.md` | The full Narwal local-control reverse-engineering report this client is based on. |

---

## Quick start

### 0. Requirements

- A Narwal **Flow / AX12** already joined to your Wi-Fi (see compatibility below).
- Python 3.10+ on a machine on the **same LAN/VLAN** as the robot.
- Node.js 20.6+ (for the WhatsApp bridge).

```bash
pip install -r requirements.txt
cp config.example.json config.json     # then edit it (see below)
```

### 1. Find the robot and its rooms

The robot identifies rooms by **number**, not name. From a machine on the robot's LAN:

```bash
python narwal_local.py identify --config config.json     # confirms IP/model/firmware
python narwal_local.py rooms    --config config.json     # prints map_id + room IDs
```

Put the robot's IP in `config.json` (`host`), and map each room name you want to say to its numeric
ID under `commands.rooms`.

### 2. Configure `config.json`

Top-level keys are the robot connection; `commands` is the language/room map; `clean` is how to
clean; `agent` is the local HTTP receiver. A Hebrew example (matching the "Gimli" use case):

```json
{
  "host": "192.168.1.50",
  "port": 9002,
  "product_key": "QoEsI5qYXO",
  "device_id": "",
  "clean": { "mode": "vacuum-then-mop", "fan": "normal", "water": "normal", "passes": 1 },
  "commands": {
    "verbs": ["נקה", "תנקה", "לנקות", "שאב", "שטוף", "clean", "vacuum", "mop"],
    "all_aliases": ["הכל", "כל הבית", "הבית", "everything"],
    "rooms": {
      "סלון": [1],
      "המאורה": [2], "מאורה": [2],
      "שרותי המאורה": [3], "שירותי המאורה": [3],
      "שרותים": [4], "שירותים": [4],
      "מטבח": [5],
      "פינת אוכל": [6], "פינת האוכל": [6],
      "מסדרון": [7]
    }
  },
  "agent": { "host": "127.0.0.1", "port": 8799 }
}
```

`clean.mode` is `vacuum-then-mop` by default; other modes are `vacuum`, `mop`, `vacuum-and-mop`.

### 3. Test on the hardware without WhatsApp

```bash
python narwal_agent.py simulate --config config.json --text "נקה את הסלון" --dry-run   # just shows the intent
python narwal_agent.py simulate --config config.json --text "נקה את הסלון"             # actually cleans room 1
```

### 4. Run the agent, then pair the WhatsApp bridge

```bash
python narwal_agent.py serve --config config.json          # terminal 1: the receiver
```

```bash
cd bridge && npm install && cp .env.example .env           # terminal 2: edit .env (GROUP_TITLE=…)
npm start                                                   # scan the QR once
```

Now send `נקה את המטבח` (or `clean the kitchen`) in the group — within a second or two the robot
starts. See `bridge/README.md` for details.

---

## The command rule

A message triggers a clean only if it contains a **clean verb** (from `commands.verbs`) — this is
what separates a command from ordinary chatter ("thanks!", "the kitchen is a mess"). The target is:

- a **whole-home** phrase (`commands.all_aliases`) → clean everything; or
- one or more **rooms** (`commands.rooms`), matched longest-first so a two-word room name is not also
  read as the shorter room whose name it contains.

A message with a verb but no known room, or a room but no verb, does nothing. Hebrew niqqud and the
geresh/apostrophe are folded, so pointed/゛spoken-style spellings still match.

---

## Safety

- **The robot's port 9002 is cleartext and has no local authentication.** LAN access is the security
  boundary. Never expose or port-forward 9002 to the internet; keep the robot on a trusted/IoT VLAN.
- Cleaning is **serialized** and the robot's own dock-state safeguard applies (it refuses to start a
  fresh whole-home/structured clean when it is not docked). The agent reports, and does not retry
  destructively.
- The WhatsApp bridge is **read-only** and uses an **unofficial** client (Baileys) — some ban risk;
  use a number you are comfortable linking. Keep `bridge/auth/` private.
- Keep `config.json` out of git (it holds your robot's LAN IP / device id). It is git-ignored.

---

## Compatibility

The standard **Narwal Flow (AX12)** is the primary, hardware-validated target (product key
`QoEsI5qYXO`, firmware `v01.08.03.07` well tested). Other 9002-family models (Flow 2, several Freo /
AX / CX variants) are likely to work but are less validated; a self-identified "Flow compact" unit
was reported with 9002 closed. Confirm a model with `nmap -p 9002 <robot-ip>` and
`python narwal_local.py identify`. The full protocol/compatibility report is in
`docs/NARWAL_RESEARCH.md`.

---

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

All tests are offline (no robot, no network). See `docs/AGENTS.md` before making changes.
