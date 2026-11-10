"""PROPS DESK — tracking only (Caden 2026-11-10: "player props looking at guys ... only playing like 10 min").

When a rotation player is ruled out and he played his team's last game (fresh news), his minutes go to teammates.
The players model already re-fits every team to 240 minutes with tonight's absences (Player.minutes). This desk:
  1. finds teammates whose projected minutes tonight are 5+ above their season average,
  2. projects their points = tonight's minutes x their points per minute over their last 10 games (60+ minutes of sample),
  3. reads the books' points line for them (The Odds API, one credit per game, only for games with such news,
     at most every 30 minutes per game),
  4. logs a PAPER bet on the over when our projection is 3+ points above the line,
  5. keeps reading that line until tip (CLV = the last line before tip minus ours), and grades it from the box score.
Nothing is ever bet from this. Stored in bet_state "props_desk"; shown on the site's Testing tab.
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .personnel import norm

GAIN_MIN = 5.0          # minutes above his average before we look
EDGE_PTS = 3.0          # projection minus the line before a paper bet
SAMPLE_MIN = 60         # minutes of recent sample needed for points per minute
REFETCH = timedelta(minutes=30)
EVENTS = "https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={key}"
PROPS = ("https://api.the-odds-api.com/v4/sports/basketball_nba/events/{eid}/odds?apiKey={key}"
         "&regions=us&markets=player_points&oddsFormat=american")


def scoring(box_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(team, normalised name) -> {"ppm", "min", "mpg"} over the player's last 10 games with minutes."""
    by = defaultdict(list)
    for r in box_rows:
        if (r.get("min") or 0) > 0:
            by[(r["team"], norm(r.get("name") or ""))].append(r)
    out = {}
    for k, rs in by.items():
        rs = sorted(rs, key=lambda r: str(r.get("game_date")))[-10:]
        m = sum(r["min"] for r in rs)
        if m >= SAMPLE_MIN:
            out[k] = {"ppm": sum(r.get("pts") or 0 for r in rs) / m, "min": m, "mpg": m / len(rs)}
    return out


def candidates(game, reads: dict, rotations: dict, score: dict) -> list[dict]:
    """Teammates of a freshly-out rotation player whose minutes tonight jump 5+ above their recent average."""
    out = []
    for team in (game.away, game.home):
        r = reads.get(team)
        rot = rotations.get(team) or {}
        if r is None:
            continue
        fresh = [rot[norm(p.name)]["name"] for p in r.players if p.status == "out"
                 and norm(p.name) in rot and rot[norm(p.name)]["last"]]
        if not fresh:
            continue
        for p in r.players:
            if p.status == "out":
                continue
            s = score.get((team, norm(p.name)))
            if not s or p.minutes - s["mpg"] < GAIN_MIN:
                continue
            out.append({"game_id": game.id, "team": team, "player": p.name, "because": fresh,
                        "mpg": round(s["mpg"], 1), "proj_min": round(p.minutes, 1),
                        "proj_pts": round(p.minutes * s["ppm"], 1), "dtd": p.status == "day-to-day"})
    return out


def parse_props(js: dict) -> dict[str, dict]:
    """normalised player -> {"line": median points line, "over": median over price, "books": n} across books."""
    lines = defaultdict(list)
    overs = defaultdict(list)
    for bk in js.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            if mk.get("key") != "player_points":
                continue
            for o in mk.get("outcomes") or []:
                if o.get("name") == "Over" and o.get("point") is not None:
                    k = norm(o.get("description") or "")
                    lines[k].append(float(o["point"]))
                    overs[k].append(int(o["price"]))
    return {k: {"line": statistics.median(v), "over": int(statistics.median(overs[k])), "books": len(v)}
            for k, v in lines.items()}


def grade(bet: dict, box_rows: list[dict]) -> str | None:
    pts = next((r.get("pts") for r in box_rows if r.get("game_id") == bet["game_id"]
                and norm(r.get("name") or "") == norm(bet["player"])), None)
    if pts is None:
        return None
    return "W" if pts > bet["line"] else "L" if pts < bet["line"] else "P"


