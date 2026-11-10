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
  * "hidden bump": a history jump the players model doesn't see (it gives him under +2 minutes). OVER only.
  * "fake bump": the players model gives this teammate 5+ more minutes, but in 3+ games this season without the
    absent player he gained under 2. History says the minutes don't come, but measured over 2 seasons his points
    still rise about 2.5 (usage), so the UNDER only fires when the line is 3+ above his usual night plus that.
  * "returning": a 28+ mpg player back after 3+ straight games out; his first game back averages 5 fewer minutes and
    2.6 fewer points (2 seasons). UNDER.
  * "fill_back": the teammates who filled in while he was out; they keep only about half their extra minutes the
    night he's back. UNDER against what they did while he was out.
  Projections are his usual night (last 10 games) plus the measured change, not raw averages (see the constants).
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
from .props_splits import returns as star_returns
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
# Measured 2026-11-10 (engine/measure_props_minutes.py, 2 seasons, 17,299 teammate-games with a fresh absence):
#  * history (2+ games) said +8.5 min -> real +5.0 overall, but bench guys (under 15 mpg) +8.8 -> +8.4: so a
#    teammate's history gain is trusted 95% for bench guys and 60% for everyone else.
#  * the naive "his minutes get shared out" guess said +5.9 -> real +1.5 min, yet points still rose +2.8, rebounds
#    +0.5, assists +0.7 (usage goes up even without minutes). Same for fake bumps: +0.8 min, +2.5 pts, +0.4 reb, +0.6 ast.
HIST_TRUST = {"bench": 0.95, "other": 0.60}
BENCH_MPG = 15.0
NO_HISTORY_GAIN = {"pts": 2.8, "reb": 0.5, "ast": 0.7}
FAKE_GAIN_STATS = {"pts": 2.5, "reb": 0.4, "ast": 0.6}
# Measured 2026-11-10 (engine/measure_minutes_spots.py, 2 seasons, 289 returns of a 28+ mpg player after 3+ straight
# games out): his first game back vs his usual, by how long he was out (minutes, points, rebounds, assists).
# 63% scored below their usual; both seasons agree. The team's ATS in that game: 136-142, nothing.
RETURN_GAME1 = ((5, {"min": -3.6, "pts": -1.8, "reb": -0.4, "ast": -0.6}),
                (10, {"min": -6.7, "pts": -4.0, "reb": -1.0, "ast": -0.5}),
                (20, {"min": -6.4, "pts": -2.7, "reb": -0.3, "ast": -0.7}),
                (999, {"min": -9.1, "pts": -3.0, "reb": -1.6, "ast": -1.4}))
# The fill-ins (5+ above their usual while he was out): usual 17.2, during 26.2, the night he returns 21.4 -> they
# keep 47% of the extra minutes.
FILL_KEEP = 0.47
KINDS = {"returning": "Star back from 3+ games out (minutes usually limited): unders",
         "fill_back": "Fill-ins the night the star returns (they lose about half the extra minutes): unders",
         "hidden": "Hidden bump (history says +5 min, the players model doesn't see it): overs",
         "jump_hist": "Minutes jump (this season's games without him): overs",
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


def returning(game, reads: dict, score: dict, rets: dict) -> list[dict]:
    """A 28+ mpg player back tonight after 3+ straight games out (unders on him), and the teammates who filled in
    for him (unders: they give back about half the extra minutes)."""
    out = []
    for team in (game.away, game.home):
        r = reads.get(team)
        if r is None:
            continue
        status = {norm(p.name): p.status for p in r.players}
        for k, x in (rets.get(team) or {}).items():
            st = status.get(k)
            if st is None or st == "out":
                continue                                  # not on tonight's read, or still out
            delta = next(d for lim, d in RETURN_GAME1 if x["missed"] <= lim)
            out.append({"game_id": game.id, "team": team, "player": x["name"], "because": [f"back after {x['missed']} games out"],
                        "kind": "returning", "missed": x["missed"], "mpg": x["pre"]["min"], "dtd": st == "day-to-day",
                        "proj": {s: round(x["pre"][s] + delta[s], 1) for s in EDGE},
                        "proj_min": round(x["pre"]["min"] + delta["min"], 1)})
            if st == "day-to-day":
                continue                                  # his fill-ins only once he's confirmed back
            for b, f in x["fill"].items():
                s = score.get((team, b))
                if not s or status.get(b) == "out":
                    continue
                pm = f["usual_min"] + FILL_KEEP * (f["during_min"] - f["usual_min"])
                out.append({"game_id": game.id, "team": team, "player": f["name"], "because": [f"{x['name']} is back"],
                            "kind": "fill_back", "returner": x["name"], "usual_min": f["usual_min"],
                            "during_min": f["during_min"], "n_during": f["n"], "mpg": round(s["mpg"], 1),
                            "dtd": status.get(b) == "day-to-day", "proj_min": round(pm, 1),
                            "proj": {"pts": round(pm * s["ppm"], 1), "reb": round(pm * s["rpm"], 1), "ast": round(pm * s["apm"], 1)}})
    return out


def candidates(game, reads: dict, rotations: dict, score: dict, splits: dict | None = None,
               rets: dict | None = None) -> list[dict]:
    """Teammates of a freshly-out rotation player whose minutes should (or are assumed to) jump; plus returning stars."""
    splits = splits or {}
    out = returning(game, reads, score, rets or {})
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
            now_ = {"pts": s["ppm"] * s["mpg"], "reb": s["rpm"] * s["mpg"], "ast": s["apm"] * s["mpg"]}   # his usual night
            if sp:
                real_gain = sp["min_wo"] - sp["min_with"]
                hist = {"split_of": who, "n_wo": sp["n_wo"], "min_with": sp["min_with"], "min_wo": sp["min_wo"]}
                if real_gain >= GAIN_MIN:
                    tr = HIST_TRUST["bench" if s["mpg"] < BENCH_MPG else "other"]
                    proj = {k: round(now_[k] + tr * (sp[f"{k}_wo"] - sp[f"{k}_with"]), 1) for k in EDGE}
                    out.append({**base, **hist, "kind": "hidden" if model_gain < FAKE_GAIN else "jump_hist", "trust": tr,
                                "proj": proj, "proj_min": round(s["mpg"] + tr * real_gain, 1)})
                elif model_gain >= GAIN_MIN and real_gain < FAKE_GAIN and sp["n_wo"] >= SPLIT_GAMES:
                    proj = {k: round(now_[k] + FAKE_GAIN_STATS[k], 1) for k in EDGE}
                    out.append({**base, **hist, "kind": "fake", "proj": proj, "proj_min": round(s["mpg"] + max(real_gain, 0), 1)})
            elif model_gain >= GAIN_MIN:
                proj = {k: round(now_[k] + NO_HISTORY_GAIN[k], 1) for k in EDGE}
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
    rets = star_returns(box_rows)
    open_games = {b["game_id"] for b in state["bets"] if not b.get("result")}
    for g in games:
        tip = datetime.fromisoformat(str(g.tip_utc).replace("Z", "+00:00")) if g.tip_utc else None
        if not tip or tip <= now or tip - now > timedelta(hours=14):
            continue
        cands = candidates(g, reads, rotations, score, sp, rets)
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
                side = "under" if c["kind"] in ("fake", "returning", "fill_back") else "over"
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
