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
from .prop_model import STATS, P, group, project
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
    sp = json.loads((PERS.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    tt = json.loads((PERS.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())

    plog = defaultdict(list)          # player -> [(min, pts, reb, ast)] games he played, oldest first
    pos = {}
    tgames = defaultdict(list)        # team -> [{name: (min, pts, reb, ast)}] oldest first
    tpts = defaultdict(list)          # team -> points scored per game
    allowed = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))   # team -> group -> [min, pts, reb, ast] allowed
    allowed_n = defaultdict(int)
    league = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])                         # group -> [min, pts, reb, ast]
    league_tot = []
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
        lt = avg(league_tot) if len(league_tot) >= 20 else None
        for team in (g.home, g.away):
            opp = g.away if team == g.home else g.home
            past = tgames[team]
            if len(past) < 5:
                continue
            last10 = past[-10:]
            mins = defaultdict(list)
            for gm in last10:
                for nm, v in gm.items():
                    mins[nm].append(v[0])
            rot = {nm: sum(v) / len(last10) for nm, v in mins.items()
                   if len([x for x in v if x > 0]) >= 5 and sum(v) / len(last10) >= 20}
            played_now = {nm for nm, v in tonight[team].items() if v[0] > 0}
            prev = past[-1]
            fresh = sorted([a for a in rot if a not in played_now and (prev.get(a) or (0,))[0] > 0], key=lambda a: -rot[a])
            # each fresh absentee's share of the team's points / rebounds / assists over the last 10 team games
            tot = [sum(v[i] for gm in last10 for v in gm.values()) or 1 for i in (1, 2, 3)]
            ab_share = [sum(gm.get(a, (0, 0, 0, 0))[i] for gm in last10 for a in fresh) / tot[i - 1] for i in (1, 2, 3)]
            mpg_now = {nm: avg([x[0] for x in plog[nm][-10:]]) for nm in played_now if len(plog[nm]) >= 1}
            denom = sum(mpg_now.values()) or 1
            absent_min = sum(rot[a] for a in fresh)
            if hs is not None and gt is not None:
                home_tt = (gt - hs) / 2
                team_total = home_tt if team == g.home else gt - home_tt
            else:
                team_total = None
            spread = None if hs is None else (hs if team == g.home else -hs)
            for nm in played_now:
                lg = plog[nm]
                if len(lg) < 5:
                    continue
                grp = group(pos.get(nm, ""))
                l10 = lg[-10:]
                f = {"name": nm, "team": team, "grp": grp, "season": season,
                     "m5": avg([x[0] for x in lg[-5:]]), "m10": avg([x[0] for x in l10]), "mseason": avg([x[0] for x in lg]),
                     "min_season": sum(x[0] for x in lg), "fresh_out": len(fresh), "abs_spread": None if spread is None else abs(spread),
                     "team_total": team_total, "team_avg": avg(tpts[team]) if len(tpts[team]) >= 3 else None,
                     "game_total": gt, "league_total": lt, "opp_games": allowed_n[opp]}
                for i, s in enumerate(STATS, start=1):
                    m10 = sum(x[0] for x in l10) or 1
                    ms = sum(x[0] for x in lg) or 1
                    f[f"{s}_r10"] = sum(x[i] for x in l10) / m10
                    f[f"{s}_rs"] = sum(x[i] for x in lg) / ms
                    L = league[grp]
                    f[f"{s}_rpos"] = L[i] / L[0] if L[0] else f[f"{s}_rs"]
                    A = allowed[opp][grp]
                    f[f"{s}_opp"] = (A[i] / A[0]) / (L[i] / L[0]) if A[0] > 100 and L[0] and L[i] else None
                    f[f"{s}_absent_share"] = ab_share[i - 1]
                    f[f"{s}_l10avg"] = avg([x[i] for x in l10])
                    f[f"{s}_savg"] = avg([x[i] for x in lg])
                    f[f"{s}_act"] = tonight[team][nm][i]
                f["min_act"] = tonight[team][nm][0]
                # minutes: real history without the biggest fresh absentee, else the naive share-out
                f["split_gain"] = None
                for a in fresh:
                    w = [gm[nm][0] for gm in past if (gm.get(nm) or (0,))[0] > 0 and (gm.get(a) or (0,))[0] > 0]
                    wo = [gm[nm][0] for gm in past if (gm.get(nm) or (0,))[0] > 0 and not (gm.get(a) or (0,))[0] > 0]
                    if len(wo) >= 2 and w:
                        f["split_gain"] = avg(wo) - avg(w)
                        break
                f["share_gain"] = absent_min * mpg_now.get(nm, 0) / denom if fresh else 0.0
                # returning star: missed his team's last 3+ games, 28+ mpg before
                streak = 0
                for gm in reversed(past):
                    if (gm.get(nm) or (0,))[0] > 0:
                        break
                    streak += 1
                f["returning"] = streak if streak >= 3 and f["mseason"] >= 28 else None
                out.append(f)
        # update history with tonight
        for team in (g.home, g.away):
            opp = g.away if team == g.home else g.home
            gm = tonight[team]
            tgames[team].append(gm)
            tpts[team].append(sum(v[1] for v in gm.values()))
            for nm, v in gm.items():
                if v[0] > 0:
                    plog[nm].append(v)
                    grp = group(pos.get(nm, ""))
                    A = allowed[opp][grp]
                    for i in range(4):
                        A[i] += v[i]
                        league[grp][i] += v[i]
            allowed_n[opp] += 1
        league_tot.append(sum(v[1] for t in tonight.values() for v in t.values()))
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
        "opp_shrink": [5.0, 10.0, 25.0]}


def tune(rows):
    p = P()
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
                  ("context: opponent by position", replace(p, opp_w=0.0))):
        print(f"  without {nm:42} {score(errors(test, q)) - full:+.4f}")


if __name__ == "__main__":
    main()
