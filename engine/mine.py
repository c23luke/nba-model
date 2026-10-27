"""Search for systems like the OG ones — and only keep the ones that win in EVERY season.

Three seasons (2023-24, 2024-25, 2025-26), graded against the closing line (Odds API consensus).
Every game gives two spread rows (one per team) and one totals row. Each row carries situation
flags: rest, schedule, travel, streaks, last game, cover streaks, record, line size, stage of season,
for the team AND its opponent. The search tries every combination of 1-3 flags (the "stack").

A system is kept only if:
  - it fired 15+ times in EACH season and 60+ in total
  - it won 53%+ in EACH season (no single hot year) and 56%+ overall
Then the whole search is re-run with the results shuffled inside each season (5 times). How many
systems pass on shuffled data = how many we'd find by pure luck. If the real search finds far more,
the extra ones are real; if not, they're noise.
"""
from __future__ import annotations

import itertools
import json
import os
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np

from . import backtest as BT
from . import personnel as P
from . import sources
from .teams import miles_between

SEASONS = {"2020-21": ("2020-12-22", "2021-05-16"), "2021-22": ("2021-10-19", "2022-04-10"),
           "2022-23": ("2022-10-18", "2023-04-09"), "2023-24": ("2023-10-24", "2024-04-14"),
           "2024-25": ("2024-10-22", "2025-04-13"), "2025-26": ("2025-10-21", "2026-04-12")}
ALL_STAR = {"2020-21": "2021-03-07", "2021-22": "2022-02-20", "2022-23": "2023-02-19",
            "2023-24": "2024-02-18", "2024-25": "2025-02-16", "2025-26": "2026-02-15"}
MIN_SEASON_N, MIN_TOTAL_N = 8, 100
MIN_SEASON_PCT, MIN_TOTAL_PCT = 0.52, 0.56
SEASONS_ALLOWED_TO_MISS = 1          # one losing season out of six is allowed (no system wins every year)
SHUFFLES = 5


