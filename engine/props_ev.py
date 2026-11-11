"""PROPS +EV vs PINNACLE — tracking only (Caden 2026-11-11: "look at pinnacle where is there +ev bets maybe we combine
with our ... betting").

Pinnacle is the sharpest book; its prices with the vig taken out are the best free estimate of a prop's true odds.
For every player points / rebounds / assists line Pinnacle posts, we compare the prices on the venues we can bet
(ProphetX, Novig, BetOpenly) at the SAME line. When a venue pays more than the fair odds by 3%+ (expected return),
that's a paper bet. "Stacked" when our own props desk (minutes / injury read) is on the same player, stat and side.

  * lines: The Odds API, regions us + us_ex + eu, 3 markets = 9 credits per read, for games tipping within 12 hours,
    read every 60 minutes and once more in the last 25 minutes before tip (that read is the CLOSE)
  * CLV: Pinnacle's fair chance of our side at the close, minus the chance our price needed to break even. Beating
    Pinnacle's close is the known sign of a real props edge; this is how we'll judge it.
  * graded from box scores; a player who doesn't play is a void
  * exchange fees are NOT taken off (Novig charges none pregame; ProphetX's commission is unknown here)
Nothing is bet from this. Stored in bet_state "props_ev".
"""
from __future__ import annotations

import json
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta

from .personnel import norm
from .props_desk import grade

VENUES = ("prophetx", "novig", "betopenly")
SHARP = "pinnacle"
MIN_EV = 0.03
READ_EVERY = timedelta(minutes=60)
CLOSE = timedelta(minutes=25)
WINDOW = timedelta(hours=12)
MARKETS = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast"}
EVENTS = "https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={key}"
ODDS = ("https://api.the-odds-api.com/v4/sports/basketball_nba/events/{eid}/odds?apiKey={key}"
        "&regions=us,us_ex,eu&markets=" + ",".join(MARKETS) + "&oddsFormat=american")


def dec(american: float) -> float:
    return 1 + (american / 100 if american > 0 else 100 / -american)


def prices(js: dict) -> dict:
    """book -> (normalised player, stat, line) -> {"Over": american, "Under": american, "name": player}."""
    out = defaultdict(dict)
    for bk in js.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            stat = MARKETS.get(mk.get("key"))
            if not stat:
                continue
            for o in mk.get("outcomes") or []:
                if o.get("point") is None or o.get("name") not in ("Over", "Under"):
                    continue
                k = (norm(o.get("description") or ""), stat, float(o["point"]))
                d = out[bk["key"]].setdefault(k, {"name": o.get("description")})
                d[o["name"]] = float(o["price"])
    return out


def fair(p: dict) -> dict | None:
    """Pinnacle's over/under with the vig removed (proportionally). None unless both sides are posted."""
    if "Over" not in p or "Under" not in p:
        return None
    io, iu = 1 / dec(p["Over"]), 1 / dec(p["Under"])
    return {"Over": io / (io + iu), "Under": iu / (io + iu)}


def edges(js: dict) -> list[dict]:
    """Every venue price at Pinnacle's line that pays 3%+ more than Pinnacle's fair odds."""
    px = prices(js)
    out = []
    for k, p in (px.get(SHARP) or {}).items():
        f = fair(p)
        if not f:
            continue
        for v in VENUES:
            q = (px.get(v) or {}).get(k)
            if not q:
                continue
            for side in ("Over", "Under"):
                if side in q:
                    ev = f[side] * dec(q[side]) - 1
                    if ev >= MIN_EV:
                        out.append({"player": p["name"], "key": list(k), "stat": k[1], "line": k[2],
                                    "side": side.lower(), "venue": v, "price": q[side], "fair": round(f[side], 4),
                                    "pin_price": p[side], "ev": round(ev, 4)})
    return out


def closing_fair(js: dict, bet: dict) -> float | None:
    p = (prices(js).get(SHARP) or {}).get(tuple([bet["key"][0], bet["key"][1], float(bet["key"][2])]))
    f = fair(p) if p else None
    return f["Over" if bet["side"] == "over" else "Under"] if f else None


