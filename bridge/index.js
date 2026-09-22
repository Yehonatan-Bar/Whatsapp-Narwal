// WhatsApp -> Narwal bridge.
//
// Connects to WhatsApp as a linked device (Baileys), watches ONE group (matched by its exact title,
// or by GROUP_JID), and forwards each new message's text to the Python agent over localhost
// (POST AGENT_URL/whatsapp {id, text}). The agent decides whether the text is a clean command and
// drives the robot. This bridge never sends WhatsApp messages and never marks anything read.
//
// Config comes from environment variables (see .env.example). Pair once by scanning the QR code
// printed on first run; the linked-device credentials are stored in ./auth (git-ignored).

import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'
import qrcode from 'qrcode-terminal'

const AGENT_URL = (process.env.AGENT_URL || 'http://127.0.0.1:8799').replace(/\/$/, '')
const AGENT_TOKEN = process.env.AGENT_TOKEN || ''
const GROUP_TITLE = process.env.GROUP_TITLE || ''
const GROUP_JID = process.env.GROUP_JID || ''
const AUTH_DIR = process.env.AUTH_DIR || './auth'

if (!GROUP_TITLE && !GROUP_JID) {
  console.error('Set GROUP_TITLE (the exact group subject) or GROUP_JID in the environment (.env).')
  process.exit(1)
}

const log = (...args) => console.log(new Date().toISOString(), ...args)

// Cache group jid -> subject so we can match by title without a metadata fetch per message.
const subjectCache = new Map()

function messageText(message) {
  const content = message?.message
  if (!content) return ''
  return (
    content.conversation ||
    content.extendedTextMessage?.text ||
    content.imageMessage?.caption ||
    content.videoMessage?.caption ||
    ''
  )
}

async function groupMatches(sock, jid) {
  if (!jid.endsWith('@g.us')) return false
  if (GROUP_JID) return jid === GROUP_JID
  if (subjectCache.has(jid)) return subjectCache.get(jid) === GROUP_TITLE
  try {
    const metadata = await sock.groupMetadata(jid)
    subjectCache.set(jid, metadata.subject)
    return metadata.subject === GROUP_TITLE
  } catch (error) {
    log('could not read group metadata for', jid, String(error))
    return false
  }
}

async function forward(id, text) {
  try {
    const response = await fetch(`${AGENT_URL}/whatsapp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(AGENT_TOKEN ? { 'X-Auth-Token': AGENT_TOKEN } : {}) },
      body: JSON.stringify({ id, text }),
    })
    const body = await response.json().catch(() => ({}))
    log('forwarded', JSON.stringify({ id, text }), '->', response.status, JSON.stringify(body))
  } catch (error) {
    log('failed to reach the agent at', AGENT_URL, String(error))
  }
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion()
  const sock = makeWASocket({ version, auth: state, markOnlineOnConnect: false, printQRInTerminal: false })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update
    if (qr) {
      console.log('\nScan this QR in WhatsApp > Settings > Linked devices:\n')
      qrcode.generate(qr, { small: true })
    }
    if (connection === 'open') log('connected to WhatsApp; watching', GROUP_JID || `group titled "${GROUP_TITLE}"`)
    if (connection === 'close') {
      const status = lastDisconnect?.error?.output?.statusCode
      const loggedOut = status === DisconnectReason.loggedOut
      log('connection closed', status ? `(status ${status})` : '', loggedOut ? '- logged out; delete ./auth and re-pair' : '- reconnecting')
      if (!loggedOut) start()
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return // live messages only; ignore history sync
    for (const message of messages) {
      const jid = message.key?.remoteJid
      if (!jid || message.message?.protocolMessage) continue
      if (!(await groupMatches(sock, jid))) continue
      const text = messageText(message).trim()
      if (!text) continue
      await forward(message.key.id, text)
    }
  })
}

start().catch((error) => {
  console.error('bridge failed to start:', error)
  process.exit(1)
})
