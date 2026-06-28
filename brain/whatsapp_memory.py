import datetime
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from brain.memory import Memory


class WhatsAppMemory(Memory):
    """
    Dedicated file-backed memory for WhatsApp messages.
    This mirrors the useful Satele behavior while staying aligned with Kuun's
    simple JSONL memory backend.
    """

    def __init__(self, db_path="whatsapp_memory", silent=False):
        full_path = PROJECT_ROOT / "brain" / db_path
        if not silent:
            print(f"📱 Initializing WhatsApp Memory at {full_path} (file-based)...")
        full_path.mkdir(parents=True, exist_ok=True)
        self.store_file = full_path / "whatsapp_memory_log.jsonl"

    def log_message(self, text, role, sender="unknown", source="whatsapp", metadata=None):
        if not text:
            return

        meta = metadata or {}
        timestamp = meta.get("timestamp") or datetime.datetime.now().isoformat()
        clean_meta = {str(k): "" if v is None else str(v) for k, v in meta.items()}
        clean_meta.update(
            {
                "timestamp": timestamp,
                "role": role,
                "sender": sender,
                "source": source,
            }
        )

        msg_id_seed = f"{sender}_{timestamp}_{text[:80]}_{clean_meta.get('message_id', '')}"
        msg_id = hashlib.md5(msg_id_seed.encode("utf-8")).hexdigest()

        for record in self._read_records():
            if record.get("id") == msg_id:
                return

        record = {
            "id": msg_id,
            "document": str(text).strip(),
            "metadata": clean_meta,
        }
        with open(self.store_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_messages_in_range(self, days=7):
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        messages = []
        for record in self._read_records():
            meta = record.get("metadata", {})
            timestamp = meta.get("timestamp", "")
            if timestamp >= since:
                messages.append(
                    {
                        "text": record.get("document", ""),
                        "role": meta.get("role", "unknown"),
                        "sender": meta.get("sender", "unknown"),
                        "timestamp": timestamp,
                    }
                )
        messages.sort(key=lambda item: item["timestamp"])
        return messages

    def get_recent_chat_history(self, jid, limit=8):
        history = []
        for record in reversed(self._read_records()):
            meta = record.get("metadata", {})
            if meta.get("sender") == jid:
                history.append(
                    {
                        "role": meta.get("role", "unknown"),
                        "text": record.get("document", ""),
                        "timestamp": meta.get("timestamp", ""),
                    }
                )
                if len(history) >= limit:
                    break
        history.reverse()
        return history

    def get_seconds_since_last_manual_message(self, jid):
        for record in reversed(self._read_records()):
            meta = record.get("metadata", {})
            text = record.get("document", "")
            if meta.get("sender") != jid or meta.get("role") != "assistant":
                continue
            if "[AI Kuun]" in text:
                continue
            timestamp = meta.get("timestamp")
            if not timestamp:
                continue
            try:
                then = datetime.datetime.fromisoformat(timestamp)
                now = datetime.datetime.now(then.tzinfo) if then.tzinfo else datetime.datetime.now()
                return (now - then).total_seconds()
            except Exception:
                continue
        return 999999


if __name__ == "__main__":
    import sys

    memory = WhatsAppMemory(silent=True)
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(memory.get_count())
    else:
        print(f"Messages in DB: {memory.get_count()}")
