import datetime
import json
import os
import threading
from pathlib import Path
from difflib import SequenceMatcher
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Memory:
    """
    Persistent memory manager for Kuun.
    Logs interactions (commands, responses, messages) to a JSON Lines file
    to avoid compilation/linking crashes of ChromaDB on macOS.
    """

    def __init__(self, db_path="kuun_memory", silent=False):
        full_path = PROJECT_ROOT / "brain" / db_path
        self._lock = threading.Lock()

        if not silent:
            print(f"🧠 Initializing Memory at {full_path} (file-based)...")

        full_path.mkdir(parents=True, exist_ok=True)
        self.store_file = full_path / "memory_log.jsonl"

    def _read_records(self) -> list[dict]:
        if not self.store_file.exists():
            return []

        records = []
        try:
            with open(self.store_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            return []
        return records

    def get_count(self) -> int:
        return len(self._read_records())

    def remember(self, text: str, role: str = "user", metadata: dict | None = None):
        if not text:
            return

        meta = metadata or {}
        clean_meta = {str(k): "" if v is None else str(v) for k, v in meta.items()}
        clean_meta["timestamp"] = datetime.datetime.now().isoformat()
        clean_meta["role"] = role

        record = {
            "id": str(uuid.uuid4()),
            "document": text.strip(),
            "metadata": clean_meta,
        }

        with self._lock:
            with open(self.store_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recall_recent(self, n_results: int = 15) -> list[str]:
        try:
            records = self._read_records()
            if not records:
                return []

            # Sort chronologically by timestamp (newest last or newest first? Let's check Satele:
            # Satele does: sort reverse=True (newest first), then top_n, then reverses them to show oldest first in context)
            paired = []
            for record in records:
                meta = record.get("metadata", {})
                paired.append(
                    {
                        "doc": record.get("document", ""),
                        "meta": meta,
                        "ts": meta.get("timestamp", ""),
                    }
                )

            paired.sort(key=lambda x: x["ts"], reverse=True)
            top_n = paired[:n_results]

            context_lines = []
            for item in top_n:
                ts = item["ts"][:16].replace("T", " ")
                role = item["meta"].get("role", "unknown")
                sender = item["meta"].get("sender", "system")
                context_lines.append(f"[{ts}] ({role}) sender:{sender} -> {item['doc']}")

            context_lines.reverse()
            return context_lines
        except Exception:
            return []

    def recall(self, query_text: str, n_results: int = 5) -> list[str]:
        if not query_text:
            return []

        try:
            records = self._read_records()
            if not records:
                return []

            scored = []
            query_lower = query_text.lower()
            for record in records:
                doc = record.get("document", "")
                meta = record.get("metadata", {})
                doc_lower = doc.lower()
                score = SequenceMatcher(None, query_lower, doc_lower).ratio()
                if query_lower in doc_lower:
                    score += 1.0
                scored.append((score, doc, meta))

            scored.sort(key=lambda item: item[0], reverse=True)
            pairs = [(doc, meta) for score, doc, meta in scored[:n_results] if doc]

            context_lines = []
            for doc, meta in pairs:
                ts = meta.get("timestamp", "")[:16].replace("T", " ")
                role = meta.get("role", "unknown")
                sender = meta.get("sender", "system")
                context_lines.append(f"[{ts}] ({role}) sender:{sender} -> {doc}")
            return context_lines
        except Exception:
            return []


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        m = Memory(silent=True)
        print(m.get_count())
    else:
        m = Memory()
        print(f"Messages in DB: {m.get_count()}")
