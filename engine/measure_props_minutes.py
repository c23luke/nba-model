"""WHO REALLY GETS THE MINUTES? (Caden 2026-11-10) Two seasons of box scores (2024-25, 2025-26), no prop lines
(there's no history of those), so this measures the MINUTES and STATS side only.

Every game where a rotation player A (20+ mpg over his team's last 10, in 5+) is out and played the previous game
(fresh news). For each teammate B who plays that night with 5+ games of his own recent history:
  base       = B's average over his last 10 games played (minutes, points, rebounds, assists)
  share      = the naive guess: A's minutes handed out in proportion to each active teammate's base minutes
               (what "he'll get more minutes" assumes)
  history    = B's average gain in games EARLIER THIS SEASON that A missed (needs 2+ / 3+ such games)
Then: does history predict tonight's real gain better than the naive share? And the "fake bump" case: the share
says +5 or more but history says under +2 (3+ games): what did B actually do?
Run: python -m engine.measure_props_minutes"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import backtest as BT
from . import backtest_open as BO
from . import sources
from .teams import code


def box(js: dict) -> dict:
    """team -> {name: (min, pts, reb, ast)} for everyone listed (0 minutes if he didn't play)."""
    out = defaultdict(dict)
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        for a in st.get("athletes", []):
            name = (a.get("athlete") or {}).get("displayName", "")
            d = dict(zip(keys, a.get("stats") or []))

            def n(k):
                try:
                    return int(str(d.get(k) or "0").split(":")[0] or 0)
                except ValueError:
                    return 0
            m = 0 if a.get("didNotPlay") else n("minutes")
            out[team][name] = (m, n("points"), n("rebounds"), n("assists")) if m else (0, 0, 0, 0)
    return out


def season_events(season):
    cfg = BO.SEASONS[season]
    days = [cfg["start"] + timedelta(i) for i in range((cfg["end"] - cfg["start"]).days + 1)]
    with ThreadPoolExecutor(8) as ex:
        games = [g for day in ex.map(lambda d: BT._safe(sources.espn_day, d) or [], days) for g, _ in day if g.final]
    games.sort(key=lambda g: (g.game_date, str(g.id)))
    with ThreadPoolExecutor(12) as ex:
        sums = dict(zip([g.id for g in games], ex.map(lambda g: BT._safe(sources.get_json, BT.SUM.format(g.id)) or {}, games)))
    hist = defaultdict(list)                 # team -> [{name: (min, pts, reb, ast)}], oldest first
    gains = defaultdict(list)                # (team, A, B) -> [B's minute / stat gain vs his base, in earlier games A missed]
    events = []
    for g in games:
        b = box(sums.get(g.id) or {})
        for t in (g.home, g.away):
            tonight = b.get(t) or {}
            past = hist[t]
            if len(past) >= 5 and tonight:
                last10 = past[-10:]
                mp = defaultdict(list)
                for gm in last10:
                    for nm, v in gm.items():
                        mp[nm].append(v[0])
                rot = {nm: sum(v) / len(last10) for nm, v in mp.items()
                       if len([x for x in v if x > 0]) >= 5 and sum(v) / len(last10) >= 20}
                prev = past[-1]
                played = {nm for nm, v in tonight.items() if v[0] > 0}
                outs = [a for a in rot if a not in played]
                fresh = [a for a in outs if (prev.get(a) or (0,))[0] > 0]

                def base(nm):
                    rs = [gm[nm] for gm in past if (gm.get(nm) or (0,))[0] > 0][-10:]
                    if len(rs) < 5:
                        return None
                    return tuple(sum(r[i] for r in rs) / len(rs) for i in range(4))
                bases = {nm: base(nm) for nm in played}
                bases = {k: v for k, v in bases.items() if v}
                tot = sum(v[0] for v in bases.values()) or 1
                for a in fresh:
                    for nm, bs in bases.items():
                        share = rot[a] * bs[0] / tot
                        h = gains.get((t, a, nm)) or []
                        actual = tonight[nm]
                        events.append({"season": season, "base": bs, "share": share, "hist": h[:],
                                       "gain": tuple(actual[i] - bs[i] for i in range(4)), "a_mpg": rot[a]})
                # record tonight's gains for every absent rotation player (fresh or not) for later games
                for a in outs:
                    for nm, bs in bases.items():
                        gains[(t, a, nm)].append(tuple(tonight[nm][i] - bs[i] for i in range(4)))
            if tonight:
                hist[t].append(tonight)
    return events


def avg(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def report(evs, label):
    print(f"\n=== {label}: {len(evs)} teammate-games with a fresh rotation absence")
    h2 = [e for e in evs if len(e["hist"]) >= 2]
    if h2:
        mae_share = avg([abs(e["gain"][0] - e["share"]) for e in h2])
        mae_hist = avg([abs(e["gain"][0] - avg([x[0] for x in e["hist"]])) for e in h2])
        mae_zero = avg([abs(e["gain"][0]) for e in h2])
        print(f"  with 2+ earlier games without that player ({len(h2)}): minutes error  naive share {mae_share:.2f}  "
              f"his history {mae_hist:.2f}  'no change' {mae_zero:.2f}")
    print(f"  {'case':62} {'n':>5} {'expected+':>9} {'real min+':>9} {'pts+':>6} {'reb+':>6} {'ast+':>6}  {'gained<2':>8}")

    def row(name, xs, exp):
        if not xs:
            print(f"  {name:62} {0:5}")
            return
        g = [e["gain"] for e in xs]
        print(f"  {name:62} {len(xs):5} {avg([exp(e) for e in xs]):+9.1f} {avg([x[0] for x in g]):+9.1f} "
              f"{avg([x[1] for x in g]):+6.1f} {avg([x[2] for x in g]):+6.1f} {avg([x[3] for x in g]):+6.1f}  "
              f"{sum(x[0] < 2 for x in g) / len(g):8.0%}")
    hist_avg = lambda e: avg([x[0] for x in e["hist"]])
    row("naive share says +5 or more (everyone)", [e for e in evs if e["share"] >= 5], lambda e: e["share"])
    row("history (2+ games) says +5 or more", [e for e in evs if len(e["hist"]) >= 2 and hist_avg(e) >= 5], hist_avg)
    row("history (3+ games) says +5 or more", [e for e in evs if len(e["hist"]) >= 3 and hist_avg(e) >= 5], hist_avg)
    row("FAKE BUMP: share +5 or more, history (3+ games) under +2",
        [e for e in evs if e["share"] >= 5 and len(e["hist"]) >= 3 and hist_avg(e) < 2], lambda e: e["share"])
    row("FAKE BUMP, 2+ games of history",
        [e for e in evs if e["share"] >= 5 and len(e["hist"]) >= 2 and hist_avg(e) < 2], lambda e: e["share"])
    row("share +5 or more, history (3+) also +5 or more",
        [e for e in evs if e["share"] >= 5 and len(e["hist"]) >= 3 and hist_avg(e) >= 5], hist_avg)
    row("share under +2 but history (3+ games) +5 or more (hidden bump)",
        [e for e in evs if e["share"] < 2 and len(e["hist"]) >= 3 and hist_avg(e) >= 5], hist_avg)
    row("bench guys (base under 15 min), history (2+) +5 or more",
        [e for e in evs if e["base"][0] < 15 and len(e["hist"]) >= 2 and hist_avg(e) >= 5], hist_avg)


def main():
    evs = []
    for s in BO.SEASONS:
        e = season_events(s)
        report(e, s)
        evs += e
    report(evs, "both seasons")


if __name__ == "__main__":
    main()
