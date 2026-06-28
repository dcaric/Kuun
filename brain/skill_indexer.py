#!/usr/bin/env python3
import json
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / ".agent" / "skills"
VAULT_FILE = PROJECT_ROOT / "brain" / "skills_vault.json"


class SkillIndexer:
    """
    Lightweight Kuun skill indexer.
    Satele used embeddings here; Kuun keeps a dependency-free searchable JSON
    index so WhatsApp/Codex workflows can still discover local skill notes.
    """

    def __init__(self, project_root: Path | str = PROJECT_ROOT):
        self.project_root = Path(project_root)
        self.skills_dir = self.project_root / ".agent" / "skills"
        self.vault_file = self.project_root / "brain" / "skills_vault.json"
        self.skills = self.load()

    def load(self) -> dict:
        if not self.vault_file.exists():
            return {}
        try:
            data = json.loads(self.vault_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save(self):
        self.vault_file.parent.mkdir(parents=True, exist_ok=True)
        self.vault_file.write_text(json.dumps(self.skills, indent=2, ensure_ascii=False), encoding="utf-8")

    def rebuild(self) -> dict:
        skills = {}
        if self.skills_dir.exists():
            for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
                text = skill_file.read_text(encoding="utf-8", errors="ignore").strip()
                name = skill_file.parent.name
                title = text.splitlines()[0].lstrip("# ").strip() if text else name
                skills[name] = {
                    "name": title or name,
                    "path": str(skill_file.relative_to(self.project_root)),
                    "text": text[:8000],
                }
        self.skills = skills
        self.save()
        return skills

    def search(self, query: str, limit: int = 5) -> list[dict]:
        query_lower = (query or "").lower()
        results = []
        for key, item in self.skills.items():
            haystack = f"{item.get('name', '')}\n{item.get('text', '')}".lower()
            score = SequenceMatcher(None, query_lower, haystack[:4000]).ratio()
            if query_lower and query_lower in haystack:
                score += 1.0
            results.append({"key": key, "score": score, **item})
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]


def get_skill_indexer(project_root=PROJECT_ROOT):
    return SkillIndexer(project_root)


if __name__ == "__main__":
    import sys

    indexer = SkillIndexer()
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        print(json.dumps(indexer.rebuild(), indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1:
        print(json.dumps(indexer.search(" ".join(sys.argv[1:])), indent=2, ensure_ascii=False))
    else:
        print(f"{len(indexer.skills)} skills indexed")
