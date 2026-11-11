"""TEST THE BOTTOM-UP PROPS MODEL (engine/prop_model.py) WITHOUT SPENDING CREDITS.

Walk forward through 2024-25 and 2025-26: for every player who plays (with 5+ games of his own already this season),
build the features using ONLY games before tonight (plus tonight's closing spread and total, and who is out, which
is known by tip), project minutes / points / rebounds / assists, and compare with what he actually did.
Baselines = what a basic book starts from: his last-10 average and his season average.
Weights are tuned on 2024-25 (coordinate search on the sum of points + rebounds + assists errors) and TESTED
untouched on 2025-26. Then each piece is switched off one at a time on 2025-26 to see what it's worth.
Also: the share of player-games where the model and his last-10 average disagree by 3+ points, and who was closer
there (that's where prop bets would come from).
Run: python -m engine.measure_prop_model
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

from . import backtest as BT
from . import backtest_open as BO
from . import personnel as PERS
from . import sources
from .prop_model import STATS, History, P, project
from .teams import code


def box(js: dict):
    """[(team, name, pos, min, pts, reb, ast)] for everyone listed."""
    out = []
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        for a in st.get("athletes", []):
            ath = a.get("athlete") or {}
            d = dict(zip(keys, a.get("stats") or []))

            def n(k):
                try:
                    return int(str(d.get(k) or "0").split(":")[0] or 0)
                except ValueError:
                    return 0
            m = 0 if a.get("didNotPlay") else n("minutes")
            out.append((team, ath.get("displayName", ""), (ath.get("position") or {}).get("abbreviation") or "",
                        m, n("points") if m else 0, n("rebounds") if m else 0, n("assists") if m else 0))
    return out


def shots(js: dict, teams_by_id: dict, names_by_id: dict):
    """[(team, name, zone, points)] from ESPN play-by-play: every field-goal attempt with a court location."""
    from .prop_model import zone
    out = []
    for pl in js.get("plays") or []:
        if not pl.get("shootingPlay"):
            continue
        txt = (pl.get("text") or "").lower()
        if "free throw" in txt:
            continue
        c = pl.get("coordinate") or {}
        parts = pl.get("participants") or []
        if c.get("x") is None or c.get("y") is None or not parts:
            continue
        aid = str((parts[0].get("athlete") or {}).get("id"))
        nm, tm = names_by_id.get(aid), teams_by_id.get(aid)
        if not nm or not tm or c["x"] < 0 or c["y"] < 0 or c["y"] > 47:
            continue
        three = "three point" in txt or (pl.get("scoreValue") == 3)
        out.append((tm, nm, zone(float(c["x"]), float(c["y"]), three), int(pl.get("scoreValue") or 0) if pl.get("scoringPlay") else 0))
    return out


def ids(js: dict):
    t_, n_ = {}, {}
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        for a in (t["statistics"][0].get("athletes") or []):
            ath = a.get("athlete") or {}
            t_[str(ath.get("id"))] = team
            n_[str(ath.get("id"))] = ath.get("displayName", "")
    return t_, n_


def avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def features(season):
    cfg = BO.SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]
    games.sort(key=lambda g: (g.game_date, str(g.id)))
    with ThreadPoolExecutor(12) as ex:
        sums = dict(zip([g.id for g in games], ex.map(lambda g: BT._safe(sources.get_json, BT.SUM.format(g.id)) or {}, games)))
    pos = {}
    sp = json.loads((PERS.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    tt = json.loads((PERS.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())

    H = History(pos)
    out = []
    for g in games:
        rows = box(sums.get(g.id) or {})
        if not rows:
            continue
        k = f"{g.game_date.isoformat()}|{g.away}|{g.home}"
        hs = (sp.get(k) or {}).get("close")
        gt = (tt.get(k) or {}).get("close")
        tonight = defaultdict(dict)
        for team, name, ps, m, pts, reb, ast in rows:
            tonight[team][name] = (m, pts, reb, ast)
            if ps:
                pos[name] = ps
        for team in (g.home, g.away):
            opp = g.away if team == g.home else g.home
            playing = {nm for nm, v in tonight[team].items() if v[0] > 0}
            known = {nm for gm in H.tgames[team][-10:] for nm in gm} | set(tonight[team])
            for f in H.features(team, opp, playing, known - playing, hs, gt, team == g.home):
                f["season"] = season
                for i, s in enumerate(STATS, start=1):
                    f[f"{s}_act"] = tonight[team][f["name"]][i]
                f["min_act"] = tonight[team][f["name"]][0]
                out.append(f)
        tb, nb = ids(sums.get(g.id) or {})
        H.add_shots(g.home, g.away, shots(sums.get(g.id) or {}, tb, nb))
        H.add(g.home, g.away, tonight)
    return out


def errors(rows, p):
    e = {s: 0.0 for s in STATS}
    e["min"] = 0.0
    for f in rows:
        pr = project(f, p)
        e["min"] += abs(pr["min"] - f["min_act"])
        for s in STATS:
            e[s] += abs(pr[s] - f[f"{s}_act"])
    n = len(rows) or 1
    return {k: v / n for k, v in e.items()}


def score(e):
    return e["pts"] + e["reb"] + e["ast"]


def base_err(rows, key):
    n = len(rows) or 1
    out = {s: sum(abs(f[f"{s}_{key}"] - f[f"{s}_act"]) for f in rows) / n for s in STATS}
    out["min"] = sum(abs((f["m10"] if key == "l10avg" else f["mseason"]) - f["min_act"]) for f in rows) / n
    return out


GRID = {"w5": [0.2, 0.4, 0.6], "w10": [0.2, 0.3, 0.4], "split_trust": [0.3, 0.6, 0.9], "share_trust": [0.0, 0.3, 0.6],
        "rate_recent": [0.3, 0.5, 0.7], "shrink_min": [50.0, 150.0, 400.0], "usage_k": [0.0, 0.5, 1.0],
        "team_total_exp": [0.0, 0.5, 1.0], "game_total_exp": [0.0, 0.5, 1.0], "opp_w": [0.0, 0.5, 1.0],
        "opp_shrink": [5.0, 10.0, 25.0], "luck_l": [0.0, 0.25, 0.5, 0.75], "match_w": [0.0, 0.5, 1.0, 1.5]}


def tune(rows):
    from .prop_model import TUNED
    p = TUNED
    best = score(errors(rows, p))
    for _ in range(2):
        for k, vals in GRID.items():
            for v in vals:
                q = replace(p, **{k: v})
                if q.w5 + q.w10 > 0.95:
                    continue
                sc = score(errors(rows, q))
                if sc < best - 1e-6:
                    best, p = sc, q
    return p


def line(name, e):
    return f"  {name:44} min {e['min']:5.2f}   pts {e['pts']:5.2f}   reb {e['reb']:5.2f}   ast {e['ast']:5.2f}"


def report(rows, p, label):
    print(f"\n=== {label}: {len(rows)} player-games (average miss; lower is better)")
    print(line("last-10 average (a basic book's start)", base_err(rows, "l10avg")))
    print(line("season average", base_err(rows, "savg")))
    print(line("OUR MODEL", errors(rows, p)))
    subsets = [("a rotation teammate freshly out", lambda f: f["fresh_out"] > 0),
               ("2+ rotation teammates freshly out", lambda f: f["fresh_out"] >= 2),
               ("returning after 3+ games out", lambda f: f["returning"]),
               ("spread 12+", lambda f: (f["abs_spread"] or 0) >= 12),
               ("bench (under 20 mpg)", lambda f: f["m10"] < 20), ("starters (30+ mpg)", lambda f: f["m10"] >= 30)]
    for nm, fn in subsets:
        rs = [f for f in rows if fn(f)]
        if rs:
            print(f"  -- {nm} ({len(rs)})")
            print(line("     last-10 average", base_err(rs, "l10avg")))
            print(line("     OUR MODEL", errors(rs, p)))
    # where the model and the last-10 average disagree on points by 3+: who was closer?
    for s, cut in (("pts", 3.0), ("reb", 1.5), ("ast", 1.5)):
        dis = [(project(f, p)[s], f) for f in rows]
        dis = [(m, f) for m, f in dis if abs(m - f[f"{s}_l10avg"]) >= cut]
        if dis:
            closer = sum(abs(m - f[f"{s}_act"]) < abs(f[f"{s}_l10avg"] - f[f"{s}_act"]) for m, f in dis)
            right_side = sum((f[f"{s}_act"] - f[f"{s}_l10avg"]) * (m - f[f"{s}_l10avg"]) > 0 for m, f in dis)
            print(f"  disagree with last-10 on {s} by {cut}+: {len(dis)} ({len(dis) / len(rows):.0%}); model closer {closer / len(dis):.0%}; "
                  f"actual landed on the model's side of the last-10 average {right_side / len(dis):.0%}")


def main():
    rows = {s: features(s) for s in BO.SEASONS}
    train, test = rows["2024-25"], rows["2025-26"]
    p = tune(train)
    print("TUNED on 2024-25:", {k: getattr(p, k) for k in GRID})
    report(train, p, "2024-25 (tuned here)")
    report(test, p, "2025-26 (untouched test)")
    print("\n=== what each piece is worth on 2025-26 (sum of pts+reb+ast miss; + = worse without it)")
    full = score(errors(test, p))
    for nm, q in (("minutes: absences (history + share-out)", replace(p, split_trust=0.0, share_trust=0.0)),
                  ("minutes: returning star", replace(p, returning=False)),
                  ("minutes: blowout", replace(p, blowout=False)),
                  ("rate: usage vacuum", replace(p, usage_k=0.0)),
                  ("context: market team total", replace(p, team_total_exp=0.0)),
                  ("context: market game total", replace(p, game_total_exp=0.0)),
                  ("context: opponent by position", replace(p, opp_w=0.0)),
                  ("shots: shooting luck", replace(p, luck_l=0.0)),
                  ("shots: shot diet vs the opponent's zones", replace(p, match_w=0.0))):
        print(f"  without {nm:42} {score(errors(test, q)) - full:+.4f}")


if __name__ == "__main__":
    main()
