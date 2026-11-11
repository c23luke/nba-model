"""PLAYER PROPS BACKTEST WITH REAL LINES (Caden 2026-11-11: "i hear so many people make money on player props ...
can we test some systems out").

The Odds API keeps past prop lines (Pinnacle + the big US books; not ProphetX/Novig). For a sample of 2025-26 games
(env GAMES, default 120, spread evenly from Jan 1 to the end of the season, so every team has history):

  A. +EV vs PINNACLE: 5 hours before tip, every US-book price that pays 3%+ more than Pinnacle's fair odds (vig
     removed) at the same line. Best price per player / stat / side. Graded from the box score, and CLV against
     Pinnacle's fair price 10 minutes before tip. By size of the edge and by book.
  B. OUR MINUTES READS against the CLOSING line (10 minutes before tip, when inactives are known): history minutes
     jumps (overs), returning stars (unders), fill-ins the night the star returns (unders), using the props desk's
     own rules and projections. "Out tonight" = a rotation player with no minutes who played his team's last game
     (fresh news), as on the props desk. The line: Pinnacle's if posted, else the most common US-book line.
Cost: 20 credits per game per snapshot per market (regions us + eu), plus 1 per day for the event list.
env MARKETS: comma list of player_points,player_rebounds,player_assists (default player_points).
Run: python -m engine.measure_props_hist
"""
from __future__ import annotations

import os
import statistics
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import cluster
from . import props_desk as PD
from . import props_ev as E
from . import sources
from .measure_minutes_spots import load
from .measure_props_minutes import box
from .personnel import Player, TeamRead, norm
from .props_splits import returns, splits
from .teams import code

