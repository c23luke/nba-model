"""OUR OWN TRENDS (Caden 2026-11-24): "now that you have an idea how they do it ... create your own".

Trends Center-style rules, but each one written down WITH A REASON before it was run (no mining), then checked on
6 seasons at the closing line (2020-21 to 2025-26; -110). Line-movement ideas need opening lines, which we only have
for 2024-25 and 2025-26, so they are checked on those two.
Caden's bar: 56%+ overall and no season under 53% (seasons with fewer than 5 bets skipped), plus 60+ bets so a
tiny slice can't pass.
LUCK CHECK: every idea is re-run 30 times with the results shuffled inside each season. The report says how many
ideas pass on shuffled results on average: that's how many "passes" luck alone gives from this many ideas.
Run: python -m engine.measure_trends_ours
"""
from __future__ import annotations

import json
import os
import random

from . import measure_trends as T
from . import mine as M
from . import personnel as P

MIN_N = 60
L = lambda c: c["last"] or {}
sub500 = lambda c: c["wp"] is not None and c["n"] >= 5 and c["wp"] < 0.5
over500 = lambda c: c["wp"] is not None and c["n"] >= 5 and c["wp"] > 0.5


def last_meeting(c, opp):
    for x in reversed(c["hist"]):
        if x["opp"] == opp:
            return x
    return None


# (name, reason, keep(row)) — we bet the team in the row
SPREADS = [
    ("Fade a team that covered 5 straight", "the market chases hot ATS teams and over-adjusts",
     lambda r: r["op"]["cs"] >= 5),
    ("Back a team that failed to cover 5 straight", "same overreaction, other side",
     lambda r: r["me"]["ncs"] >= 5),
    ("Fade a team that covered 3 straight by 10+ each", "lines move after blowout covers",
     lambda r: len([x for x in r["op"]["hist"][-3:] if x.get("cov") and x["margin"] + (x["line"] or 0) >= 10]) == 3),
    ("Revenge: lost to this opponent by 20+ last time, this season", "embarrassment + film; market anchors on the blowout",
     lambda r: (lm := last_meeting(r["me"], r["opp"])) is not None and lm["margin"] <= -20),
    ("Letdown: favorite of 7+ after a 25+ point win", "flat spot after a statement win; number inflated",
     lambda r: L(r["op"]).get("margin", 0) >= 25 and r["line"] >= 7),
    ("Back a rested team (2+ days) vs a team on its 4th game in 6 nights", "fatigue stacks over a week, not just one night",
     lambda r: (r["me"]["rest"] or 0) >= 2 and r["op"]["in6"] >= 4),
    ("Fade a team on its 3rd road game in 4 nights", "travel + no home bed",
     lambda r: r["home"] and r["op"]["in4"] >= 3 and r["op"]["stretch"] >= 3),
    ("Back a home team in its first game back after a 4+ game road trip, with 1+ day rest", "home bed, rested",
     lambda r: r["home"] and r["me"]["prev_road"] >= 4 and (r["me"]["rest"] or 0) >= 1),
    ("Fade a road team on the last game of a 5+ game road trip", "'getaway game', worn down",
     lambda r: r["home"] and r["op"]["stretch"] >= 5),
    ("Big underdog (+10 or more) that lost its last game by 20+", "market over-punishes a blowout loss",
     lambda r: r["line"] >= 10 and L(r["me"]).get("margin", 0) <= -20),
    ("Favorite after a loss as a 10+ point favorite", "bounce-back after an upset; market cools on them",
     lambda r: r["line"] < 0 and L(r["me"]).get("fav") and (L(r["me"]).get("line") or 0) <= -10 and not L(r["me"]).get("won")),
    ("Underdog vs a team that just won by 15+", "the number is inflated after a big win",
     lambda r: r["line"] > 0 and L(r["op"]).get("margin", 0) >= 15),
    ("Bad team (under .400) as a home underdog after 2+ days rest", "rested bad teams play hard at home",
     lambda r: r["home"] and r["line"] > 0 and r["me"]["wp"] is not None and r["me"]["n"] >= 10 and r["me"]["wp"] < 0.4
     and (r["me"]["rest"] or 0) >= 2),
    ("Good team (over .600) as an underdog", "market rarely makes good teams dogs; usually rest/injury noise",
     lambda r: r["line"] > 0 and r["me"]["wp"] is not None and r["me"]["n"] >= 10 and r["me"]["wp"] > 0.6),
    ("First 14 days: fade favorites of 8+", "early lines lean on last season; rosters changed",
     lambda r: r["first14"] and r["line"] >= 8),
    ("Team after an overtime LOSS, not on a back-to-back", "close loss, motivated, rested",
     lambda r: L(r["me"]).get("ot") and not L(r["me"]).get("won") and not r["me"]["b2b"]),
    ("Back a team whose opponent covered by 15+ last game", "market overreacts to one big cover",
     lambda r: (L(r["op"]).get("margin", 0) + (L(r["op"]).get("line") or 0)) >= 15),
    ("Home team on a back-to-back vs a rested road team (2+ days)", "the home edge can't cover tired legs",
     lambda r: not r["home"] and r["op"]["b2b"] and (r["me"]["rest"] or 0) >= 2),
    ("Road team after 3+ days rest", "rest helps more on the road",
     lambda r: not r["home"] and (r["me"]["rest"] or 0) >= 3),
]