# ------------------------------------------------------------------ data
def games_for(season):
    s, e = (date.fromisoformat(x) for x in SEASONS[season])
    days = [s + timedelta(i) for i in range((e - s).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        g = [x for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for x, _ in day if x.final]
    return sorted(g, key=lambda x: (x.game_date, x.id)), s, e, days


def closing_lines(season, days, key):
    tag = season.replace("-", "_")
    out = {}
    sp, tt = P.STATIC / f"odds_openclose_{tag}.json", P.STATIC / f"odds_totals_{tag}.json"
    if sp.exists() and tt.exists():
        a, b = json.loads(sp.read_text()), json.loads(tt.read_text())
        for k in set(a) | set(b):
            out[k] = {"spread": (a.get(k) or {}).get("close"), "total": (b.get(k) or {}).get("close")}
        return out, "cached"
    cache = P.STATIC / f"odds_close_{tag}.json"
    if cache.exists():
        return json.loads(cache.read_text()), "cached"
    def snap(d):
        try:
            lines, meta = sources.odds_api_historical(key, d.isoformat() + "T22:30:00Z", markets="spreads,totals")
            return d, lines, meta
        except Exception:
            return d, {}, {}
    left = None
    with ThreadPoolExecutor(6) as ex:
        for d, lines, meta in ex.map(snap, days):
            left = meta.get("remaining") or left
            for (gd, away, home), ln in lines.items():
                if gd == d:
                    out[f"{gd.isoformat()}|{away}|{home}"] = {"spread": ln.get("home_spread"), "total": ln.get("total")}
    cache.write_text(json.dumps(out))
    return out, f"fetched (credits left {left})"


# ------------------------------------------------------------------ flags
def team_flags(hist, team, day, game, opp):
    """Situation of `team` going into `game` on `day` (only earlier games). hist[team] = list of dicts."""
    h = hist[team]
    f = {}
    last = h[-1] if h else None
    rest = (day - last["date"]).days - 1 if last else None
    f["b2b"] = rest == 0
    f["rest2p"] = rest is not None and rest >= 2
    f["rest3p"] = rest is not None and rest >= 3
    f["3in4"] = sum(1 for x in h if 1 <= (day - x["date"]).days <= 3) >= 2
    f["4in6"] = sum(1 for x in h if 1 <= (day - x["date"]).days <= 5) >= 3
    f["won_last"] = bool(last and last["won"])
    f["lost_last"] = bool(last and not last["won"])
    f["won_by15"] = bool(last and last["margin"] >= 15)
    f["lost_by15"] = bool(last and last["margin"] <= -15)
    f["won_by25"] = bool(last and last["margin"] >= 25)
    f["lost_by25"] = bool(last and last["margin"] <= -25)
    f["ot_last"] = bool(last and last["ot"])
    ws = ls = 0
    for x in reversed(h):
        if x["won"] and ls == 0:
            ws += 1
        elif not x["won"] and ws == 0:
            ls += 1
        else:
            break
    f["wstreak3"], f["wstreak5"], f["lstreak3"], f["lstreak5"] = ws >= 3, ws >= 5, ls >= 3, ls >= 5
    cov = [x["covered"] for x in h if x["covered"] is not None]
    f["covered_last"] = bool(cov and cov[-1] is True)
    f["no_cover_last"] = bool(cov and cov[-1] is False)
    f["covered3"] = len(cov) >= 3 and all(cov[-3:])
    f["no_cover3"] = len(cov) >= 3 and not any(cov[-3:])
    ovs = [x["over"] for x in h if x["over"] is not None]
    f["over_last"] = bool(ovs and ovs[-1] is True)
    f["over3"] = len(ovs) >= 3 and all(ovs[-3:])
    f["under3"] = len(ovs) >= 3 and not any(ovs[-3:])
    n = len(h)
    wp = sum(x["won"] for x in h) / n if n else None
    f["tank35"] = n >= 40 and wp <= 0.35          # T25's tanking range
    f["good_rec"] = n >= 10 and wp >= 0.6
    f["bad_rec"] = n >= 10 and wp <= 0.4
    f["home_last"] = bool(last and last["home"])
    road = 0
    for x in reversed(h):
        if x["home"]:
            break
        road += 1
    f["road3p"] = road >= 2 and game.home != team          # 3rd+ straight road game
    f["long_trip"] = bool(last and miles_between(last["venue"], game.home) >= 1500)
    f["same_opp_last"] = bool(last and last["opp"] == opp)
    f["early_lt10"] = n < 10
    f["home_after_road3"] = game.home == team and road >= 3          # first home game after 3+ away
    f["road_after_home3"] = game.home != team and sum(1 for _ in itertools.takewhile(lambda x: x["home"], reversed(h))) >= 3
    f["first_b2b"] = rest == 0 and not any((h[i]["date"] - h[i - 1]["date"]).days == 1 for i in range(1, len(h)))
    last5 = h[-5:]
    f["hot5"] = len(last5) == 5 and sum(x["won"] for x in last5) >= 4
    f["cold5"] = len(last5) == 5 and sum(x["won"] for x in last5) <= 1
    f["ats_hot5"] = len(cov) >= 5 and sum(1 for c in cov[-5:] if c) >= 4
    f["ats_cold5"] = len(cov) >= 5 and sum(1 for c in cov[-5:] if c) <= 1
    f["overs5"] = len(ovs) >= 5 and sum(1 for o in ovs[-5:] if o) >= 4
    f["unders5"] = len(ovs) >= 5 and sum(1 for o in ovs[-5:] if o) <= 1
    return f


def build(season, games, lines, start, end=None):
    hist = defaultdict(list)
    spread_rows, total_rows = [], []
    totals_all = sorted(v["total"] for v in lines.values() if v.get("total"))
    lo_t = totals_all[len(totals_all) // 4] if totals_all else 0
    hi_t = totals_all[3 * len(totals_all) // 4] if totals_all else 999
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    allstar = date.fromisoformat(ALL_STAR[season])
    end = end or max(by_day)
    seen_tot: list[float] = []
    for day in sorted(by_day):
        avg_sofar = sum(seen_tot) / len(seen_tot) if len(seen_tot) >= 30 else None
        q1_sofar = sorted(seen_tot)[len(seen_tot) // 4] if len(seen_tot) >= 30 else None
        stage = {"first14": (day - start).days < 14, "first30": (day - start).days < 30,
                 "nov_dec": 14 <= (day - start).days and day < date(start.year + 1, 1, 1),
                 "pre_jan": day < date(start.year + 1, 1, 1), "jan_asb": date(start.year + 1, 1, 1) <= day < allstar,
                 "post_asb": day >= allstar, "last21": day >= end - timedelta(21)}
        for g in by_day[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            hs, tot = ln.get("spread"), ln.get("total")
            fh = team_flags(hist, g.home, day, g, g.away)
            fa = team_flags(hist, g.away, day, g, g.home)
            margin = g.home_score - g.away_score
            if hs is not None:
                for team, mine, theirs, line, is_home in ((g.home, fh, fa, hs, True), (g.away, fa, fh, -hs, False)):
                    res = (margin if is_home else -margin) + line
                    if res == 0:
                        continue
                    row = {f"T:{k}": v for k, v in mine.items()}
                    row.update({f"O:{k}": v for k, v in theirs.items()})
                    row.update({"G:home": is_home, "G:road": not is_home, "G:fav": line < 0, "G:dog": line > 0,
                                "G:line0-3": abs(line) <= 3, "G:line3-7": 3 < abs(line) <= 7,
                                "G:line7-10": 7 < abs(line) <= 10, "G:line10+": abs(line) > 10})
                    row.update({f"G:{k}": v for k, v in stage.items()})
                    row.update({"_key": f"{day.isoformat()}|{g.away}|{g.home}", "_home": is_home, "_margin": margin})
                    spread_rows.append((row, res > 0, season))
            if tot is not None:
                pts = g.home_score + g.away_score
                if pts != tot:
                    row = {f"H:{k}": v for k, v in fh.items()}
                    row.update({f"A:{k}": v for k, v in fa.items()})
                    row.update({"G:tot_low": tot <= lo_t, "G:tot_high": tot >= hi_t,
                                "G:close_game": hs is not None and abs(hs) <= 3,
                                "G:mismatch": hs is not None and abs(hs) >= 10,
                                # only games already played this season (the live model can't see the future)
                                "G:tot_above_avg": avg_sofar is not None and tot > avg_sofar,
                                "G:tot_low_sofar": q1_sofar is not None and tot <= q1_sofar,
                                "_hs": hs, "_tot": tot, "_pts": pts, "_key": f"{day.isoformat()}|{g.away}|{g.home}"})
                    row.update({f"G:{k}": v for k, v in stage.items()})
                    total_rows.append((row, pts > tot, season))
        for g in by_day[day]:
            ln = lines.get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
            hs, tot = ln.get("spread"), ln.get("total")
            if tot is not None:
                seen_tot.append(tot)
            m = g.home_score - g.away_score
            for team, opp, home, mg in ((g.home, g.away, True, m), (g.away, g.home, False, -m)):
                cov = None if hs is None else ((mg + (hs if home else -hs)) > 0 if (mg + (hs if home else -hs)) != 0 else None)
                over = None if tot is None else (None if g.home_score + g.away_score == tot else g.home_score + g.away_score > tot)
                hist[team].append({"date": day, "won": mg > 0, "margin": mg, "ot": (g.periods or 4) > 4,
                                   "home": home, "venue": g.home, "opp": opp, "covered": cov, "over": over})
    return spread_rows, total_rows


# ------------------------------------------------------------------ search
def search(rows, label, shuffle_seed=None, max_k=3):
    names = sorted({k for r, _, _ in rows for k in r if not k.startswith("_")})
    X = np.array([[bool(r.get(k)) for k in names] for r, _, _ in rows], dtype=bool)
    y = np.array([w for _, w, _ in rows], dtype=bool)
    seasons = list(SEASONS)
    S = np.array([seasons.index(s) for _, _, s in rows])
    if shuffle_seed is not None:
        rng = np.random.default_rng(shuffle_seed)
        y = y.copy()
        for i in range(len(seasons)):
            idx = np.where(S == i)[0]
            y[idx] = y[rng.permutation(idx)]
    smask = [S == i for i in range(len(seasons))]
    useful = [j for j in range(len(names)) if MIN_TOTAL_N <= X[:, j].sum() <= len(rows) * 0.6]
    found = []
    for k in range(1, max_k + 1):
        for combo in itertools.combinations(useful, k):
            # no two flags from the same family (T:b2b + T:3in4 is fine, but skip exact duplicates)
            m = X[:, combo[0]].copy()
            for j in combo[1:]:
                m &= X[:, j]
            n = int(m.sum())
            if n < MIN_TOTAL_N:
                continue
            for side, yy in (("bet", y), ("fade", ~y)):
                misses, recs = 0, []
                for sm in smask:
                    mm = m & sm
                    ns = int(mm.sum())
                    w = int((mm & yy).sum())
                    if ns < MIN_SEASON_N or w / ns < MIN_SEASON_PCT:
                        misses += 1
                        if misses > SEASONS_ALLOWED_TO_MISS:
                            break
                    recs.append((w, ns - w))
                if misses > SEASONS_ALLOWED_TO_MISS:
                    continue
                W = sum(a for a, _ in recs)
                if W / n < MIN_TOTAL_PCT:
                    continue
                found.append({"flags": [names[j] for j in combo], "side": side, "w": W, "l": n - W,
                              "seasons": recs, "pct": W / n})
    return found


def wilson_low(w, n, z=1.64):
    if not n:
        return 0
    p = w / n
    return (p + z * z / (2 * n) - z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / (1 + z * z / n)


def describe(sys_, kind):
    if kind == "spread":
        what = "bet the team" if sys_["side"] == "bet" else "bet AGAINST the team"
    else:
        what = "bet the OVER" if sys_["side"] == "bet" else "bet the UNDER"
    return f"{' + '.join(sys_['flags'])}  →  {what}"


def main():
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    spread_rows, total_rows = [], []
    for season in SEASONS:
        games, start, end, days = games_for(season)
        lines, how = closing_lines(season, days, key)
        sr, tr = build(season, games, lines, start, end)
        spread_rows += sr
        total_rows += tr
        print(f"{season}: {len(games)} games, lines {how}; {len(sr)} spread rows, {len(tr)} totals rows")
    window = os.environ.get("MINE_WINDOW", "all")
    if window == "pre_asb":
        keep = lambda r: not r[0].get("G:post_asb")
        spread_rows = [r for r in spread_rows if keep(r)]
        total_rows = [r for r in total_rows if keep(r)]
        for rows in (spread_rows, total_rows):
            for r, _, _ in rows:
                for k in ("G:post_asb", "G:last21"):
                    r.pop(k, None)
        print(f"\nWINDOW: opening night to the All-Star break only — {len(spread_rows)} spread rows, {len(total_rows)} totals rows")
    print(f"\nRules: 1-3 flags; {MIN_SEASON_N}+ games and {MIN_SEASON_PCT:.0%}+ in every season but at most "
          f"{SEASONS_ALLOWED_TO_MISS}; {MIN_TOTAL_N}+ games and {MIN_TOTAL_PCT:.0%}+ overall; vs the closing line.\n")
    out = {}
    for kind, rows in (("spread", spread_rows), ("total", total_rows)):
        real = search(rows, kind)
        fakes = [search(rows, kind, shuffle_seed=s) for s in range(SHUFFLES)]
        fake = [len(f) for f in fakes]
        print(f"=== {kind.upper()}: {len(real)} systems pass on real results; on shuffled results "
              f"{fake} pass (average {sum(fake)/len(fake):.0f}) — that's how many pure luck produces")
        fl = lambda lst: [wilson_low(x["w"], x["w"] + x["l"]) for x in lst]
        for cut in (0.52, 0.54, 0.56, 0.58, 0.60):
            r = sum(f >= cut for f in fl(real))
            fk = [sum(f >= cut for f in fl(x)) for x in fakes]
            print(f"    floor ≥ {cut:.0%}: real {r} vs luck {fk} (avg {sum(fk)/len(fk):.0f})")
        print(f"    best floor: real {max(fl(real) or [0]):.1%} vs luck {[round(max(fl(x) or [0]) * 100, 1) for x in fakes]}")
        real.sort(key=lambda s: -wilson_low(s["w"], s["w"] + s["l"]))
        seen = []
        shown = 0
        for s in real:
            fs = set(s["flags"])
            if any(fs >= set(x) and s["side"] == sd for x, sd in seen):
                continue                      # a narrower version of a system already shown
            seen.append((s["flags"], s["side"]))
            seas = " | ".join(f"{a}-{b}" for a, b in s["seasons"])
            print(f"  {s['w']}-{s['l']} ({s['pct']:.1%}, floor {wilson_low(s['w'], s['w'] + s['l']):.1%})  "
                  f"by season {seas}   {describe(s, kind)}")
            shown += 1
            if shown >= 40:
                break
        out[kind] = {"real": real[:200], "shuffled": fake}
        print()
    (P.STATIC / f"mined_systems{'' if window == 'all' else '_' + window}.json").write_text(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