KEY = os.environ.get("ODDS_API_KEY", "")
H = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
US = ("draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "betonlineag", "bovada", "fanatics")
N = int(os.environ.get("GAMES", "120"))
MKTS = os.environ.get("MARKETS", "player_points")
STATS = [E.MARKETS[m] for m in MKTS.split(",")]
spent = {"credits": 0, "left": None}


def get(url):
    meta = {}
    try:
        js = sources.get_json(url, meta=meta)
    except Exception:
        return None
    spent["credits"] += int(meta.get("x-requests-last") or 0)
    spent["left"] = meta.get("x-requests-remaining")
    return js


def c(x):
    try:
        return code(x)
    except Exception:
        return None


def rows_for(g, summ):
    out = []
    for team, ps in box(summ or {}).items():
        for name, (m, pts, reb, ast) in ps.items():
            out.append({"team": team, "game_id": str(g.id), "game_date": g.game_date.isoformat(), "name": name,
                        "min": m, "pts": pts, "orb": 0, "drb": reb, "ast": ast})
    return out


def snap(eid, when):
    js = get(f"{H}/events/{eid}/odds?apiKey={urllib.parse.quote(KEY)}&date={when.strftime('%Y-%m-%dT%H:%M:%SZ')}"
             f"&regions=us,eu&markets={MKTS}&oddsFormat=american")
    return (js or {}).get("data") or None


def line_at(js, player, stat):
    """Pinnacle's line and prices, else the most common US line with -110."""
    px = E.prices(js)
    for (p, s, ln), q in (px.get("pinnacle") or {}).items():
        if p == player and s == stat and "Over" in q and "Under" in q:
            return {"line": ln, "over": q["Over"], "under": q["Under"], "src": "pinnacle"}
    lines = [ln for b in US for (p, s, ln) in (px.get(b) or {}) if p == player and s == stat]
    if not lines:
        return None
    return {"line": statistics.mode(lines), "over": -110.0, "under": -110.0, "src": "us"}


def rec(rs):
    w = sum(1 for r in rs if r["res"] == "W"); l = sum(1 for r in rs if r["res"] == "L")
    u = sum((E.dec(r["price"]) - 1) if r["res"] == "W" else -1 for r in rs if r["res"] in ("W", "L"))
    cl = [r["clv"] for r in rs if r.get("clv") is not None]
    s = f"{w}-{l}" + (f" {w / (w + l):5.1%}  {u:+6.1f}u ({u / (w + l):+.1%} a bet)" if w + l else "")
    if cl:
        s += f"  CLV vs Pinnacle close {sum(cl) / len(cl) * 100:+.1f}c, beat it {sum(x > 0 for x in cl)}/{len(cl)}"
    return s


def main():
    games, sums, _ = load("2025-26")
    games = [g for g in games if g.final]
    allrows = {str(g.id): rows_for(g, sums.get(g.id)) for g in games}
    pool = [g for g in games if g.game_date >= date(2026, 1, 1)]
    step_ = max(1, len(pool) // N)
    sample = pool[::step_][:N]
    print(f"sample: {len(sample)} games from {sample[0].game_date} to {sample[-1].game_date}; markets {MKTS}", flush=True)
    ev_bets, ours = [], []
    day_events = {}
    for g in sample:
        d = g.game_date
        if d not in day_events:
            js = get(f"{H}/events?apiKey={urllib.parse.quote(KEY)}&date={d.isoformat()}T16:00:00Z")
            day_events[d] = (js or {}).get("data") or []
        ev = next((e for e in day_events[d] if {c(e.get("home_team", "")), c(e.get("away_team", ""))} == {g.home, g.away}), None)
        if not ev:
            continue
        tip = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        early, close = snap(ev["id"], tip - timedelta(hours=5)), snap(ev["id"], tip - timedelta(minutes=10))
        tonight = allrows[str(g.id)]
        if not tonight:
            continue
        # ---- A. +EV vs Pinnacle among US books, 5 hours out
        if early:
            px = E.prices(early)
            best = {}
            for k, p in (px.get("pinnacle") or {}).items():
                f = E.fair(p)
                if not f or k[1] not in STATS:
                    continue
                for b in US:
                    q = (px.get(b) or {}).get(k)
                    for side in ("Over", "Under"):
                        if q and side in q:
                            ev_ = f[side] * E.dec(q[side]) - 1
                            if ev_ >= E.MIN_EV and ev_ > best.get((k, side), {}).get("ev", -1):
                                best[(k, side)] = {"ev": ev_, "price": q[side], "book": b, "fair": f[side]}
            for (k, side), x in best.items():
                cf = None
                if close:
                    pq = (E.prices(close).get("pinnacle") or {}).get(k)
                    fc = E.fair(pq) if pq else None
                    cf = fc[side] if fc else None
                res = PD.grade({"game_id": str(g.id), "player": k[0], "stat": k[1], "side": side.lower(), "line": k[2]}, tonight)
                if res in ("W", "L", "P"):
                    ev_bets.append({**x, "res": res, "side": side.lower(), "stat": k[1],
                                    "clv": None if cf is None else cf - 1 / E.dec(x["price"])})
        # ---- B. our minutes reads at the close
        if close:
            prior = [r for gid, rs in allrows.items() for r in rs if r["game_date"] < d.isoformat()]
            rot, sp, rets, score = cluster.rotations(prior), splits(prior), returns(prior), PD.scoring(prior)
            reads = {}
            for team in (g.home, g.away):
                tr = TeamRead(team)
                for r in tonight:
                    if r["team"] != team:
                        continue
                    s = score.get((team, norm(r["name"])))
                    out_ = r["min"] == 0 and norm(r["name"]) in (rot.get(team) or {})
                    tr.players.append(Player(r["name"], "out" if out_ else "active", 0, {"mp": 1} if s else None,
                                             minutes=s["mpg"] if s else 0.0))
                reads[team] = tr

            class _G:
                id, home, away = str(g.id), g.home, g.away
            for cnd in PD.candidates(_G, reads, rot, score, sp, rets):
                if cnd["kind"] not in ("hidden", "jump_hist", "returning", "fill_back"):
                    continue
                for stat in STATS:
                    m = line_at(close, norm(cnd["player"]), stat)
                    if not m:
                        continue
                    side = "under" if cnd["kind"] in ("returning", "fill_back") else "over"
                    proj = cnd["proj"][stat]
                    edge = (proj - m["line"]) if side == "over" else (m["line"] - proj)
                    if edge < PD.EDGE[stat]:
                        continue
                    res = PD.grade({"game_id": str(g.id), "player": cnd["player"], "stat": stat, "side": side,
                                    "line": m["line"]}, tonight)
                    if res in ("W", "L", "P"):
                        kind = "history jump (over)" if cnd["kind"] in ("hidden", "jump_hist") else \
                            "returning star (under)" if cnd["kind"] == "returning" else "fill-ins when he returns (under)"
                        ours.append({"kind": kind, "res": res, "price": m[side], "src": m["src"], "stat": stat,
                                     "edge": edge})
    print(f"\ncredits spent: {spent['credits']}  | left: {spent['left']}")
    print(f"\n=== A. US-book prices 3%+ better than Pinnacle's fair odds, 5 hours before tip ({len(ev_bets)} bets)")
    print("  all:", rec(ev_bets))
    for lo, hi, nm in ((0.03, 0.05, "edge 3-5%"), (0.05, 0.08, "edge 5-8%"), (0.08, 9, "edge 8%+")):
        print(f"  {nm:12}", rec([b for b in ev_bets if lo <= b["ev"] < hi]))
    for side in ("over", "under"):
        print(f"  {side:12}", rec([b for b in ev_bets if b["side"] == side]))
    for b in US:
        xs = [x for x in ev_bets if x["book"] == b]
        if xs:
            print(f"  at {b:18}", rec(xs))
    print(f"\n=== B. our minutes reads against the closing prop line ({len(ours)} bets)")
    print("  all:", rec(ours))
    for k in ("history jump (over)", "returning star (under)", "fill-ins when he returns (under)"):
        print(f"  {k:34}", rec([o for o in ours if o["kind"] == k]))
    print("  line from Pinnacle:", rec([o for o in ours if o["src"] == "pinnacle"]), "| from US books:", rec([o for o in ours if o["src"] == "us"]))


if __name__ == "__main__":
    main()