TOTALS = [
    ("UNDER: both teams on a back-to-back", "tired legs, slower pace", lambda t: t["h"]["b2b"] and t["a"]["b2b"], False),
    ("UNDER: a team off an overtime game on a back-to-back", "extra minutes last night", lambda t: (t["h"]["b2b"] and L(t["h"]).get("ot")) or (t["a"]["b2b"] and L(t["a"]).get("ot")), False),
    ("UNDER: both teams' last 3 games went over", "the market chases overs", lambda t: all(x.get("over") for x in t["h"]["hist"][-3:]) and all(x.get("over") for x in t["a"]["hist"][-3:]) and len(t["h"]["hist"]) >= 3 and len(t["a"]["hist"]) >= 3, False),
    ("OVER: both teams' last 3 games went under", "same, other side", lambda t: len(t["h"]["hist"]) >= 3 and len(t["a"]["hist"]) >= 3 and all(x.get("over") is False for x in t["h"]["hist"][-3:]) and all(x.get("over") is False for x in t["a"]["hist"][-3:]), True),
    ("OVER: both teams rested 2+ days", "fresh legs, faster pace", lambda t: (t["h"]["rest"] or 0) >= 2 and (t["a"]["rest"] or 0) >= 2, True),
    ("UNDER: from March on, a bad team (under .400) at home", "tanking teams give minutes to young players (reason unsure)", lambda t: t["late"] and t["h"]["wp"] is not None and t["h"]["n"] >= 40 and t["h"]["wp"] < 0.4, False),
    ("UNDER: first 14 days of the season", "defenses ahead of offenses early; totals set off last season", lambda t: t["first14"], False),
    ("OVER: big spread (12+) and a low total (bottom quarter so far)", "garbage time scoring", lambda t: t["hs"] is not None and abs(t["hs"]) >= 12 and t["q3"] is not None and t["tot"] < t["q3"] - 10, True),
]


