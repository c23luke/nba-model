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
OPEN_WINDOW = timedelta(hours=30)     # opening-lines model: read games tipping within 30 hours...
OPEN_EVERY = timedelta(hours=3)       # ...every 3 hours while they're more than 12 hours away
OPEN_MIN = timedelta(hours=8)         # a first read closer to tip than this isn't an opening line
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


MODEL_EDGE = {"pts": 3.0, "reb": 1.5, "ast": 1.5}   # our projection vs Pinnacle's line (2026-11-11 walk-forward)


def model_edges(js: dict, game_id: str, proj: dict) -> list[dict]:
    """Our props model vs Pinnacle's line: 3+ points (1.5 rebounds / assists) off -> paper bet on that side, at the
    best venue price at that line (Pinnacle's own price if no venue has it)."""
    px = prices(js)
    out = []
    for k, p in (px.get(SHARP) or {}).items():
        f = fair(p)
        pr = proj.get((game_id, k[0]))
        if not f or not pr or k[1] not in pr:
            continue
        diff = pr[k[1]] - k[2]
        if abs(diff) < MODEL_EDGE[k[1]]:
            continue
        side = "Over" if diff > 0 else "Under"
        best, venue = p[side], "pinnacle"
        for v in VENUES:
            q = (px.get(v) or {}).get(k)
            if q and side in q and q[side] > best:
                best, venue = q[side], v
        out.append({"kind": "model", "player": p["name"], "key": list(k), "stat": k[1], "line": k[2],
                    "side": side.lower(), "venue": venue, "price": best, "fair": round(f[side], 4),
                    "pin_price": p[side], "ev": round(f[side] * dec(best) - 1, 4), "proj": pr[k[1]],
                    "proj_min": pr.get("min"), "l10": (pr.get("l10") or {}).get(k[1]),
                    "fresh_out": pr.get("fresh_out"), "returning": pr.get("returning"), "mpg": pr.get("mpg"),
                    # the two spots that beat Pinnacle's close in the real-lines test (points, 3+ off, 2025-26):
                    "spot_fresh": bool(pr.get("fresh_out")), "spot_bench": (pr.get("mpg") or 99) < 20})
    return out


def venue_model_edges(js: dict, game_id: str, proj: dict) -> list[dict]:
    """Our props model vs each VENUE's own line (ProphetX / Novig / BetOpenly), at that venue's price: the bet we
    would actually make (Caden 2026-11-11: beat the softer markets, not Pinnacle)."""
    px = prices(js)
    pin = px.get(SHARP) or {}
    out = []
    for v in VENUES:
        for k, q in (px.get(v) or {}).items():
            pr = proj.get((game_id, k[0]))
            if not pr or k[1] not in pr:
                continue
            diff = pr[k[1]] - k[2]
            if abs(diff) < MODEL_EDGE[k[1]]:
                continue
            side = "Over" if diff > 0 else "Under"
            if side not in q:
                continue
            f = fair(pin[k]) if k in pin else None
            out.append({"kind": "model_venue", "player": q["name"], "key": list(k), "stat": k[1], "line": k[2],
                        "side": side.lower(), "venue": v, "price": q[side], "proj": pr[k[1]],
                        "fair": round(f[side], 4) if f else None, "pin_line": None if f else
                        next((kk[2] for kk in pin if kk[0] == k[0] and kk[1] == k[1]), None),
                        "ev": round(f[side] * dec(q[side]) - 1, 4) if f else None, "mpg": pr.get("mpg"),
                        "spot_fresh": bool(pr.get("fresh_out")), "spot_bench": (pr.get("mpg") or 99) < 20})
    return out


def stack_edges(js: dict, game_id: str, proj: dict) -> list[dict]:
    """PROPS STACK TRACKERS (engine/props_stack.py): Pinnacle's points line for every player we project, his over /
    under flags, and every tracker they set off. Priced at the best venue at Pinnacle's line (else Pinnacle's own)."""
    from .props_stack import fire
    px = prices(js)
    out = []
    for k, p in (px.get(SHARP) or {}).items():
        if k[1] != "pts":
            continue
        pr = proj.get((game_id, k[0]))
        f = fair(p)
        if not f or not pr or not pr.get("feat"):
            continue
        for name, side, why in fire(pr["feat"], k[2], pr.get("pts")):
            S = side.capitalize()
            best, venue = p[S], "pinnacle"
            for v in VENUES:
                q = (px.get(v) or {}).get(k)
                if q and S in q and q[S] > best:
                    best, venue = q[S], v
            out.append({"kind": "pstack", "tracker": name, "why": why, "player": p["name"], "key": list(k), "stat": "pts",
                        "line": k[2], "side": side, "venue": venue, "price": best, "pin_price": p[S],
                        "fair": round(f[S], 4), "ev": round(f[S] * dec(best) - 1, 4), "proj": pr.get("pts"),
                        "mpg": pr.get("mpg")})
    return out


