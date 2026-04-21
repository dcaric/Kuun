import { makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import pino from 'pino';
import axios from 'axios';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import qrcode from 'qrcode-terminal';
import express from 'express';
import fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const FASTAPI_PORT = process.env.FASTAPI_PORT || '8100';
const WA_API_PORT = Number(process.env.WA_API_PORT || '8101');
const WA_API_BIND_HOST = process.env.WA_API_BIND_HOST || '127.0.0.1';
const SERVER_URL = process.env.BRIDGE_SERVER_URL || `http://localhost:${FASTAPI_PORT}/webhook/message`;
const BOT_TRIGGER = (process.env.BOT_TRIGGER || 'kuun').trim();
const BRIDGE_SECRET_KEY = process.env.BRIDGE_SECRET_KEY || '';
const AUTH_DIR = path.resolve(__dirname, '.kuun_cache');
const ALLOWED_NUMBERS_FILE = path.resolve(__dirname, 'allowed_numbers.txt');

const logger = pino({ level: 'silent' });

function getBrowserProfile() {
  const platform = os.platform();
  if (platform === 'linux') return Browsers.ubuntu('Desktop');
  if (platform === 'win32') return Browsers.windows('Desktop');
  return Browsers.macOS('Desktop');
}

function textFromMsg(msg) {
  const m = msg?.message || {};
  if (m.conversation) return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;
  if (m.imageMessage?.caption) return m.imageMessage.caption;
  if (m.videoMessage?.caption) return m.videoMessage.caption;
  return '';
}

function loadAllowedNumbers() {
  try {
    if (!fs.existsSync(ALLOWED_NUMBERS_FILE)) {
      fs.writeFileSync(ALLOWED_NUMBERS_FILE, '');
      return new Set();
    }

    const raw = fs.readFileSync(ALLOWED_NUMBERS_FILE, 'utf-8');
    const nums = raw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.replace(/\D/g, ''))
      .filter(Boolean);

    return new Set(nums);
  } catch (err) {
    console.error('⚠️ Failed to read allowlist:', err.message);
    return new Set();
  }
}

function isAllowedSender(jid, allowlist) {
  if (!allowlist || allowlist.size === 0) {
    // Security-first: empty allowlist means deny all.
    return false;
  }

  if (!jid) return false;

  const exact = jid.trim();
  const bare = exact.split('@')[0] || '';
  const bareDigits = bare.replace(/\D/g, '');

  return allowlist.has(exact) || allowlist.has(bare) || allowlist.has(bareDigits);
}

async function startWhatsApp() {
  console.log(`🚀 Starting WhatsApp bridge (trigger: ${BOT_TRIGGER})`);

  const { version } = await fetchLatestBaileysVersion();
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: getBrowserProfile(),
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('\n📷 Scan this QR code:\n');
      qrcode.generate(qr, { small: true });
    }

    if (connection === 'close') {
      const shouldReconnect =
        lastDisconnect?.error instanceof Boom
          ? lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut
          : true;
      console.log('❌ WhatsApp closed. Reconnecting:', shouldReconnect);
      if (shouldReconnect) setTimeout(() => startWhatsApp(), 5000);
    } else if (connection === 'open') {
      console.log('✅ WhatsApp connected');
      global.whatsappSock = sock;
    }
  });

  sock.ev.on('messages.upsert', async ({ type, messages }) => {
    if (type !== 'notify' || !messages) return;

    for (const msg of messages) {
      if (!msg?.message) continue;

      const jid = msg.key?.remoteJid;
      const fromMe = !!msg.key?.fromMe;
      const text = (textFromMsg(msg) || '').trim();

      if (!jid || !text) continue;

      const triggerRegex = new RegExp(`\\b${BOT_TRIGGER}\\b`, 'i');
      const isTriggered = triggerRegex.test(text);
      const isBotLike = text.startsWith('🤖') || text.startsWith('♊') || text.startsWith('📊');

      if (fromMe && (!isTriggered || isBotLike)) continue;
      if (!isTriggered) continue;

      // Enforce allowlist for external senders.
      if (!fromMe) {
        const allowlist = loadAllowedNumbers();
        if (!isAllowedSender(jid, allowlist)) {
          console.log(`🚫 Ignored non-whitelisted sender: ${jid}`);
          continue;
        }
      }

      try {
        await axios.post(SERVER_URL, {
          text,
          sender: jid,
          source: 'whatsapp',
        }, {
          headers: { Authorization: `Bearer ${BRIDGE_SECRET_KEY}` },
        });

        await sock.sendMessage(jid, {
          text: `🤖 [${BOT_TRIGGER}] Working...`,
        });
      } catch (err) {
        console.error('❌ Forward failed:', err.message);
      }
    }
  });
}

const app = express();
app.use(express.json());

app.post('/send', async (req, res) => {
  const authHeader = req.headers.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice('Bearer '.length) : '';
  if (!token || token !== BRIDGE_SECRET_KEY) {
    return res.status(403).json({ error: 'Forbidden' });
  }

  const { to, text } = req.body;
  if (!global.whatsappSock || !to || !text) {
    return res.status(500).json({ error: 'WhatsApp not connected or missing params' });
  }

  let jid = to;
  if (!jid.includes('@')) jid += '@s.whatsapp.net';

  try {
    await global.whatsappSock.sendMessage(jid, { text });
    return res.json({ status: 'sent' });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

app.listen(WA_API_PORT, WA_API_BIND_HOST, () => {
  console.log(`📡 WA send API running on http://${WA_API_BIND_HOST}:${WA_API_PORT}`);
});

startWhatsApp();
