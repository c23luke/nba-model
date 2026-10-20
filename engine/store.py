"""Save/load games, picks and the board.

If SUPABASE_URL and SUPABASE_SERVICE_KEY are set → Supabase tables.
Otherwise → JSON files in ./data (handy for testing on your laptop).
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


class LocalStore:
    def __init__(self, folder="data"):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _read(self, name, default):
        p = self.dir / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else default

    def _write(self, name, obj):
        (self.dir / f"{name}.json").write_text(json.dumps(obj, indent=1, default=str))

    def load_games(self):  return self._read("games", [])
    def save_games(self, rows):
        cur = {r["id"]: r for r in self.load_games()}
        cur.update({r["id"]: r for r in rows})
        self._write("games", list(cur.values()))

    def load_picks(self):  return self._read("picks", [])
    def save_picks(self, rows):
        cur = {r["key"]: r for r in self.load_picks()}
        cur.update({r["key"]: r for r in rows})
        self._write("picks", list(cur.values()))

    def save_board(self, board):
        self._write("board", board)


class SupabaseStore:
    def __init__(self, url, key):
        self.url = url.rstrip("/") + "/rest/v1"
        self.h = {"apikey": key, "Content-Type": "application/json"}
        if not key.startswith("sb_"):          # old-style JWT keys also go in Authorization
            self.h["Authorization"] = f"Bearer {key}"

    def _req(self, method, path, body=None, extra=None):
        data = None if body is None else json.dumps(body, default=str).encode()
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={**self.h, **(extra or {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else None

    def _all(self, table):
        rows, start = [], 0
        while True:
            chunk = self._req("GET", f"/{table}?select=*", extra={"Range": f"{start}-{start + 999}"})
            rows += chunk
            if len(chunk) < 1000:
                return rows
            start += 1000

    def _upsert(self, table, rows, conflict):
        for i in range(0, len(rows), 500):
            self._req("POST", f"/{table}?on_conflict={conflict}", rows[i:i + 500],
                      {"Prefer": "resolution=merge-duplicates,return=minimal"})

    def load_games(self):  return self._all("games")
    def save_games(self, rows):
        if rows: self._upsert("games", rows, "id")

    def load_picks(self):  return self._all("picks")
    def save_picks(self, rows):
        if rows: self._upsert("picks", rows, "key")

    def save_board(self, board):
        self._upsert("board", [{"id": 1, "data": board}], "id")


def get_store():
    # .strip(): pasted secrets often carry a trailing newline or space
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_KEY") or "").strip()
    if key and (any(c in key for c in "\r\n\t ") or not key.isascii()):
        lines = [ln.strip() for ln in key.splitlines() if ln.strip()]
        raise SystemExit(
            "SUPABASE_SERVICE_KEY looks mis-pasted: "
            f"{len(lines)} non-empty line(s), lengths {[len(ln) for ln in lines]}, "
            f"starts with sb_secret_: {[ln.startswith('sb_secret_') for ln in lines]}, "
            f"plain ASCII: {key.isascii()}. Re-paste just the one key in GitHub → Settings → Secrets.")
    return SupabaseStore(url, key) if url and key else LocalStore(os.environ.get("DATA_DIR", "data"))