def judge(rs, won, seasons):
    w = sum(won(r) for r in rs)
    n = len(rs)
    ok = n >= MIN_N and w / n >= 0.56
    per = []
    for s in seasons:
        sub = [r for r in rs if r["season"] == s]
        sw = sum(won(r) for r in sub)
        per.append(f"{sw}-{len(sub) - sw}")
        if len(sub) >= 5 and sw / len(sub) < 0.53:
            ok = False
    return w, n, per, ok


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    rows, totals = [], []
    for s in M.SEASONS:
        r, t = T.build(s, key)
        rows += r
        totals += t
    seasons = list(M.SEASONS)
    print(f"{len(rows)} team-games, {len(totals)} totals, 6 seasons at the close. Bar: {MIN_N}+ bets, 56%+, no season under 53%.\n")

    def run(ideas, data, kind, shuffle=None):
        passes = 0
        out = []
        for idea in ideas:
            name, why, keep = idea[:3]
            over = idea[3] if len(idea) > 3 else None
            if kind == "spread":
                won = lambda r: r["_w"]
            else:
                won = (lambda t: t["_o"]) if over else (lambda t: not t["_o"])
            rs = [r for r in data if keep(r)]
            w, n, per, ok = judge(rs, won, seasons)
            passes += ok
            out.append((name, why, w, n, per, ok))
        return passes, out

    for r in rows:
        r["_w"] = r["win"]
    for t in totals:
        t["_o"] = t["over"]
    sp_pass, sp = run(SPREADS, rows, "spread")
    to_pass, to = run(TOTALS, totals, "total")
    for title, res in (("SPREADS (we bet the team described)", sp), ("TOTALS", to)):
        print(f"=== {title}")
        print("    seasons: " + "  ".join(s[2:] for s in seasons))
        for name, why, w, n, per, ok in res:
            pct = f"{w / n:.1%}" if n else "-"
            print(f"  {'PASSES' if ok else 'fails '}  {name}\n          why: {why}\n          {w}-{n - w} ({pct}, {w - 1.1 * (n - w):+.1f}u)   " + "  ".join(per))
        print()

    # luck check: shuffle results inside each season, count passes
    rng = random.Random(7)
    fake = []
    for i in range(30):
        for s in seasons:
            a = [r["win"] for r in rows if r["season"] == s]
            rng.shuffle(a)
            it = iter(a)
            for r in rows:
                if r["season"] == s:
                    r["_w"] = next(it)
            b = [t["over"] for t in totals if t["season"] == s]
            rng.shuffle(b)
            it = iter(b)
            for t in totals:
                if t["season"] == s:
                    t["_o"] = next(it)
        fake.append(run(SPREADS, rows, "spread")[0] + run(TOTALS, totals, "total")[0])
    print(f"=== LUCK CHECK: real ideas passing: {sp_pass + to_pass} of {len(SPREADS) + len(TOTALS)}. "
          f"On shuffled results, 30 times: average {sum(fake) / len(fake):.2f} pass (max {max(fake)}). "
          "Real passes well above that are worth tracking; at or below it, they could be luck.")

    # line movement ideas (2 seasons with opening lines)
    print("\n=== LINE MOVEMENT (2024-25 and 2025-26 only: the seasons with opening lines), graded at the close")
    for s in ("2024-25", "2025-26"):
        tag = s.replace("-", "_")
        sp_oc = json.loads((P.STATIC / f"odds_openclose_{tag}.json").read_text())
        to_oc = json.loads((P.STATIC / f"odds_totals_{tag}.json").read_text())
        mv = {k: (v.get("close") - v.get("open")) for k, v in sp_oc.items() if v.get("open") is not None and v.get("close") is not None}
        tm = {k: (v.get("close") - v.get("open")) for k, v in to_oc.items() if v.get("open") is not None and v.get("close") is not None}
        for r in rows:
            if r["season"] == s:
                k = f"{r['day'].isoformat()}|{r['opp'] if r['home'] else r['team']}|{r['team'] if r['home'] else r['opp']}"
                m = mv.get(k)
                r["_mv"] = None if m is None else (-m if r["home"] else m)    # + = line moved toward this team
        for t in totals:
            if t["season"] == s:
                t["_tm"] = tm.get(f"{t['day'].isoformat()}|{t['away']}|{t['home']}")
    two = [r for r in rows if r["season"] in ("2024-25", "2025-26") and r.get("_mv") is not None]
    tt = [t for t in totals if t["season"] in ("2024-25", "2025-26") and t.get("_tm") is not None]
    ideas = [("Line moved 1.5+ toward the team (sharp money)", lambda r: r["_mv"] >= 1.5, two, lambda r: r["win"]),
             ("Line moved 2.5+ toward the team", lambda r: r["_mv"] >= 2.5, two, lambda r: r["win"]),
             ("Line moved 2.5+ toward an underdog", lambda r: r["_mv"] >= 2.5 and r["line"] > 0, two, lambda r: r["win"]),
             ("Line moved 2.5+ toward a favorite", lambda r: r["_mv"] >= 2.5 and r["line"] < 0, two, lambda r: r["win"]),
             ("Total dropped 3+ -> under", lambda t: t["_tm"] <= -3, tt, lambda t: not t["over"]),
             ("Total rose 3+ -> over", lambda t: t["_tm"] >= 3, tt, lambda t: t["over"]),
             ("Total rose 3+ -> under (fade the move)", lambda t: t["_tm"] >= 3, tt, lambda t: not t["over"])]
    for name, keep, data, won in ideas:
        rs = [x for x in data if keep(x)]
        w = sum(won(x) for x in rs)
        n = len(rs)
        per = "  ".join(f"{s[2:]}: {sum(won(x) for x in rs if x['season'] == s)}-{sum(not won(x) for x in rs if x['season'] == s)}"
                        for s in ("2024-25", "2025-26"))
        print(f"  {name:52} {w}-{n - w} ({(w / n if n else 0):.1%}, {w - 1.1 * (n - w):+.1f}u)   {per}")


if __name__ == "__main__":
    main()
