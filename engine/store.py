"""Save/load games, picks and the board.

If SUPABASE_URL and SUPABASE_SERVICE_KEY are set → Supabase tables.
Otherwise → JSON files in ./data (handy for testing on your laptop).
"""
from __future__ import annotations

import json
import os
import urllib.error
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
    def load_orders(self):
        """Live orders that filled (what the order placer actually bet)."""
        return [o for o in self._read("bet_orders", []) if o.get("mode") == "live"
                and ((o.get("fill_count") or 0) > 0 or o.get("status") == "resting")]

    def load_placer_run(self):
        runs = [r for r in self._read("bet_log", []) if str(r.get("message", "")).startswith("run (")]
        return ({"at": runs[-1].get("ts"), "skips": (runs[-1].get("data") or {}).get("skips", [])} if runs else None)

    def save_picks(self, rows):
        cur = {r["key"]: r for r in self.load_picks()}
        cur.update({r["key"]: r for r in shape("picks", rows)})     # same columns as the Supabase table
        self._write("picks", list(cur.values()))

    def save_injury_log(self, rows):
        cur = {r["id"]: r for r in self._read("injury_log", [])}
        for r in rows:
            cur[r["id"]] = {**cur.get(r["id"], {"first_seen": r["last_seen"]}), **r}
        self._write("injury_log", list(cur.values()))
    def load_player_games(self):  return self._read("player_games", [])
    def save_player_games(self, rows):
        cur = {r["id"]: r for r in self.load_player_games()}
        cur.update({r["id"]: r for r in rows})
        self._write("player_games", list(cur.values()))

    def save_board(self, board):
        self._write("board", board)

    def save_feed(self, rows, now):
        old = {r["key"]: r for r in self._read("bet_feed", [])}
        keep = {r["key"] for r in rows}
        for k, r in old.items():
            if k not in keep:
                r.update(status="off", updated_at=now.isoformat())
        old.update({r["key"]: r for r in rows})
        self._write("bet_feed", list(old.values()))

    def get_config(self, key):
        return self._read("config", {}).get(key)


# Columns in supabase/schema.sql. Every row sent in one batch must have the same keys,
# and unknown keys are rejected, so rows are shaped to exactly these.
COLUMNS = {
    "games": ["id", "game_date", "tip_utc", "away", "home", "away_score", "home_score", "periods",
              "final", "home_spread", "total", "line_source", "line_books", "line_updated"],
    "picks": ["key", "game_id", "game_date", "tip_utc", "away", "home", "system", "bet", "side",
              "label", "line", "first_line", "first_seen", "last_checked", "active", "dropped_reason",
              "evidence", "kalshi", "result", "final_score", "graded_at", "meta"],
    "player_games": ["id", "game_id", "game_date", "team", "espn_id", "name", "min", "pts", "fgm", "fga",
                     "fg3m", "fg3a", "ftm", "fta", "orb", "drb", "ast", "stl", "blk", "tov", "pf", "pm",
                     "team_poss", "game_min"],
}


def shape(table, rows):
    cols = COLUMNS[table]
    return [{c: r.get(c) for c in cols} for r in rows]


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
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else None
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Supabase {method} {path} -> {e.code}: {e.read().decode()[:500]}") from None

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
        if rows: self._upsert("games", shape("games", rows), "id")

    def load_picks(self):  return self._all("picks")
    def save_picks(self, rows):
        if rows: self._upsert("picks", shape("picks", rows), "key")

    def load_orders(self):
        """Live orders that filled (what the order placer actually bet). Private table; service key only."""
        return self._req("GET", "/bet_orders?mode=eq.live&or=(fill_count.gt.0,status.eq.resting)&select=*"
                                "&order=created_at.desc") or []

    def load_placer_run(self):
        """The order placer's latest run summary: why each card bet was skipped (logged at least every 15 min)."""
        rows = self._req("GET", "/bet_log?message=like.run%20(*&select=ts,data&order=ts.desc&limit=1") or []
        return {"at": rows[0]["ts"], "skips": (rows[0].get("data") or {}).get("skips", [])} if rows else None

    def save_injury_log(self, rows):
        """Every official-report status we see, kept so Questionable/Doubtful play rates can be measured
        later (first_seen is kept on updates; last_seen moves)."""
        if rows: self._upsert("injury_log", rows, "id")
    def load_player_games(self):  return self._all("player_games")
    def save_player_games(self, rows):
        if rows: self._upsert("player_games", shape("player_games", rows), "id")

    def save_board(self, board):
        self._upsert("board", [{"id": 1, "data": board}], "id")

    def save_feed(self, rows, now):
        """Upsert today's card into bet_feed; anything no longer on the card is switched to 'off'."""
        if rows:
            self._upsert("bet_feed", rows, "key")
        keep = {r["key"] for r in rows}
        stale = [o["key"] for o in (self._req("GET", "/bet_feed?select=key&status=neq.off") or [])
                 if o["key"] not in keep]
        if stale:
            self._upsert("bet_feed", [{"key": k, "status": "off", "updated_at": now.isoformat()} for k in stale], "key")

    def get_config(self, key):
        """Private settings (e.g. the phone-alert channel). Table has no public read policy."""
        rows = self._req("GET", f"/config?key=eq.{key}&select=value") or []
        v = rows[0]["value"] if rows else None
        if isinstance(v, str) and v.strip()[:1] in "[{":      # the value column is text; JSON settings come back as strings
            v = json.loads(v)
        return v


def get_store():
    # Keys never contain whitespace; a copy from a wrapped line can insert a line break mid-key.
    url = "".join((os.environ.get("SUPABASE_URL") or "").split())
    key = "".join((os.environ.get("SUPABASE_SERVICE_KEY") or "").split())
    if key and not (key.startswith(("sb_secret_", "eyJ")) and key.isascii()):
        raise SystemExit(
            f"SUPABASE_SERVICE_KEY doesn't look like a Supabase secret key (length {len(key)}, "
            f"starts with sb_secret_: {key.startswith('sb_secret_')}). Re-paste it in GitHub → Settings → Secrets.")
    return SupabaseStore(url, key) if url and key else LocalStore(os.environ.get("DATA_DIR", "data"))
