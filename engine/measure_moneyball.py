"""The "Moneyball" list, tested: what the market might be pricing wrong.

A. Shooting luck. A team's results this season feed its rating (engine/results_adj.py). Whether
   opponents hit their threes is mostly luck; so is free-throw shooting. Variants remove that luck from
   each game's miss before it counts: opponents' threes only / both teams' threes / threes + free throws.
   Also: blowouts capped (a 30-point loss counts as 15 or 20), since garbage time inflates margins.
   Each variant CHOSEN on 2024-25, TESTED on 2025-26, graded like the bet (players gap 3+ vs the opener).
B. Popular teams (LAL, GSW, BOS, NYK): against the spread as favorites / overall. 2 seasons at the
   opener, 6 seasons at the close.
C. Referee crews and totals. ESPN lists each game's officials. Each referee carries a running record of
   how far totals in his games finished over/under the opening total (only games before this one);
   the crew's average (shrunk) predicts over/under. Built on 2024-25, tested on 2025-26.
D. Late season. Last 21 days: tanking teams (win% .35 or worse) and top teams (.65+) against the spread;
   betting against tankers. 6 seasons at the close, 2 at the opener.

Run: python -m engine.measure_moneyball
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import backtest as BT
from . import backtest_open as BO
from . import boxscore, mine, sources
from . import personnel as P
from .measure_personnel_upgrades import LIVE, market_rank, score, pct

POP = {"LAL", "GSW", "BOS", "NYK"}


# ------------------------------------------------------------------ data
def fetch(season):
    cfg = BO.SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]

    def one(g):
        js = BT._safe(sources.get_json, BT.SUM.format(g.id)) or {}
        rows = boxscore.parse_summary(js, g.id, g.game_date.isoformat()) if js else []
        refs = [o.get("displayName") or o.get("fullName") or "" for o in (js.get("gameInfo") or {}).get("officials") or []]
        return g, rows, [r for r in refs if r]
    with ThreadPoolExecutor(12) as ex:
        out = list(ex.map(one, games))
    return out, days


def shooting(rows):
    """Per team in one game: 3PM, 3PA, FTM, FTA."""
    t = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        x = t[r["team"]]
        x[0] += r["fg3m"]; x[1] += r["fg3a"]; x[2] += r["ftm"]; x[3] += r["fta"]
    return t


# ------------------------------------------------------------------ A. luck + caps
def corrected(rows, luck, K=5, opp3=False, own3=False, ft=False, cap=None):
    res = defaultdict(list)
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    out = []
    for day in sorted(by_day):
        for r in by_day[day]:
            ch = sum(res[r["home"]]) / (len(res[r["home"]]) + K)
            ca = sum(res[r["away"]]) / (len(res[r["away"]]) + K)
            out.append({**r, "pred": r["pred"] + ch - ca})
        for r in by_day[day]:
            e = r["actual"] - r["pred"]
            L = luck.get((r["date"], r["home"], r["away"]))
            eh, ea = e, -e
            if L:
                (h3, a3, hf, af) = L
                if opp3:                       # opponents' threes above/below league rate: not the defense's doing
                    eh += a3; ea += h3
                if own3:
                    eh -= h3; ea -= a3
                if ft:
                    eh += af - hf; ea += hf - af
            if cap:
                eh, ea = max(-cap, min(cap, eh)), max(-cap, min(cap, ea))
            res[r["home"]].append(eh)
            res[r["away"]].append(ea)
    return out


def luck_table(games):
    """(date, home, away) -> points from 3s and FTs above the league's running rates, per team."""
    out = {}
    m3 = a3 = mf = af = 0
    by_day = defaultdict(list)
    for g, rows, _ in games:
        by_day[g.game_date].append((g, rows))
    for day in sorted(by_day):
        p3 = m3 / a3 if a3 else 0.36
        pf = mf / af if af else 0.78
        for g, rows in by_day[day]:
            s = shooting(rows)
            h, a = s[g.home], s[g.away]
            out[(day, g.home, g.away)] = (3 * (h[0] - h[1] * p3), 3 * (a[0] - a[1] * p3),
                                          (h[2] - h[3] * pf), (a[2] - a[3] * pf))
        for g, rows in by_day[day]:
            for x in shooting(rows).values():
                m3 += x[0]; a3 += x[1]; mf += x[2]; af += x[3]
    return out


