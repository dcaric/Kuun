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
const HUMAN_INTERVENTION_TIMEOUT = Number(process.env.HUMAN_INTERVENTION_TIMEOUT || '300');
const ALLOW_FROMME_SYSTEM = ['1', 'true', 'on', 'yes'].includes(
  String(process.env.ALLOW_FROMME_SYSTEM || 'true').toLowerCase()
);
const AUTH_DIR = path.resolve(__dirname, '.kuun_cache');
const ALLOWED_NUMBERS_FILE = path.resolve(__dirname, 'allowed_numbers.txt');
const WHITELIST_FILE = path.resolve(__dirname, 'whitelist.json');
const WHITELIST_GROUPS_FILE = path.resolve(__dirname, 'whitelist_groups.json');
const GROUP_CACHE_FILE = path.resolve(__dirname, 'group_cache.json');
const CONTACTS_CACHE_FILE = path.resolve(__dirname, 'contacts_cache.json');
const TRUSTED_NAMES = new Set(
  (process.env.TRUSTED_NAMES || 'Dario,Dario Caric')
    .split(',')
    .map((n) => n.trim().toLowerCase())
    .filter(Boolean)
);

const logger = pino({ level: 'silent' });
const groupNameCache = new Map();
const contactCache = new Map();
const lastManualMessageAt = new Map();

if (fs.existsSync(GROUP_CACHE_FILE)) {
  try {
    const data = JSON.parse(fs.readFileSync(GROUP_CACHE_FILE, 'utf8'));
    Object.entries(data).forEach(([jid, name]) => groupNameCache.set(jid, name));
  } catch (err) {
    console.error('⚠️ Failed to read group cache:', err.message);
  }
}

function saveGroupCache() {
  try {
    const data = Object.fromEntries(groupNameCache);
    fs.writeFileSync(GROUP_CACHE_FILE, JSON.stringify(data, null, 2));
  } catch (err) {
    console.error('⚠️ Failed to save group cache:', err.message);
  }
}

if (fs.existsSync(CONTACTS_CACHE_FILE)) {
  try {
    const data = JSON.parse(fs.readFileSync(CONTACTS_CACHE_FILE, 'utf8'));
    Object.entries(data).forEach(([jid, name]) => contactCache.set(jid, name));
  } catch (err) {
    console.error('⚠️ Failed to read contacts cache:', err.message);
  }
}

function saveContactCache() {
  try {
    const data = Object.fromEntries(contactCache);
    fs.writeFileSync(CONTACTS_CACHE_FILE, JSON.stringify(data, null, 2));
  } catch (err) {
    console.error('⚠️ Failed to save contacts cache:', err.message);
  }
}

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

function isGroupJid(jid) {
  return typeof jid === 'string' && jid.endsWith('@g.us');
}

function normalizeJidUser(jid = '') {
  return String(jid).split('@')[0].split(':')[0];
}

