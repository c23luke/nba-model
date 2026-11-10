"""CLUSTER INJURIES (Caden 2026-11-10): when 2-3 rotation players are out at once — especially at the same position —
does the market under-react? Two seasons (2024-25, 2025-26), every game with an open and a close.

Who is "out": a rotation player (20+ minutes a game over the team's last 10 games, in at least 5 of them) who isn't in
this game's box score with minutes. "Fresh" = he played in the team's previous game (news the market had to react
to recently); "long" = he's been out a while (the market has had days to price it).
Position from ESPN's box score: guards (PG/SG/G), wings (SF/F/G-F), bigs (PF/C/F-C).

For each bucket, from the side of the DEPLETED team and of its OPPONENT:
  ATS at the open, ATS at the close, and how far the line moved (open -> close) toward the opponent.
Totals: over/under at the close when one team is missing 2+ players.
If depleted teams still cover at the close, the market adjusts enough (no edge). If the opponent covers well at the
close, the market under-reacts and the cluster is a bet.
Run: python -m engine.measure_cluster"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import backtest as BT
from . import backtest_open as BO
from . import personnel as P
from . import sources
from .teams import code


def group(pos: str) -> str:
    p = (pos or "").upper()
    if p in ("C", "F-C", "C-F", "PF"):
        return "big"
    if p in ("PG", "SG", "G"):
        return "guard"
    return "wing"


def box(js: dict) -> dict:
    """team -> {name: (minutes, position)} for players who played; positions for everyone listed."""
    out, pos = defaultdict(dict), {}
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        for a in st.get("athletes", []):
            ath = a.get("athlete") or {}
            name = ath.get("displayName", "")
            pos[name] = ((ath.get("position") or {}).get("abbreviation") or "")
            d = dict(zip(keys, a.get("stats") or []))
            try:
                m = 0 if a.get("didNotPlay") else int(str(d.get("minutes") or "0").split(":")[0] or 0)
            except ValueError:
                m = 0
            out[team][name] = (m, pos[name])
    return out, pos


def season_rows(season):
    cfg = BO.SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]
    games.sort(key=lambda g: (g.game_date, str(g.id)))
    with ThreadPoolExecutor(12) as ex:
        sums = dict(zip([g.id for g in games], ex.map(lambda g: BT._safe(sources.get_json, BT.SUM.format(g.id)) or {}, games)))
    lines = json.loads((P.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
    hist = defaultdict(list)          # team -> [{name: minutes}] for its previous games, oldest first
    position = {}
    out = []
    for g in games:
        b, pos = box(sums.get(g.id) or {})
        position.update({k: v for k, v in pos.items() if v})
        k = f"{g.game_date.isoformat()}|{g.away}|{g.home}"
        ln, tt = lines.get(k) or {}, totals.get(k) or {}
        teams = {}
        for t in (g.home, g.away):
            last10 = hist[t][-10:]
            mins = defaultdict(list)
            for gm in last10:
                for n, m in gm.items():
                    mins[n].append(m)
            rot = {n: sum(v) / len(last10) for n, v in mins.items() if len(last10) >= 5 and len([x for x in v if x > 0]) >= 5
                   and sum(v) / len(last10) >= 20}
            played = {n for n, (m, _) in (b.get(t) or {}).items() if m > 0}
            prev = hist[t][-1] if hist[t] else {}
            outs = [(n, mp, group(position.get(n, "")), (prev.get(n, 0) > 0)) for n, mp in rot.items() if n not in played]
            teams[t] = outs
        if b and ln.get("open") is not None and ln.get("close") is not None:
            out.append({"season": season, "home": g.home, "away": g.away, "margin": g.home_score - g.away_score,
                        "pts": g.home_score + g.away_score, "open": ln["open"], "close": ln["close"],
                        "tot_close": tt.get("close"), "tot_open": tt.get("open"), "outs": teams})
        for t in (g.home, g.away):
            if b.get(t):
                hist[t].append({n: m for n, (m, _) in b[t].items()})
    return out


def bucket(outs):
    """Labels for one team's absences."""
    n = len(outs)
    labs = []
    if n == 0:
        labs.append("0 rotation players out")
    elif n == 1:
        labs.append("1 out")
    elif n == 2:
        labs.append("2 out")
    else:
        labs.append("3+ out")
    by = defaultdict(int)
    for _, _, gp, _ in outs:
        by[gp] += 1
    if any(v >= 2 for v in by.values()):
        labs.append("2+ out at the SAME position")
        for gp, v in by.items():
            if v >= 2:
                labs.append(f"2+ {gp}s out")
    if n >= 2 and not any(v >= 2 for v in by.values()):
        labs.append("2+ out, all different positions")
    fresh = sum(1 for o in outs if o[3])
    if n >= 2 and fresh >= 1:
        labs.append("2+ out, at least one FRESH (played the last game)")
    if n >= 2 and fresh == 0:
        labs.append("2+ out, all LONG absences")
    mp = sum(o[1] for o in outs)
    if mp >= 60:
        labs.append("60+ rotation minutes out")
    return labs


def rec(xs):
    w = sum(x > 0 for x in xs); l = sum(x < 0 for x in xs)
    return f"{w}-{l} ({w / (w + l):.1%})" if w + l else "-"


def main():
    rows = []
    for s in BO.SEASONS:
        rows += season_rows(s)
    for scope in list(BO.SEASONS) + ["both"]:
        rs = rows if scope == "both" else [r for r in rows if r["season"] == scope]
        cats = defaultdict(lambda: {"dep_o": [], "dep_c": [], "opp_o": [], "opp_c": [], "move": [], "over": []})
        for r in rs:
            for t in (r["home"], r["away"]):
                outs = r["outs"][t]
                other = r["away"] if t == r["home"] else r["home"]
                if len(r["outs"][other]) >= len(outs) and len(outs) > 0:
                    continue        # only count a team as depleted when it's missing more than its opponent
                for lab in bucket(outs):
                    c = cats[lab]
                    home = t == r["home"]
                    m = r["margin"] if home else -r["margin"]
                    o = r["open"] if home else -r["open"]
                    cl = r["close"] if home else -r["close"]
                    c["dep_o"].append(m + o); c["dep_c"].append(m + cl)
                    c["opp_o"].append(-(m + o)); c["opp_c"].append(-(m + cl))
                    c["move"].append(o - cl)          # + = line moved against the depleted team (toward its opponent)
                    if r.get("tot_close") is not None:
                        c["over"].append(r["pts"] - r["tot_close"])
        print(f"\n=== {scope}: {len(rs)} games (a team counts as depleted only when missing more rotation players than its opponent)")
        print(f"  {'bucket':52} {'n':>5}  {'depleted ATS open':>18} {'depleted ATS close':>19}  {'opponent ATS close':>19}  {'line moved vs them':>18}  {'over at close':>15}")
        order = ["0 rotation players out", "1 out", "2 out", "3+ out", "2+ out at the SAME position", "2+ guards out",
                 "2+ wings out", "2+ bigs out", "2+ out, all different positions",
                 "2+ out, at least one FRESH (played the last game)", "2+ out, all LONG absences", "60+ rotation minutes out"]
        for lab in order:
            c = cats.get(lab)
            if not c or not c["dep_o"]:
                continue
            mv = sum(c["move"]) / len(c["move"])
            print(f"  {lab:52} {len(c['dep_o']):5}  {rec(c['dep_o']):>18} {rec(c['dep_c']):>19}  {rec(c['opp_c']):>19}  "
                  f"{mv:+18.2f}  {rec(c['over']):>15}")


if __name__ == "__main__":
    main()
