"""PROPS DESK — tracking only (Caden 2026-11-10: "player props looking at guys ... only playing like 10 min";
then: "when this player sits ... everyone thinks this other player would get more minutes but they don't, so we take
the under").

When a rotation player is ruled out and he played his team's last game (fresh news), his minutes go somewhere.
Three kinds of paper bet, tracked separately:
  * "jump (history)": this season, in games the absent player missed, this teammate really did play 5+ more minutes.
    We project points / rebounds / assists from those games and take the OVER when the line is short of it.
  * "jump (model)": no games yet without the absent player, but the players model (which re-fits every team to 240
    minutes with tonight's absences) gives this teammate 5+ more minutes. Projection = tonight's minutes x his rate
    over his last 10 games. OVER only.
  * "fake bump": the players model gives this teammate 5+ more minutes, but in 3+ games this season without the
    absent player he gained under 2. The market likely assumes the bump; history says it doesn't come.
    We take the UNDER when the line sits above what he did in those games.
Lines: The Odds API (points, rebounds, assists; 3 credits per read), only for games with such news, read when the
news appears and then every 90 minutes, plus once in the last 30 minutes before tip (that read is the closing line
for CLV). Graded from the box score. Nothing is ever bet from this. Stored in bet_state "props_desk".
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .personnel import norm
from .props_splits import splits as with_without

GAIN_MIN = 5.0          # minutes above his average before we look
FAKE_GAIN = 2.0         # "fake bump": gained under this many minutes in the games without the absent player
SPLIT_GAMES = 3         # games without the absent player before his history counts (2 for an over)
EDGE = {"pts": 3.0, "reb": 1.5, "ast": 1.5}     # projection vs the line before a paper bet
MARKETS = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast"}
SAMPLE_MIN = 60         # minutes of recent sample needed for per-minute rates
REFETCH = timedelta(minutes=90)
CLOSE_READ = timedelta(minutes=30)
EVENTS = "https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={key}"
PROPS = ("https://api.the-odds-api.com/v4/sports/basketball_nba/events/{eid}/odds?apiKey={key}"
         "&regions=us&markets=" + ",".join(MARKETS) + "&oddsFormat=american")
KINDS = {"jump_hist": "Minutes jump (this season's games without him): overs",
         "jump_model": "Minutes jump (players model only): overs",
         "fake": "Fake bump (everyone expects minutes, history says no): unders"}


def _reb(r):
    return (r.get("orb") or 0) + (r.get("drb") or 0)


def scoring(box_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(team, normalised name) -> per-minute rates and mpg over the player's last 10 games with minutes."""
    by = defaultdict(list)
    for r in box_rows:
        if (r.get("min") or 0) > 0:
            by[(r["team"], norm(r.get("name") or ""))].append(r)
    out = {}
    for k, rs in by.items():
        rs = sorted(rs, key=lambda r: str(r.get("game_date")))[-10:]
        m = sum(r["min"] for r in rs)
        if m >= SAMPLE_MIN:
            out[k] = {"ppm": sum(r.get("pts") or 0 for r in rs) / m, "rpm": sum(_reb(r) for r in rs) / m,
                      "apm": sum(r.get("ast") or 0 for r in rs) / m, "min": m, "mpg": m / len(rs)}
    return out


def candidates(game, reads: dict, rotations: dict, score: dict, splits: dict | None = None) -> list[dict]:
    """Teammates of a freshly-out rotation player whose minutes should (or are assumed to) jump."""
    splits = splits or {}
    out = []
    for team in (game.away, game.home):
        r = reads.get(team)
        rot = rotations.get(team) or {}
        if r is None:
            continue
        fresh = [norm(p.name) for p in r.players if p.status == "out" and norm(p.name) in rot and rot[norm(p.name)]["last"]]
        if not fresh:
            continue
        because = [rot[a]["name"] for a in fresh]
        fresh.sort(key=lambda a: -rot[a]["mpg"])
        for p in r.players:
            if p.status == "out":
                continue
            b = norm(p.name)
            s = score.get((team, b))
            if not s:
                continue
            model_gain = p.minutes - s["mpg"]
            # the biggest absent player with a real history for this teammate
            sp, who = None, None
            for a in fresh:
                x = ((splits.get(team) or {}).get(a) or {}).get(b)
                if x and x["n_wo"] >= 2:
                    sp, who = x, rot[a]["name"]
                    break
            base = {"game_id": game.id, "team": team, "player": p.name, "because": because,
                    "mpg": round(s["mpg"], 1), "model_min": round(p.minutes, 1), "dtd": p.status == "day-to-day"}
            if sp:
                real_gain = sp["min_wo"] - sp["min_with"]
                hist = {"split_of": who, "n_wo": sp["n_wo"], "min_with": sp["min_with"], "min_wo": sp["min_wo"]}
                proj = {k: sp[f"{k}_wo"] for k in EDGE}
                if real_gain >= GAIN_MIN:
                    out.append({**base, **hist, "kind": "jump_hist", "proj": proj, "proj_min": sp["min_wo"]})
                elif model_gain >= GAIN_MIN and real_gain < FAKE_GAIN and sp["n_wo"] >= SPLIT_GAMES:
                    out.append({**base, **hist, "kind": "fake", "proj": proj, "proj_min": sp["min_wo"]})
            elif model_gain >= GAIN_MIN:
                proj = {"pts": round(p.minutes * s["ppm"], 1), "reb": round(p.minutes * s["rpm"], 1),
                        "ast": round(p.minutes * s["apm"], 1)}
                out.append({**base, "kind": "jump_model", "proj": proj, "proj_min": round(p.minutes, 1)})
    return out


