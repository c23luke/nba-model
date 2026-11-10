"""TWO MINUTES SPOTS (Caden 2026-11-10: "yes plz go"). Two seasons of box scores (2024-25, 2025-26) plus closing
spreads. Box scores only: there is no history of prop lines, so this measures minutes and stats, not prop results.

1. STAR RETURNING: a player who averaged 28+ minutes over his last 10 games played comes back after missing 3+
   straight team games. His first and second games back vs his usual (minutes, points, rebounds, assists), split by
   how long he was out; the teammates who gained minutes while he was out (5+ above their own usual) — do they
   give it back? And the team's ATS at the close in his first game back.
2. BLOWOUT SPREADS: by closing spread size, starters' (30+ mpg) and bench players' (under 15 mpg) minutes and points
   vs their usual, for the favourite and the underdog. And how often a game actually ends 15+.
"Usual" = the player's average over his last 10 games played before that night (5+ games needed).
Run: python -m engine.measure_minutes_spots"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import backtest as BT
from . import backtest_open as BO
from . import personnel as P
from . import sources
from .measure_props_minutes import box


def load(season):
    cfg = BO.SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]
    games.sort(key=lambda g: (g.game_date, str(g.id)))
    with ThreadPoolExecutor(12) as ex:
        sums = dict(zip([g.id for g in games], ex.map(lambda g: BT._safe(sources.get_json, BT.SUM.format(g.id)) or {}, games)))
    lines = json.loads((P.STATIC / f"odds_openclose_{season.replace('-', '_')}.json").read_text())
    return games, sums, lines


def usual(past, nm):
    rs = [gm[nm] for gm in past if (gm.get(nm) or (0,))[0] > 0][-10:]
    if len(rs) < 5:
        return None
    return tuple(sum(r[i] for r in rs) / len(rs) for i in range(4))


def avg(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def season(season_name):
    games, sums, lines = load(season_name)
    hist = defaultdict(list)                       # team -> [{name: (min, pts, reb, ast)}]
    seen = defaultdict(set)
    streak = defaultdict(int)                      # (team, name) -> team games missed in a row
    back = {}                                      # (team, name) -> {"n": games back so far, "missed": k, "pre": usual}
    ret, fillers, blow = [], [], []
    for g in games:
        b = box(sums.get(g.id) or {})
        ln = lines.get(f"{g.game_date.isoformat()}|{g.away}|{g.home}") or {}
        close = ln.get("close")
        for t in (g.home, g.away):
            tonight = b.get(t) or {}
            past = hist[t]
            if not tonight:
                continue
            home = t == g.home
            margin = (g.home_score - g.away_score) * (1 if home else -1)
            spread = None if close is None else (close if home else -close)        # this team's spread (+ = dog)
            played = {nm for nm, v in tonight.items() if v[0] > 0}
            known = seen[t]                                 # everyone who has appeared for this team this season
            # --- 1. returning stars
            for nm in known | set(tonight):
                key = (t, nm)
                if nm in played:
                    k = streak.get(key, 0)
                    if k >= 3:
                        pre = usual(past[:-k] if k <= len(past) else [], nm)
                        if pre and pre[0] >= 28:
                            # who filled in: teammates 5+ above their usual over the games he missed
                            fill = []
                            for tm in played - {nm}:
                                u = usual(past[:-k], tm)
                                dur = [gm[tm][0] for gm in past[-k:] if (gm.get(tm) or (0,))[0] > 0]
                                if u and len(dur) >= 2 and avg(dur) - u[0] >= 5:
                                    fill.append((tm, u[0], avg(dur), tonight[tm][0]))
                            back[key] = {"n": 0, "missed": k, "pre": pre}
                            cover = None if spread is None else margin + spread
                            ret.append({"missed": k, "pre": pre, "g1": tonight[nm], "fill": fill, "cover": cover,
                                        "spread": spread})
                    elif key in back and back[key]["n"] == 1:
                        ret_row = next((r for r in reversed(ret) if r.get("pre") is back[key]["pre"]), None)
                        if ret_row is not None:
                            ret_row["g2"] = tonight[nm]
                    if key in back:
                        back[key]["n"] += 1
                    streak[key] = 0
                elif nm in known:
                    streak[key] = streak.get(key, 0) + 1
            # --- 2. blowouts
            if spread is not None:
                for nm in played:
                    u = usual(past, nm)
                    if not u:
                        continue
                    role = "starter" if u[0] >= 30 else "bench" if u[0] < 15 else None
                    if role:
                        blow.append({"role": role, "spread": spread, "u": u, "got": tonight[nm],
                                     "final_margin": abs(margin)})
            past.append(tonight)
            seen[t] |= set(tonight)
    return ret, blow


def report(ret, blow, label):
    print(f"\n=== {label}")
    print(f"\n-- 1. STAR RETURNING (28+ mpg before, back after missing 3+ straight team games): {len(ret)} returns")
    print(f"  {'out for':18} {'n':>4}  {'usual min':>9}  {'game 1 min':>10} {'pts':>6} {'reb':>5} {'ast':>5}   "
          f"{'game 2 min':>10} {'pts':>6}   {'team ATS at close, game 1':>26}")
    for name, lo, hi in (("3-5 games", 3, 5), ("6-10 games", 6, 10), ("11-20 games", 11, 20), ("21+ games", 21, 999),
                         ("all", 3, 999)):
        rs = [r for r in ret if lo <= r["missed"] <= hi]
        if not rs:
            continue
        d = lambda i, key="g1": avg([r[key][i] - r["pre"][i] for r in rs if key in r])
        cv = [r["cover"] for r in rs if r["cover"] is not None]
        w, l = sum(c > 0 for c in cv), sum(c < 0 for c in cv)
        g2n = sum(1 for r in rs if "g2" in r)
        print(f"  {name:18} {len(rs):4}  {avg([r['pre'][0] for r in rs]):9.1f}  {d(0):+10.1f} {d(1):+6.1f} {d(2):+5.1f} "
              f"{d(3):+5.1f}   {d(0, 'g2'):+10.1f} {d(1, 'g2'):+6.1f}   "
              f"{f'{w}-{l} ({w / (w + l):.1%})' if w + l else '-':>26}   (game 2 n={g2n})")
    lim = [r for r in ret if r["g1"][0] - r["pre"][0] <= -6]
    print(f"  played 6+ fewer minutes than usual in game 1: {len(lim)} of {len(ret)} ({len(lim) / max(len(ret), 1):.0%}); "
          f"points then {avg([r['g1'][1] - r['pre'][1] for r in lim]):+.1f} vs usual")
    under = [r for r in ret if r["g1"][1] < r["pre"][1]]
    print(f"  scored below his usual in game 1: {len(under)} of {len(ret)} ({len(under) / max(len(ret), 1):.0%})")
    f = [x for r in ret for x in r["fill"]]
    print(f"  fill-ins (5+ above their usual while he was out): {len(f)}; usual {avg([x[1] for x in f]):.1f} min, "
          f"while he was out {avg([x[2] for x in f]):.1f}, the night he came back {avg([x[3] for x in f]):.1f}")
    kept = [x for x in f if x[3] - x[1] >= 5]
    print(f"  fill-ins who kept 5+ of the extra minutes the night he came back: {len(kept)} of {len(f)} "
          f"({len(kept) / max(len(f), 1):.0%})")

    print(f"\n-- 2. BLOWOUT SPREADS (by this team's closing spread; + = underdog)")
    print(f"  {'spread':26} {'role':8} {'n':>6}  {'usual min':>9} {'min vs usual':>12} {'pts vs usual':>12} "
          f"{'reb':>5} {'ast':>5}  {'fewer min by 4+':>15}  {'game ended 15+':>14}")
    bands = (("favourite by 12+", -99, -12), ("favourite by 8-11.5", -11.5, -8), ("within 7.5", -7.5, 7.5),
             ("underdog by 8-11.5", 8, 11.5), ("underdog by 12+", 12, 99))
    for name, lo, hi in bands:
        for role in ("starter", "bench"):
            rs = [r for r in blow if r["role"] == role and lo <= r["spread"] <= hi]
            if not rs:
                continue
            d = lambda i: avg([r["got"][i] - r["u"][i] for r in rs])
            fewer = sum(r["got"][0] - r["u"][0] <= -4 for r in rs) / len(rs)
            big = sum(r["final_margin"] >= 15 for r in rs) / len(rs)
            print(f"  {name:26} {role:8} {len(rs):6}  {avg([r['u'][0] for r in rs]):9.1f} {d(0):+12.1f} {d(1):+12.1f} "
                  f"{d(2):+5.1f} {d(3):+5.1f}  {fewer:15.0%}  {big:14.0%}")


def main():
    allr, allb = [], []
    for s in BO.SEASONS:
        r, b = season(s)
        report(r, b, s)
        allr += r
        allb += b
    report(allr, allb, "both seasons")


if __name__ == "__main__":
    main()