def step(state: dict, now: datetime, games: list, fetch, box_rows: list[dict], finals: dict, desk_bets: list[dict]) -> dict:
    """One pass. fetch(game) -> the event's odds json or None."""
    state = {"bets": [dict(b) for b in state.get("bets") or []], "fetched": dict(state.get("fetched") or {})}
    stacked = {(b["game_id"], norm(b["player"]), b.get("stat", "pts"), b.get("side", "over")) for b in desk_bets}
    for g in games:
        tip = datetime.fromisoformat(str(g.tip_utc).replace("Z", "+00:00")) if g.tip_utc else None
        if not tip or tip <= now or tip - now > WINDOW:
            continue
        last = state["fetched"].get(g.id)
        if last:
            last_t = datetime.fromisoformat(last)
            closing = tip - now <= CLOSE and last_t < tip - CLOSE
            if now - last_t < READ_EVERY and not closing:
                continue
        js = fetch(g)
        state["fetched"][g.id] = now.isoformat()
        if not js:
            continue
        for b in state["bets"]:                               # the latest Pinnacle read before tip = the close
            if b["game_id"] == g.id and not b.get("result"):
                cf = closing_fair(js, b)
                if cf is not None:
                    b["close_fair"], b["close_at"] = round(cf, 4), now.isoformat()
        have = {(b["game_id"], tuple(b["key"]), b["side"], b["venue"]) for b in state["bets"]}
        for e in edges(js):
            k = (g.id, tuple(e["key"]), e["side"], e["venue"])
            if k in have:
                continue
            state["bets"].append({**e, "game_id": g.id, "away": g.away, "home": g.home, "tip_utc": g.tip_utc,
                                  "at": now.isoformat(), "close_fair": e["fair"],
                                  "stacked": (g.id, e["key"][0], e["stat"], e["side"]) in stacked})
    for b in state["bets"]:
        if not b.get("result") and (finals.get(b["game_id"]) or {}).get("final"):
            b["result"] = grade({"game_id": b["game_id"], "player": b["player"], "stat": b["stat"], "side": b["side"],
                                 "line": b["line"]}, box_rows)
        b["clv"] = round(b["close_fair"] - 1 / dec(b["price"]), 4)      # + = beat Pinnacle's close
    state["bets"] = state["bets"][-1500:]
    return state


def _rec(bets):
    g = [b for b in bets if b.get("result") in ("W", "L")]
    units = sum((dec(b["price"]) - 1) if b["result"] == "W" else -1 for b in g)
    cl = [b["clv"] for b in bets if b.get("clv") is not None and b.get("result")]
    return {"bets": len(bets), "w": sum(b["result"] == "W" for b in g), "l": sum(b["result"] == "L" for b in g),
            "open": sum(1 for b in bets if not b.get("result")), "units": round(units, 2),
            "avg_ev": round(sum(b["ev"] for b in bets) / len(bets), 4) if bets else None,
            "avg_clv": round(sum(cl) / len(cl) * 100, 2) if cl else None, "beat_close": sum(c > 0 for c in cl),
            "n_clv": len(cl)}


def summary(state: dict) -> dict:
    bets = state.get("bets") or []
    return {**_rec(bets), "stacked": _rec([b for b in bets if b.get("stacked")]),
            "by_venue": {v: _rec([b for b in bets if b["venue"] == v]) for v in VENUES},
            "recent": sorted(bets, key=lambda b: (-b["ev"], b["at"]))[:40] if bets else []}


def make_fetch(api_key: str, get_json):
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
        return get_json(ODDS.format(eid=ev["id"], key=urllib.parse.quote(api_key))) if ev else None
    return fetch


def run(store, now, games, box_rows, api_key, get_json, finals) -> dict | None:
    if not api_key or not hasattr(store, "load_state"):
        return None
    st = store.load_state(["props_ev", "props_desk"])
    old = st.get("props_ev") or {}
    new = step(old, now, games, make_fetch(api_key, get_json), box_rows, finals, (st.get("props_desk") or {}).get("bets") or [])
    if json.dumps(new, sort_keys=True, default=str) != json.dumps(old, sort_keys=True, default=str):
        store.save_state({"props_ev": new})
    return summary(new)