def step(state: dict, now: datetime, games: list, reads: dict, rotations: dict, box_rows: list[dict],
         fetch_props, finals: dict) -> dict:
    """One pass. state: {"bets": [...], "fetched": {game_id: iso}, "events": {game_id: event_id}}.
    fetch_props(game) -> parsed props {player: {...}} or None. finals: game_id -> final game row."""
    state = {"bets": list(state.get("bets") or []), "fetched": dict(state.get("fetched") or {})}
    score = scoring(box_rows)
    open_games = {b["game_id"] for b in state["bets"] if not b.get("result")}
    for g in games:
        tip = datetime.fromisoformat(str(g.tip_utc).replace("Z", "+00:00")) if g.tip_utc else None
        if not tip or tip <= now or tip - now > timedelta(hours=14):
            continue
        cands = candidates(g, reads, rotations, score)
        if not cands and g.id not in open_games:
            continue
        last = state["fetched"].get(g.id)
        if last and now - datetime.fromisoformat(last) < REFETCH:
            continue
        props = fetch_props(g)
        state["fetched"][g.id] = now.isoformat()
        if not props:
            continue
        for b in state["bets"]:                       # keep the line moving toward tip: CLV
            if b["game_id"] == g.id and not b.get("result"):
                p = props.get(norm(b["player"]))
                if p:
                    b["last_line"], b["last_over"], b["last_at"] = p["line"], p["over"], now.isoformat()
        have = {(b["game_id"], norm(b["player"])) for b in state["bets"]}
        for c in cands:
            p = props.get(norm(c["player"]))
            if not p or (g.id, norm(c["player"])) in have or c["dtd"]:
                continue
            if c["proj_pts"] - p["line"] >= EDGE_PTS:
                state["bets"].append({**c, "at": now.isoformat(), "line": p["line"], "over": p["over"],
                                      "books": p["books"], "last_line": p["line"], "last_over": p["over"],
                                      "tip_utc": g.tip_utc})
    for b in state["bets"]:
        if not b.get("result") and (finals.get(b["game_id"]) or {}).get("final"):
            b["result"] = grade(b, box_rows)
        if b.get("last_line") is not None:
            b["clv"] = round(b["last_line"] - b["line"], 1)      # + = the line rose after we'd have bet the over
    state["bets"] = state["bets"][-300:]
    return state


def summary(state: dict) -> dict:
    bets = state.get("bets") or []
    g = [b for b in bets if b.get("result") in ("W", "L")]
    clv = [b["clv"] for b in bets if b.get("clv") is not None and b.get("result")]
    return {"bets": len(bets), "w": sum(b["result"] == "W" for b in g), "l": sum(b["result"] == "L" for b in g),
            "avg_clv": round(sum(clv) / len(clv), 2) if clv else None, "beat_close": sum(c > 0 for c in clv),
            "n_clv": len(clv), "recent": sorted(bets, key=lambda b: b["at"], reverse=True)[:30]}


def make_fetch(api_key: str, get_json):
    """fetch_props(game) using The Odds API: the events list (free) to find the game, then one credit for its props."""
    cache: dict = {}

    def fetch(game):
        if "events" not in cache:
            cache["events"] = get_json(EVENTS.format(key=urllib.parse.quote(api_key))) or []
        from .teams import code

        def c(x):
            try:
                return code(x)
            except Exception:
                return None
        ev = next((e for e in cache["events"] if {c(e.get("home_team", "")), c(e.get("away_team", ""))}
                   == {game.home, game.away}), None)
        if not ev:
            return None
        return parse_props(get_json(PROPS.format(eid=ev["id"], key=urllib.parse.quote(api_key))) or {})
    return fetch


def run(store, now, games, reads, rotations, box_rows, api_key, get_json, finals) -> dict | None:
    if not api_key or not hasattr(store, "load_state"):
        return None
    st = store.load_state(["props_desk"]).get("props_desk") or {}
    new = step(st, now, games, reads, rotations, box_rows, make_fetch(api_key, get_json), finals)
    if json.dumps(new, sort_keys=True, default=str) != json.dumps(st, sort_keys=True, default=str):
        store.save_state({"props_desk": new})
    return summary(new)