def closing_fair(js: dict, bet: dict) -> float | None:
    p = (prices(js).get(SHARP) or {}).get(tuple([bet["key"][0], bet["key"][1], float(bet["key"][2])]))
    f = fair(p) if p else None
    return f["Over" if bet["side"] == "over" else "Under"] if f else None


def _venue_line(js_px: dict, venue: str, player: str, stat: str):
    """A venue's current line for a player / stat: the one priced closest to even (its main line)."""
    best = None
    for (p, s_, ln), q in (js_px.get(venue) or {}).items():
        if p == player and s_ == stat and "Over" in q and "Under" in q:
            d = abs(q["Over"] - q["Under"])
            if best is None or d < best[0]:
                best = (d, ln, q)
    return (best[1], best[2]) if best else (None, None)


def step(state: dict, now: datetime, games: list, fetch, box_rows: list[dict], finals: dict, desk_bets: list[dict],
         proj: dict | None = None, news: dict | None = None, if_out: dict | None = None) -> dict:
    """One pass. fetch(game) -> the event's odds json or None.
    news: game_id -> [players newly ruled out this run] (news desk; forces a read of that game's props now).
    if_out: (game_id, questionable player) -> projections for his teammates if he sits (the ready list)."""
    state = {"bets": [dict(b) for b in state.get("bets") or []], "fetched": dict(state.get("fetched") or {}),
             "opened": dict(state.get("opened") or {}), "ready": dict(state.get("ready") or {})}
    news = news or {}
    stacked = {(b["game_id"], norm(b["player"]), b.get("stat", "pts"), b.get("side", "over")) for b in desk_bets}
    for g in games:
        tip = datetime.fromisoformat(str(g.tip_utc).replace("Z", "+00:00")) if g.tip_utc else None
        if not tip or tip <= now or tip - now > OPEN_WINDOW:
            continue
        last = state["fetched"].get(g.id)
        forced = bool(news.get(g.id))
        if last and not forced:
            last_t = datetime.fromisoformat(last)
            closing = tip - now <= CLOSE and last_t < tip - CLOSE
            every = READ_EVERY if tip - now <= WINDOW else OPEN_EVERY
            if now - last_t < every and not closing:
                continue
        js = fetch(g)
        state["fetched"][g.id] = now.isoformat()
        if not js:
            continue
        px = prices(js)
        # line movement for every open bet at its own venue (points; + = moved our way)
        for b in state["bets"]:
            if b["game_id"] == g.id and not b.get("result") and b.get("venue") in VENUES:
                ln, q = _venue_line(px, b["venue"], b["key"][0], b["stat"])
                if ln is not None:
                    b["last_line"], b["last_at"] = ln, now.isoformat()
                    b["move"] = round((ln - b["line"]) if b["side"] == "over" else (b["line"] - ln), 1)
        base = {"game_id": g.id, "away": g.away, "home": g.home, "tip_utc": g.tip_utc, "at": now.isoformat()}
        # A. OPENING LINES: the first time this game's props are on the board
        if g.id not in state["opened"] and any(px.get(v) for v in VENUES):
            state["opened"][g.id] = now.isoformat()
            # only a real opening read counts: 8+ hours before tip (a first read near tip isn't an opening line)
            for e in (venue_model_edges(js, g.id, proj or {}) if tip - now >= OPEN_MIN else []):
                state["bets"].append({**e, **base, "kind": "open", "hours_before": round((tip - now).total_seconds() / 3600, 1),
                                      "close_fair": e["fair"]})
        # B. NEWS DESK: a rotation player was just ruled out -> his teammates, at lines that may not have moved yet
        for out_name, team in news.get(g.id) or []:
            for e in venue_model_edges(js, g.id, proj or {}):
                pr = (proj or {}).get((g.id, e["key"][0])) or {}
                if pr.get("team") != team:
                    continue
                state["bets"].append({**e, **base, "kind": "news", "news_player": out_name,
                                      "hours_before": round((tip - now).total_seconds() / 3600, 1), "close_fair": e["fair"]})
        # B2. READY LIST: if a questionable player sits, which teammate lines would be 3+ off our number
        ready = []
        for (gid, who), alt in (if_out or {}).items():
            if gid != g.id:
                continue
            for e in venue_model_edges(js, g.id, alt):
                now_pr = ((proj or {}).get((g.id, e["key"][0])) or {}).get(e["stat"])
                if now_pr is not None and abs(now_pr - e["line"]) >= MODEL_EDGE[e["stat"]]:
                    continue                          # already a bet without the news
                ready.append({"if_out": who, "player": e["player"], "stat": e["stat"], "side": e["side"],
                              "line": e["line"], "venue": e["venue"], "price": e["price"], "proj_if_out": e["proj"],
                              "proj_now": now_pr})
        state["ready"][g.id] = {"at": now.isoformat(), "tip_utc": g.tip_utc, "away": g.away, "home": g.home,
                                "list": ready[:40]}
        if tip - now > WINDOW:
            continue                                  # the other trackers start 12 hours before tip
        for b in state["bets"]:                               # the latest Pinnacle read before tip = the close
            if b["game_id"] == g.id and not b.get("result"):
                cf = closing_fair(js, b)
                if cf is not None:
                    b["close_fair"], b["close_at"] = round(cf, 4), now.isoformat()
        have = {(b["game_id"], tuple(b["key"]), b["side"], b["venue"]) for b in state["bets"]}
        # props stack trackers: one paper bet per player, game and tracker (the first read inside 12 hours)
        have_stack = {(b["game_id"], b["key"][0], b.get("tracker")) for b in state["bets"] if b.get("kind") == "pstack"}
        for e in stack_edges(js, g.id, proj or {}):
            if (g.id, e["key"][0], e["tracker"]) in have_stack:
                continue
            have_stack.add((g.id, e["key"][0], e["tracker"]))
            state["bets"].append({**e, **base, "close_fair": e["fair"]})
        have_model = {(b["game_id"], tuple(b["key"][:2])) for b in state["bets"] if b.get("kind") == "model"}
        have_venue = {(b["game_id"], tuple(b["key"][:2]), b["venue"]) for b in state["bets"] if b.get("kind") == "model_venue"}
        for e in venue_model_edges(js, g.id, proj or {}):
            if (g.id, tuple(e["key"][:2]), e["venue"]) in have_venue:
                continue
            have_venue.add((g.id, tuple(e["key"][:2]), e["venue"]))
            state["bets"].append({**e, "game_id": g.id, "away": g.away, "home": g.home, "tip_utc": g.tip_utc,
                                  "at": now.isoformat(), "close_fair": e["fair"]})
        for e in model_edges(js, g.id, proj or {}):
            if (g.id, tuple(e["key"][:2])) in have_model:
                continue
            state["bets"].append({**e, "game_id": g.id, "away": g.away, "home": g.home, "tip_utc": g.tip_utc,
                                  "at": now.isoformat(), "close_fair": e["fair"],
                                  "stacked": (g.id, e["key"][0], e["stat"], e["side"]) in stacked})
        for e in edges(js):
            k = (g.id, tuple(e["key"]), e["side"], e["venue"])
            if k in have:
                continue
            e["kind"] = "ev"
            state["bets"].append({**e, "game_id": g.id, "away": g.away, "home": g.home, "tip_utc": g.tip_utc,
                                  "at": now.isoformat(), "close_fair": e["fair"],
                                  "stacked": (g.id, e["key"][0], e["stat"], e["side"]) in stacked})
    for b in state["bets"]:
        if not b.get("result") and (finals.get(b["game_id"]) or {}).get("final"):
            b["result"] = grade({"game_id": b["game_id"], "player": b["player"], "stat": b["stat"], "side": b["side"],
                                 "line": b["line"]}, box_rows)
        b["clv"] = None if b.get("close_fair") is None else round(b["close_fair"] - 1 / dec(b["price"]), 4)   # + = beat Pinnacle's close
    state["bets"] = state["bets"][-2500:]
    state["opened"] = {k: v for k, v in state["opened"].items() if now - datetime.fromisoformat(v) < timedelta(days=3)}
    state["ready"] = {k: v for k, v in state["ready"].items()
                      if v.get("tip_utc") and datetime.fromisoformat(str(v["tip_utc"]).replace("Z", "+00:00")) > now}
    return state