def parse_props(js: dict) -> dict[tuple[str, str], dict]:
    """(normalised player, stat) -> {"line", "over", "under", "books"}: the most common line across books, and the
    median prices at that line."""
    found = defaultdict(list)
    for bk in js.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            stat = MARKETS.get(mk.get("key"))
            if not stat:
                continue
            per = defaultdict(dict)
            for o in mk.get("outcomes") or []:
                if o.get("point") is not None and o.get("name") in ("Over", "Under"):
                    per[(norm(o.get("description") or ""), float(o["point"]))][o["name"]] = int(o["price"])
            for (k, pt), px in per.items():
                found[(k, stat)].append((pt, px))
    out = {}
    for key, v in found.items():
        line = statistics.median_low([pt for pt, _ in v])
        at = [px for pt, px in v if pt == line]
        ov = [px["Over"] for px in at if "Over" in px]
        un = [px["Under"] for px in at if "Under" in px]
        out[key] = {"line": line, "over": int(statistics.median_low(ov)) if ov else None,
                    "under": int(statistics.median_low(un)) if un else None, "books": len(v)}
    return out


def grade(bet: dict, box_rows: list[dict]) -> str | None:
    r = next((r for r in box_rows if r.get("game_id") == bet["game_id"]
              and norm(r.get("name") or "") == norm(bet["player"])), None)
    if r is None:
        return None
    if not (r.get("min") or 0):
        return "VOID"                                  # he didn't play: a prop bet is refunded
    stat = bet.get("stat", "pts")
    got = _reb(r) if stat == "reb" else (r.get(stat) or 0)
    d = (got - bet["line"]) * (1 if bet.get("side", "over") == "over" else -1)
    return "W" if d > 0 else "L" if d < 0 else "P"


def clv(bet: dict) -> float | None:
    """+ = the line moved our way after we'd have bet (over: it rose; under: it fell)."""
    if bet.get("last_line") is None:
        return None
    d = bet["last_line"] - bet["line"]
    return round(d if bet.get("side", "over") == "over" else -d, 1)


def step(state: dict, now: datetime, games: list, reads: dict, rotations: dict, box_rows: list[dict],
         fetch_props, finals: dict) -> dict:
    """One pass. state: {"bets": [...], "fetched": {game_id: iso}}.
    fetch_props(game) -> parse_props output or None. finals: game_id -> {"final": bool}."""
    state = {"bets": [dict(b) for b in state.get("bets") or []], "fetched": dict(state.get("fetched") or {})}
    score = scoring(box_rows)
    sp = with_without(box_rows)
    open_games = {b["game_id"] for b in state["bets"] if not b.get("result")}
    for g in games:
        tip = datetime.fromisoformat(str(g.tip_utc).replace("Z", "+00:00")) if g.tip_utc else None
        if not tip or tip <= now or tip - now > timedelta(hours=14):
            continue
        cands = candidates(g, reads, rotations, score, sp)
        if not cands and g.id not in open_games:
            continue
        last = state["fetched"].get(g.id)
        if last:
            ago = now - datetime.fromisoformat(last)
            closing = tip - now <= CLOSE_READ and datetime.fromisoformat(last) < tip - CLOSE_READ
            if ago < REFETCH and not closing:
                continue
        props = fetch_props(g)
        state["fetched"][g.id] = now.isoformat()
        if not props:
            continue
        for b in state["bets"]:                       # keep reading the line toward tip: CLV
            if b["game_id"] == g.id and not b.get("result"):
                p = props.get((norm(b["player"]), b.get("stat", "pts")))
                if p:
                    b["last_line"], b["last_at"] = p["line"], now.isoformat()
        have = {(b["game_id"], norm(b["player"]), b.get("stat", "pts")) for b in state["bets"]}
        for c in cands:
            if c["dtd"]:
                continue
            for stat, proj in c["proj"].items():
                p = props.get((norm(c["player"]), stat))
                if not p or (g.id, norm(c["player"]), stat) in have:
                    continue
                side = "under" if c["kind"] == "fake" else "over"
                edge = (proj - p["line"]) if side == "over" else (p["line"] - proj)
                price = p["over"] if side == "over" else p["under"]
                if edge >= EDGE[stat] and price is not None:
                    state["bets"].append({**c, "stat": stat, "side": side, "proj_stat": proj, "edge": round(edge, 1),
                                          "at": now.isoformat(), "line": p["line"], "price": price, "books": p["books"],
                                          "last_line": p["line"], "tip_utc": g.tip_utc})
    for b in state["bets"]:
        if not b.get("result") and (finals.get(b["game_id"]) or {}).get("final"):
            b["result"] = grade(b, box_rows)
        b["clv"] = clv(b)
    state["bets"] = state["bets"][-400:]
    return state


def _rec(bets):
    g = [b for b in bets if b.get("result") in ("W", "L")]
    cl = [b["clv"] for b in bets if b.get("clv") is not None and b.get("result")]
    units = sum((100 / -b["price"] if b["price"] < 0 else b["price"] / 100) if b["result"] == "W" else -1
                for b in g if b.get("price"))
    return {"bets": len(bets), "w": sum(b["result"] == "W" for b in g), "l": sum(b["result"] == "L" for b in g),
            "open": sum(1 for b in bets if not b.get("result")), "units": round(units, 2),
            "avg_clv": round(sum(cl) / len(cl), 2) if cl else None, "beat_close": sum(c > 0 for c in cl),
            "n_clv": len(cl)}


def summary(state: dict) -> dict:
    bets = state.get("bets") or []
    out = _rec(bets)
    out["by_kind"] = {k: {"name": KINDS[k], **_rec([b for b in bets if b.get("kind", "jump_model") == k])} for k in KINDS}
    out["recent"] = sorted(bets, key=lambda b: b["at"], reverse=True)[:30]
    return out


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
