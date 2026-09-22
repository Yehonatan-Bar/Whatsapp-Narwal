# WhatsApp bridge

A tiny Node service that connects to WhatsApp as a **linked device** (Baileys), watches one group,
and forwards each new message's text to the Python agent over localhost. It never sends messages and
never marks chats read — it only reads the one configured group.

## Setup

Requires Node.js 20.6+ (for `--env-file`).

```bash
cd bridge
npm install
cp .env.example .env      # then edit .env (set GROUP_TITLE and, if used, AGENT_TOKEN)
npm start                 # prints a QR code on first run
```

Scan the QR from your phone: **WhatsApp > Settings > Linked devices > Link a device**. The
linked-device credentials are stored in `bridge/auth/` (git-ignored); you only pair once.

Make sure the Python agent is already running (`python narwal_agent.py serve --config config.json`).

## What it does

- On every **live** message in the target group it extracts the text (conversation, extended text, or
  a media caption) and `POST`s `{"id": "<message id>", "text": "<message text>"}` to
  `AGENT_URL/whatsapp`.
- The group is matched by its exact **title** (`GROUP_TITLE`) or, more precisely, by its **JID**
  (`GROUP_JID`, ends with `@g.us`). If you rename the group, update `GROUP_TITLE` or use `GROUP_JID`.
- History-sync and protocol messages are ignored; only live `notify` messages are forwarded.

## Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `AGENT_URL` | Where the Python agent listens. Default `http://127.0.0.1:8799`. |
| `AGENT_TOKEN` | Optional shared secret. Must equal `config.agent.token` in the Python config if that is set. |
| `GROUP_TITLE` | The exact group subject to watch (e.g. `Gimli`). |
| `GROUP_JID` | The group JID; wins over `GROUP_TITLE` when set. |
| `AUTH_DIR` | Where linked-device credentials live. Default `./auth`. |

If you prefer not to use `--env-file`, set the variables in your shell and run `node index.js`.

## Notes and safety

- Baileys is an **unofficial** WhatsApp client and carries some ban risk. This bridge is read-only
  (`markOnlineOnConnect: false`, never sends), which minimizes it, but use a number you are
  comfortable linking.
- Never run two linked-device clients against the same `auth/` directory.
- Keep `bridge/auth/` private — it is a credential. It is git-ignored by default.