def _move(bets):
    mv = [b["move"] for b in bets if b.get("move") is not None and b.get("result")]
    return {"avg_move": round(sum(mv) / len(mv), 2) if mv else None, "moved_our_way": sum(m > 0 for m in mv),
            "moved_against": sum(m < 0 for m in mv)}


def _rec(bets):
    g = [b for b in bets if b.get("result") in ("W", "L")]
    units = sum((dec(b["price"]) - 1) if b["result"] == "W" else -1 for b in g)
    cl = [b["clv"] for b in bets if b.get("clv") is not None and b.get("result")]
    return {"bets": len(bets), "w": sum(b["result"] == "W" for b in g), "l": sum(b["result"] == "L" for b in g),
            "open": sum(1 for b in bets if not b.get("result")), "units": round(units, 2),
            "avg_ev": round(sum(b["ev"] for b in bets if b.get("ev") is not None) / max(1, sum(1 for b in bets if b.get("ev") is not None)), 4) if bets else None,
            "avg_clv": round(sum(cl) / len(cl) * 100, 2) if cl else None, "beat_close": sum(c > 0 for c in cl),
            "n_clv": len(cl)}


def summary(state: dict) -> dict:
    allb = state.get("bets") or []
    bets = [b for b in allb if b.get("kind", "ev") == "ev"]
    model = [b for b in allb if b.get("kind") == "model"]
    return {**_rec(bets), "stacked": _rec([b for b in bets if b.get("stacked")]),
            "model": {**_rec(model), "recent": sorted(model, key=lambda b: b["at"], reverse=True)[:40]},
            "model_and_ev": _rec([b for b in model if b["ev"] > 0]),
            # the three props models (Caden 2026-11-11), points + rebounds + assists, each judged on its own
            "open_lines": {**_rec(ob := [b for b in allb if b.get("kind") == "open"]), **_move(ob),
                           "recent": sorted(ob, key=lambda b: b["at"], reverse=True)[:30]},
            "news_desk": {**_rec(nb := [b for b in allb if b.get("kind") == "news"]), **_move(nb),
                          "recent": sorted(nb, key=lambda b: b["at"], reverse=True)[:30]},
            "ready": state.get("ready") or {},
            "model_venue": {**_rec(mv := [b for b in allb if b.get("kind") == "model_venue" and b["stat"] == "pts"]),
                            "by_venue": {v: _rec([b for b in mv if b["venue"] == v]) for v in VENUES},
                            "recent": sorted(mv, key=lambda b: b["at"], reverse=True)[:30]},
            # tracked on their own (Caden 2026-11-11): points only, as tested
            "spot_fresh": {**_rec(sf := [b for b in model if b.get("spot_fresh") and b["stat"] == "pts"]),
                           "recent": sorted(sf, key=lambda b: b["at"], reverse=True)[:20]},
            "spot_bench": {**_rec(sb := [b for b in model if b.get("spot_bench") and b["stat"] == "pts"]),
                           "recent": sorted(sb, key=lambda b: b["at"], reverse=True)[:20]},
            "by_venue": {v: _rec([b for b in bets if b["venue"] == v]) for v in VENUES},
            # props stack trackers (Caden 2026-11-12), each judged on its own
            "stack_trackers": {name: {**_rec(tb := [b for b in allb if b.get("kind") == "pstack" and b.get("tracker") == name]),
                                      "backtest": bt, "side": side,
                                      "recent": sorted(tb, key=lambda b: b["at"], reverse=True)[:15]}
                               for name, side, _, bt in _trackers()},
            "recent": sorted(bets, key=lambda b: (-b["ev"], b["at"]))[:40] if bets else []}


def _trackers():
    from .props_stack import TRACKERS
    return TRACKERS


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


def run(store, now, games, box_rows, api_key, get_json, finals, proj=None, news=None, if_out=None) -> dict | None:
    if not api_key or not hasattr(store, "load_state"):
        return None
    st = store.load_state(["props_ev", "props_desk"])
    old = st.get("props_ev") or {}
    new = step(old, now, games, make_fetch(api_key, get_json), box_rows, finals, (st.get("props_desk") or {}).get("bets") or [],
               proj, news, if_out)
    if json.dumps(new, sort_keys=True, default=str) != json.dumps(old, sort_keys=True, default=str):
        store.save_state({"props_ev": new})
    return summary(new)