function isReplyToBotMessage(msg, sock) {
  const ext = msg?.message?.extendedTextMessage;
  const ctx = ext?.contextInfo;
  if (!ctx) return false;

  // When available, participant points to the author of the quoted message.
  const quotedParticipant = normalizeJidUser(ctx.participant || '');
  const botUser = normalizeJidUser(sock?.user?.id || '');
  if (quotedParticipant && botUser && quotedParticipant === botUser) return true;

  return false;
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

function isSystemUser(jid, fromMe, allowlist) {
  if (fromMe && ALLOW_FROMME_SYSTEM) return true;
  return isAllowedSender(jid, allowlist);
}

function loadWhitelist() {
  try {
    if (!fs.existsSync(WHITELIST_FILE)) return {};
    const data = JSON.parse(fs.readFileSync(WHITELIST_FILE, 'utf8'));
    if (Array.isArray(data)) {
      const mapped = {};
      data.forEach((v) => {
        const key = String(v || '').trim();
        if (key) mapped[key] = key;
      });
      return mapped;
    }
    if (data && typeof data === 'object') return data;
  } catch (err) {
    console.error('⚠️ Failed to read whitelist:', err.message);
  }
  return {};
}

function isTrustedSender(jid, pushName, allowlist) {
  const normalizedPushName = String(pushName || '').trim().toLowerCase();
  const phoneId = normalizeJidUser(jid || '');
  const whitelist = loadWhitelist();
  const addressBookName = String(contactCache.get(jid) || '').trim().toLowerCase();

  for (const [keyRaw, valRaw] of Object.entries(whitelist)) {
    const key = String(keyRaw || '').trim().toLowerCase();
    const value = String(valRaw || '').trim().toLowerCase();
    if (!key && !value) continue;

    if (key && (jid.toLowerCase() === key || phoneId === key || jid.toLowerCase().startsWith(key))) return true;
    if (value && normalizedPushName && (normalizedPushName.includes(value) || value.includes(normalizedPushName))) return true;
    if (value && addressBookName && (addressBookName.includes(value) || value.includes(addressBookName))) return true;
    if (key && normalizedPushName && (normalizedPushName.includes(key) || key.includes(normalizedPushName))) return true;
  }

  return isAllowedSender(jid, allowlist) || (!!normalizedPushName && TRUSTED_NAMES.has(normalizedPushName));
}

function markManualMessage(jid) {
  if (!jid) return;
  lastManualMessageAt.set(jid, Date.now());
}

function hasRecentManualIntervention(jid) {
  if (!jid) return false;
  const ts = lastManualMessageAt.get(jid);
  if (!ts) return false;
  const timeoutMs = Math.max(0, HUMAN_INTERVENTION_TIMEOUT) * 1000;
  return (Date.now() - ts) < timeoutMs;
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

  sock.ev.on('contacts.set', ({ contacts }) => {
    contacts.forEach((c) => {
      if (c.id && (c.name || c.verifiedName)) {
        contactCache.set(c.id, c.name || c.verifiedName);
      }
    });
    saveContactCache();
  });

  sock.ev.on('contacts.upsert', (contacts) => {
    contacts.forEach((c) => {
      if (c.id && (c.name || c.verifiedName)) {
        contactCache.set(c.id, c.name || c.verifiedName);
      }
    });
    saveContactCache();
  });

  sock.ev.on('contacts.update', (updates) => {
    updates.forEach((c) => {
      if (c.id && (c.name || c.verifiedName)) {
        contactCache.set(c.id, c.name || c.verifiedName);
      }
    });
    saveContactCache();
  });

  sock.ev.on('chats.set', ({ chats }) => {
    chats.forEach((c) => {
      if (c.id && c.name && !isGroupJid(c.id)) {
        contactCache.set(c.id, c.name);
      }
    });
    saveContactCache();
  });

  sock.ev.on('chats.upsert', (chats) => {
    chats.forEach((c) => {
      if (c.id && c.name && !isGroupJid(c.id)) {
        contactCache.set(c.id, c.name);
      }
    });
    saveContactCache();
  });

  sock.ev.on('messages.upsert', async ({ type, messages }) => {
    if (type !== 'notify' || !messages) return;

    for (const msg of messages) {
      if (!msg?.message) continue;

      const jid = msg.key?.remoteJid;
      const fromMe = !!msg.key?.fromMe;
      const senderName = msg.pushName || (fromMe ? 'Kuun Owner' : (jid || '').split('@')[0]);
      const text = (textFromMsg(msg) || '').trim();

      if (!jid || !text) continue;

      const triggerRegex = new RegExp(`\\b${BOT_TRIGGER}\\b`, 'i');
      const isTriggered = triggerRegex.test(text);
      const isBotLike = text.startsWith('🤖') || text.startsWith('♊') || text.startsWith('📊');
      const isGroup = isGroupJid(jid);
      let isReplyToMe = isReplyToBotMessage(msg, sock);
      let isWhitelistedGroup = false;
      const allowlist = loadAllowedNumbers();
      const isSystem = isSystemUser(jid, fromMe, allowlist);
      const trustedSender = isSystem || isTrustedSender(jid, senderName, allowlist);
      const isRecentOutboundEcho = fromMe && isBotLike;
      const allowSelfConversation = false;

      // Track real manual outgoing messages as human intervention.
      if (fromMe && !isTriggered && !isBotLike) {
        markManualMessage(jid);
      }

      if (fromMe && !allowSelfConversation && (!isTriggered || isRecentOutboundEcho)) continue;

      if (isGroup) {
        if (!isReplyToMe && sock.user && sock.user.id) {
          const myNumber = normalizeJidUser(sock.user.id);
          const participant = normalizeJidUser(msg.message?.extendedTextMessage?.contextInfo?.participant || '');
          if (participant && myNumber && participant === myNumber) {
            isReplyToMe = true;
          }
        }

        let groupName = groupNameCache.get(jid);
        if (!groupName) {
          try {
            const metadata = await sock.groupMetadata(jid);
            groupName = metadata?.subject || '';
            if (groupName) {
              groupNameCache.set(jid, groupName);
              saveGroupCache();
            }
          } catch (_) {
            // ignore metadata lookup failures
          }
        }

        if (fs.existsSync(WHITELIST_GROUPS_FILE)) {
          try {
            const groups = JSON.parse(fs.readFileSync(WHITELIST_GROUPS_FILE, 'utf8'));
            if (Array.isArray(groups)) {
              const groupsLower = groups.map((g) => String(g).toLowerCase());
              const jidCore = jid.split('@')[0];
              if (
                groups.includes(jid) ||
                groups.includes(jidCore) ||
                (groupName && groupsLower.includes(groupName.toLowerCase()))
              ) {
                isWhitelistedGroup = true;
              }
            }
          } catch (err) {
            console.error('⚠️ Failed to read group whitelist:', err.message);
          }
        }
      }

      if (isGroup && !isReplyToMe && !isWhitelistedGroup) {
        console.log(`👥 Ignoring group message without direct reply from ${senderName}`);
        continue;
      }

      const finalTriggered = isSystem && isTriggered;
      const taskMode = finalTriggered ? 'agent' : (trustedSender ? 'trusted_chat' : 'public_chat');

      if (!isSystem && isTriggered) {
        continue;
      }

      // If user manually took over this chat recently, keep Revan/Kuun silent for a while.
      if (!fromMe && taskMode === 'trusted_chat' && hasRecentManualIntervention(jid)) {
        continue;
      }

      try {
        await axios.post(SERVER_URL, {
          text,
          sender: jid,
          pushName: senderName,
          source: 'whatsapp',
          fromMe,
          mode: taskMode,
        }, {
          headers: { Authorization: `Bearer ${BRIDGE_SECRET_KEY}` },
        });

        if (finalTriggered) {
          await sock.sendMessage(jid, {
            text: `🤖 [${BOT_TRIGGER}] Working...`,
          });
        }
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

  // Final send-time authorization check: never deliver to unauthorized recipients.
  const allowlist = loadAllowedNumbers();
  if (!isAllowedSender(jid, allowlist)) {
    return res.status(403).json({ error: 'Recipient not authorized' });
  }

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
