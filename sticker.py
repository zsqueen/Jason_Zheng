"""Sticker search and send for nekowhale kit."""

import json
import random
from pathlib import Path

STICKER_DIR = Path(__file__).parent / "_stickers"
INDEX_FILE = STICKER_DIR / "nekowhale.json"
PACKS_DIR = STICKER_DIR / "packs"


class StickerKit:
    def __init__(self):
        self.stickers = []
        self.emotions = []
        self.packs = []
        self._load()

    def _load(self):
        if not INDEX_FILE.exists():
            return
        try:
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            self.packs = data.get("packs", [])
            self.emotions = data.get("emotions", [])
            self.stickers = data.get("stickers", [])
        except Exception:
            pass

    def _local_path(self, sticker):
        sid = sticker.get("id", "")
        pack, _, name = sid.partition("/")
        if not pack or not name:
            return ""
        path = PACKS_DIR / pack / f"{name}.gif"
        return str(path) if path.exists() else ""

    def search(self, query, limit=5):
        if not query or not self.stickers:
            return []
        q = query.lower()
        scored = []
        for s in self.stickers:
            score = 0
            emotion = s.get("emotion", "")
            tags = s.get("tags", [])
            desc = s.get("desc", "")
            use = s.get("use", "")
            if q in emotion.lower():
                score += 10
            for tag in tags:
                if q in tag.lower():
                    score += 5
            if q in desc.lower() or q in use.lower():
                score += 2
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        seen = set()
        results = []
        for _, s in scored:
            sid = s.get("id")
            if sid not in seen:
                seen.add(sid)
                results.append(s)
                if len(results) >= limit:
                    break
        return results

    def pick_by_emotion(self, emotion):
        matches = [s for s in self.stickers if s.get("emotion") == emotion]
        if not matches:
            matches = self.search(emotion, limit=10)
        if not matches:
            return None
        return random.choice(matches)

    def get_sticker_path(self, sticker):
        return self._local_path(sticker)

    def format_for_qq(self, sticker):
        path = self._local_path(sticker)
        if path:
            return f"![sticker]({path})"
        return ""

    def list_emotions(self):
        return list(self.emotions)


_kit = None


def get_kit():
    global _kit
    if _kit is None:
        _kit = StickerKit()
    return _kit


def search_stickers(query, limit=5):
    return get_kit().search(query, limit)


def pick_sticker(emotion):
    return get_kit().pick_by_emotion(emotion)


def format_sticker(sticker):
    return get_kit().format_for_qq(sticker)


def get_sticker_path(sticker):
    return get_kit().get_sticker_path(sticker)