VARIANTS = {
    "LIVE (results, K=5)": {},
    "remove opponents' 3-pt luck": {"opp3": True},
    "remove both teams' 3-pt luck": {"opp3": True, "own3": True},
    "remove 3-pt + free-throw luck": {"opp3": True, "own3": True, "ft": True},
    "cap each game's miss at 15": {"cap": 15},
    "cap each game's miss at 20": {"cap": 20},
    "opponents' 3-pt luck + cap 15": {"opp3": True, "cap": 15},
}


# ------------------------------------------------------------------ helpers
def wl_line(name, w, l):
    return f"    {name:44} {w}-{l} ({w / max(w + l, 1):.1%}, {w - 1.1 * l:+.1f}u)"


def ats(items):
    w = sum(1 for x in items if x > 0); l = sum(1 for x in items if x < 0)
    return w, l


def main():
    data, games_all, lines_all, totals_all = {}, {}, {}, {}
    for season in BO.SEASONS:
        games, days = fetch(season)
        lines, _ = BO.fetch_lines(season, days, "")
        totals = json.loads((P.STATIC / f"odds_totals_{season.replace('-', '_')}.json").read_text())
        preds, _ = BO.replay(season, [(g, r) for g, r, _ in games], lines)
        data[season], games_all[season], lines_all[season], totals_all[season] = preds[LIVE], games, lines, totals
        refs_seen = sum(1 for _, _, rf in games if rf)
        print(f"{season}: {len(games)} games, {refs_seen} with referees listed")

    # ---------------- A
    print("\n" + "=" * 90 + "\nA. SHOOTING LUCK AND BLOWOUT CAPS in the results correction (players gap 3+ vs the opener)\n" + "=" * 90)
    res = {}
    for season, rows in data.items():
        luck = luck_table(games_all[season])
        ranks = market_rank(rows)
        print(f"\n=== {season}")
        for name, kw in VARIANTS.items():
            res[(season, name)] = score(corrected(rows, luck, **kw), ranks, name)
    best = max(VARIANTS, key=lambda n: (round(res[("2024-25", n)]["info"], 3), pct(res[("2024-25", n)]["g3"])))
    print(f"\nCHOSEN ON 2024-25: {best}")
    for n in ("LIVE (results, K=5)", best):
        r = res[("2025-26", n)]
        print(f"    2025-26 {n:40} 3+ {BO.fmt(r['g3'])}; info {r['info']:+.3f}/pt (t {r['t']:.1f})")
    print("BOTH SEASONS, 3+ vs open:")
    for n in VARIANTS:
        w = sum(res[(s, n)]["g3"]["w"] for s in data); l = sum(res[(s, n)]["g3"]["l"] for s in data)
        print(wl_line(n, w, l))

    # ---------------- B
    print("\n" + "=" * 90 + "\nB. POPULAR TEAMS (LAL, GSW, BOS, NYK) against the spread\n" + "=" * 90)
    print("  at the OPENER, 2 seasons:")
    for season in data:
        fav, dog, allp = [], [], []
        for g, _, _ in games_all[season]:
            ln = lines_all[season].get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}
            op = ln.get("open")
            if op is None:
                continue
            for t, line, margin in ((g.home, op, g.home_score - g.away_score), (g.away, -op, g.away_score - g.home_score)):
                if t in POP:
                    c = margin + line
                    allp.append(c)
                    (fav if line < 0 else dog).append(c)
        print(wl_line(f"{season} popular, all", *ats(allp)))
        print(wl_line(f"{season} popular as favorite", *ats(fav)))
        print(wl_line(f"{season} popular as underdog", *ats(dog)))
    print("  at the CLOSE, 6 seasons:")
    tot = defaultdict(list)
    for season in mine.SEASONS:
        try:
            gs, s, e, days = mine.games_for(season)
            cl, _ = mine.closing_lines(season, days, "")
        except Exception as ex:
            print(f"    {season}: {ex}")
            continue
        fav, allp = [], []
        for g in gs:
            hs = (cl.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}).get("spread")
            if hs is None:
                continue
            for t, line, margin in ((g.home, hs, g.home_score - g.away_score), (g.away, -hs, g.away_score - g.home_score)):
                if t in POP:
                    allp.append(margin + line)
                    if line < 0:
                        fav.append(margin + line)
        tot["all"] += allp; tot["fav"] += fav
        print(wl_line(f"{season} popular as favorite (close)", *ats(fav)))
    print(wl_line("6 SEASONS popular, all (close)", *ats(tot["all"])))
    print(wl_line("6 SEASONS popular as favorite (close)", *ats(tot["fav"])))
    print("    (betting AGAINST them wins when the record above is under 47.6%)")

    # ---------------- C
    print("\n" + "=" * 90 + "\nC. REFEREE CREWS AND TOTALS (vs the opening total)\n" + "=" * 90)
    ref_hist = defaultdict(list)            # ref -> [actual - open total]
    for season in data:
        bets = defaultdict(list)
        xs, ys = [], []
        ordered = sorted(games_all[season], key=lambda x: (x[0].game_date, str(x[0].id)))
        by_day = defaultdict(list)
        for x in ordered:
            by_day[x[0].game_date].append(x)
        for day in sorted(by_day):
            todays = []
            for g, rows, refs in by_day[day]:
                tl = totals_all[season].get(f"{day.isoformat()}|{g.away}|{g.home}") or {}
                op = tl.get("open")
                if op is None or not refs:
                    continue
                diff = g.home_score + g.away_score - op
                known = [ref_hist[r] for r in refs if ref_hist[r]]
                if known:
                    crew = sum(sum(v) / (len(v) + 20) for v in known) / len(refs)   # shrunk, averaged over the crew
                    xs.append(crew); ys.append(diff)
                    for t in (1.0, 2.0, 3.0):
                        if crew >= t:
                            bets[f"over when crew ≥ +{t:g}"].append(diff)
                        if crew <= -t:
                            bets[f"under when crew ≤ −{t:g}"].append(-diff)
                todays.append((refs, diff))
            for refs, diff in todays:
                for r in refs:
                    ref_hist[r].append(diff)
        _, b, t = BT.ols(xs, ys) if len(xs) > 10 else (0, 0, 0)
        print(f"  {season}: {len(xs)} games with crew history; total vs open moves {b:+.2f} per point of crew lean (t {t:.1f})")
        for k in sorted(bets):
            print(wl_line(f"{season} {k}", *ats(bets[k])))

    # ---------------- D
    print("\n" + "=" * 90 + "\nD. LATE SEASON (last 21 days): tankers and top teams against the spread\n" + "=" * 90)
    agg = defaultdict(list)
    for season in mine.SEASONS:
        try:
            gs, s, e, days = mine.games_for(season)
            cl, _ = mine.closing_lines(season, days, "")
        except Exception as ex:
            print(f"    {season}: {ex}")
            continue
        rec = defaultdict(lambda: [0, 0])
        cut = e - timedelta(21)
        rows = defaultdict(list)
        for g in sorted(gs, key=lambda g: (g.game_date, g.id)):
            hs = (cl.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}).get("spread")
            if hs is not None and g.game_date >= cut:
                for t, o, line, margin in ((g.home, g.away, hs, g.home_score - g.away_score),
                                           (g.away, g.home, -hs, g.away_score - g.home_score)):
                    w, l = rec[t]
                    wo, lo = rec[o]
                    pt = w / (w + l) if w + l >= 40 else None
                    po = wo / (wo + lo) if wo + lo >= 40 else None
                    c = margin + line
                    if pt is not None and pt <= 0.35:
                        rows["tanker (≤.350) ATS"].append(c)
                    if pt is not None and pt >= 0.65:
                        rows["top team (≥.650) ATS"].append(c)
                    if po is not None and po <= 0.35 and line < 0:
                        rows["favorite vs a tanker ATS"].append(c)
            hw = g.home_score > g.away_score
            rec[g.home][0 if hw else 1] += 1
            rec[g.away][1 if hw else 0] += 1
        for k in sorted(rows):
            agg[k] += rows[k]
            print(wl_line(f"{season} {k}", *ats(rows[k])))
    for k in sorted(agg):
        print(wl_line(f"6 SEASONS {k}", *ats(agg[k])))


if __name__ == "__main__":
    main()
