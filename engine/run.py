"""One pass of the model. Runs every few minutes on a schedule.

  1. Pull schedule + final scores from ESPN (last 3 days, today, tomorrow)
  2. Pull current lines (The Odds API consensus; ESPN's DraftKings line as backup)
  3. For every game that hasn't tipped: work out both teams' state, run all 4 systems
  4. Price each live bet on Kalshi
  5. Grade bets whose games are final
  6. Write the board the website reads

    python -m engine.run              # normal pass
    python -m engine.run --backfill   # also load every day since opening night
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import sources
from .state import Game, team_state
from .store import get_store
from .systems import (SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS, Pick, evaluate, evaluate_tests,
                      evaluate_early, evaluate_personnel, evaluate_personnel_shadow, personnel_call,
                      SHADOW_SYSTEMS, grade, label, group)
from . import personnel as personnel_mod
from . import boxscore
from . import case as case_mod

SEASON_START = date.fromisoformat(os.environ.get("SEASON_START", "2026-10-20"))


def game_from_row(r: dict) -> Game:
    return Game(id=r["id"], game_date=date.fromisoformat(str(r["game_date"])[:10]),
                away=r["away"], home=r["home"], away_score=r.get("away_score"),
                home_score=r.get("home_score"), periods=r.get("periods"),
                final=bool(r.get("final")), tip_utc=r.get("tip_utc"))


def row_from_game(g: Game, prev: dict | None) -> dict:
    row = dict(prev or {})
    row.update(id=g.id, game_date=g.game_date.isoformat(), tip_utc=g.tip_utc, away=g.away,
               home=g.home, away_score=g.away_score, home_score=g.home_score,
               periods=g.periods, final=g.final)
    return row


def tipped(g: Game, now: datetime) -> bool:
    if g.final:
        return True
    if not g.tip_utc:
        return False
    return datetime.fromisoformat(g.tip_utc.replace("Z", "+00:00")) <= now


def run(now: datetime | None = None, backfill: bool = False, fetch_day=sources.espn_day,
        fetch_lines=None, fetch_kalshi=sources.kalshi_markets, store=None,
        season_start: date = SEASON_START, personnel_fetch="default", fetch_box=boxscore.fetch_box) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(sources.ET).date()
    store = store or get_store()
    log = []

    # ---- 1. games
    stored = {r["id"]: r for r in store.load_games()}
    first = season_start if (backfill or not stored) else max(season_start, today - timedelta(3))
    days = [first + timedelta(i) for i in range((today + timedelta(1) - first).days + 1)]
    espn_lines = {}
    changed = []
    for d in days:
        try:
            for g, line in fetch_day(d):
                if g.game_date < season_start:
                    continue
                stored[g.id] = row_from_game(g, stored.get(g.id))
                changed.append(stored[g.id])
                if line:
                    espn_lines[g.id] = line
        except Exception as e:                      # one bad day shouldn't kill the run
            log.append(f"ESPN {d}: {e}")
    games = [game_from_row(r) for r in stored.values()]
    finals = [g for g in games if g.final]

    # ---- 2. lines
    odds_lines, usage = {}, {}
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    if fetch_lines is None and key:
        fetch_lines = lambda: sources.odds_api_lines(key)
    if fetch_lines:
        try:
            odds_lines, usage = fetch_lines()
        except Exception as e:
            log.append(f"Odds API: {e}")

    upcoming = sorted([g for g in games if g.game_date in (today, today + timedelta(1)) and not tipped(g, now)],
                      key=lambda g: (g.tip_utc or "", g.id))
    for g in upcoming:
        row = stored[g.id]
        line = odds_lines.get((g.game_date, g.away, g.home)) or espn_lines.get(g.id)
        if line:
            if (line.get("home_spread"), line.get("total")) != (row.get("home_spread"), row.get("total")):
                row["line_updated"] = now.isoformat()
            row.update(home_spread=line.get("home_spread"), total=line.get("total"),
                       line_source=line.get("source"), line_books=line.get("books"))
            changed.append(row)
    store.save_games(list({r["id"]: r for r in changed}.values()))

    # ---- 2a. this season's box scores (only games not stored yet)
    live = {}
    try:
        box_rows = store.load_player_games()
        have = {r["game_id"] for r in box_rows}
        new_rows = []
        for g in finals:
            if g.id not in have and fetch_box:
                try:
                    new_rows += fetch_box(g.id, g.game_date.isoformat())
                except Exception as e:
                    log.append(f"Box score {g.id}: {e}")
        if new_rows:
            store.save_player_games(new_rows)
            log.append(f"Box scores: {len({r['game_id'] for r in new_rows})} new games stored")
        live = boxscore.season_impact(box_rows + new_rows)
    except Exception as e:
        log.append(f"Box score step failed: {e}")

    # ---- 2b. personnel read (current rosters x each player's own last two seasons + this season)
    views, reads, stress, cal = {}, {}, {}, None
    if personnel_fetch == "default":
        personnel_fetch = lambda: personnel_mod.read_all(live=live)
    if personnel_fetch:
        try:
            reads = personnel_fetch()
            raw = {g.id: personnel_mod.fair_home_spread(reads[g.home], reads[g.away])
                   for g in upcoming if g.home in reads and g.away in reads}
            cal = personnel_mod.calibrate([(stored[gid].get("home_spread"), f) for gid, f in raw.items()])
            for g in upcoming:
                if g.id in raw:
                    views[g.id] = personnel_mod.game_view(reads[g.away], reads[g.home],
                                                          stored[g.id].get("home_spread"), cal)
            try:
                stress = personnel_mod.stress_lines(
                    reads, [(g.id, g.away, g.home, stored[g.id].get("home_spread")) for g in upcoming if g.id in raw])
            except Exception as e:
                log.append(f"Stress tests failed: {e}")
            log.append(f"Personnel: {len(views)} games rated"
                       + (f", calibrated market = {cal[0]:+.1f} + {cal[1]:.2f} x personnel" if cal else ", not calibrated (under 6 lines)"))
        except Exception as e:
            log.append(f"Personnel read failed: {e}")

    # ---- 3 + 4. run systems on every game that hasn't tipped
    old = {p["key"]: p for p in store.load_picks()}
    t13 = [p for p in old.values() if p["system"] == 113 and p.get("active") and p.get("result")]
    t13_record = {"w": sum(p["result"] == "W" for p in t13), "l": sum(p["result"] == "L" for p in t13)}
    seen_now = set()
    pick_rows = []
    slate = []
    for g in upcoming:
        row = stored[g.id]
        hs, at = team_state(g.home, finals, g.game_date), team_state(g.away, finals, g.game_date)
        picks = (evaluate(g, hs, at, row.get("home_spread"), row.get("total"))
                 + evaluate_tests(g, hs, at, row.get("home_spread"), row.get("total"))
                 + evaluate_early(g, hs, at, row.get("home_spread"), row.get("total"),
                                  (g.game_date - season_start).days)
                 + evaluate_personnel(g, row.get("home_spread"), views.get(g.id))
                 + evaluate_personnel_shadow(g, row.get("home_spread"), views.get(g.id)))
        keys = []
        for p in picks:
            prev = old.get(p.key, {})
            # Kalshi prices only for the 4 main systems
            quote = (sources.kalshi_quote(p, g, fetch=fetch_kalshi)
                     if p.line is not None and p.system < 100 else None)
            r = {
                **prev,
                "key": p.key, "game_id": g.id, "game_date": g.game_date.isoformat(), "tip_utc": g.tip_utc,
                "away": g.away, "home": g.home, "system": p.system,
                "bet": p.bet, "side": p.side,
                "label": p.label(), "line": p.line, "evidence": p.evidence, "active": True,
                "kalshi": quote or prev.get("kalshi"),
                "first_seen": prev.get("first_seen") or now.isoformat(),
                "first_line": prev.get("first_line") if prev.get("first_line") is not None else p.line,
                "last_checked": now.isoformat(),
                "meta": {**(prev.get("meta") or {}), **p.meta},
            }
            pick_rows.append(r)
            seen_now.add(p.key)
            if p.system < 300:
                keys.append(p.key)
        pview = ({**views[g.id], "call": personnel_call(views[g.id])} if g.id in views else None)
        if pview and pview["call"]["call"] in ("now", "waiting") and row.get("home_spread") is not None:
            try:
                side = g.home if pview["call"]["side"] == "home" else g.away
                bet_line = row["home_spread"] if side == g.home else -row["home_spread"]
                names = {**SYSTEMS, **TEST_SYSTEMS, **EARLY_SYSTEMS}
                others = sorted({f"{label(p.system)} {names[p.system]['name']} ({group(p.system)})" for p in picks
                                 if p.side == side and p.bet == "spread" and p.system not in (113, 301)})
                pview["case"] = case_mod.build_case(g.away, g.home, side, bet_line, row["home_spread"], pview,
                                                    reads, stress.get(g.id), cal, others, t13_record)
            except Exception as e:
                log.append(f"Case for {g.away} @ {g.home} failed: {e}")
        slate.append({
            "game_id": g.id, "date": g.game_date.isoformat(), "tip_utc": g.tip_utc,
            "away": g.away, "home": g.home,
            "away_state": _state(at), "home_state": _state(hs),
            "home_spread": row.get("home_spread"), "total": row.get("total"),
            "line_source": row.get("line_source"), "line_books": row.get("line_books"),
            "line_updated": row.get("line_updated"), "picks": keys,
            "personnel": pview,
        })

    # bets that fired earlier but no longer qualify (line moved) — keep, mark inactive
    upcoming_ids = {g.id for g in upcoming}
    for k, p in old.items():
        if p["game_id"] in upcoming_ids and k not in seen_now and p.get("active"):
            pick_rows.append({**p, "active": False, "last_checked": now.isoformat(),
                              "dropped_reason": "No longer qualifies at the current line"})

    # ---- 5. grade every pick, including ones that fired and later dropped (tracked separately),
    #         at the closing line AND at the line when it first fired
    by_id = {g.id: g for g in games}
    for k, p in old.items():
        g = by_id.get(p["game_id"])
        if p.get("result") is None and g and g.final and p.get("line") is not None:
            res = grade(Pick(p["system"], p["game_id"], p["bet"], p["side"], p["line"]), g)
            first = p.get("first_line")
            meta = dict(p.get("meta") or {})
            gr = stored.get(p["game_id"]) or {}
            close = (gr.get("total") if p["bet"] == "total" else
                     None if gr.get("home_spread") is None else
                     gr["home_spread"] if p["side"] == p["home"] else -gr["home_spread"])
            if close is None:
                close = p["line"]
            meta["close_line"] = close
            if first is not None:
                meta["result_first"] = grade(Pick(p["system"], p["game_id"], p["bet"], p["side"], first), g)
                meta["clv"] = clv(p["bet"], p["side"], first, close)
            pick_rows.append({**p, "result": res, "final_score": g.score_line(),
                              "graded_at": now.isoformat(), "meta": meta})
    store.save_picks(pick_rows)

    # ---- 6. board
    all_picks = {p["key"]: p for p in store.load_picks()}
    board = build_board(now, today, slate, list(all_picks.values()), usage, log,
                        source="Odds API" if odds_lines else ("ESPN / DraftKings" if espn_lines else "none yet"))
    store.save_board(board)
    return board


def clv(bet: str, side: str, first: float, close: float) -> float:
    """Points gained by betting when it first fired instead of at the close (+ = first line was better)."""
    if bet == "total":
        return round(close - first if side == "OVER" else first - close, 1)
    return round(first - close, 1)


def _state(st) -> dict:
    rest = "first game" if st.days_rest is None else ("B2B" if st.days_rest == 0 else f"{st.days_rest}d rest")
    last = None
    if st.last_game:
        g = st.last_game
        last = {"won": st.last_won, "ot": st.last_ot, "score": g.score_line(), "date": g.game_date.isoformat()}
    return {"record": st.record, "streak": st.streak, "rest": rest, "last": last}


def _wl(results) -> dict:
    results = [r for r in results if r]
    w, l, pu = (sum(r == x for r in results) for x in "WLP")
    return {"w": w, "l": l, "p": pu, "n": w + l + pu,
            "win_pct": round(w / (w + l), 4) if w + l else None,
            "units": round(w * (100 / 110) - l, 2)}           # 1u risked at -110


def _meta(p, k):
    return (p.get("meta") or {}).get(k)


def _records(defs, picks):
    out = {}
    for sid, meta in defs.items():
        official = [p for p in picks if p["system"] == sid and p.get("result") and p.get("active")]
        ever = [p for p in picks if p["system"] == sid and p.get("result")]
        clvs = [_meta(p, "clv") for p in ever if _meta(p, "clv") is not None]
        out[sid] = {**meta, "tag": label(sid), "group": group(sid), **_wl(p["result"] for p in official),
                    # every time it fired, even if the line later moved out, graded at the first line
                    "if_first": _wl(_meta(p, "result_first") for p in ever),
                    "dropped": _wl(p["result"] for p in ever if not p.get("active")),
                    "avg_clv": round(sum(clvs) / len(clvs), 2) if clvs else None}
    return out


def _bucket(g):
    for lo, hi, name in ((0, 1, "0–1"), (1, 2, "1–2"), (2, 3, "2–3"), (3, 4, "3–4"), (4, 99, "4+")):
        if lo <= g < hi:
            return name
    return "4+"


def tracking(picks: list[dict]) -> dict:
    """Every variation, graded: stacks of systems on the same side, systems vs the personnel line,
    and the personnel line split by gap size and by day-to-day / blind status."""
    graded = [p for p in picks if p.get("result") and p.get("active")]
    real = [p for p in graded if p["system"] < 300]
    shadow = {p["game_id"]: p for p in graded if p["system"] == 301}

    # same game, same bet, same side → one stack
    stacks = {}
    for p in real:
        stacks.setdefault((p["game_id"], p["bet"], p["side"]), []).append(p)
    by_combo, by_groups, by_count = {}, {}, {}
    for (gid, bet, side), ps in stacks.items():
        res = ps[0]["result"]
        n = len({p["system"] for p in ps})
        by_count.setdefault("1 system" if n == 1 else "2 systems" if n == 2 else "3+ systems", []).append(res)
        if n < 2:
            continue
        combo = "+".join(sorted({label(p["system"]) for p in ps}))
        groups = "+".join(sorted({group(p["system"]) for p in ps}))
        by_combo.setdefault(combo, []).append(res)
        by_groups.setdefault(groups, []).append(res)

    # opposite sides of the same game
    conflicts = 0
    per_game = {}
    for (gid, bet, side) in stacks:
        per_game.setdefault((gid, bet), set()).add(side)
    conflicts = sum(len(v) > 1 for v in per_game.values())

    # each system's spread picks: did the personnel line agree?
    vs_pers = {}
    for p in real:
        sh = shadow.get(p["game_id"])
        if p["bet"] != "spread" or not sh or p["system"] == 113:
            continue
        k = f"{group(p['system'])} + personnel {'agrees' if sh['side'] == p['side'] else 'disagrees'}"
        vs_pers.setdefault(k, []).append(p["result"])

    pers_gap, pers_call = {}, {}
    for p in shadow.values():
        pers_gap.setdefault(_bucket(_meta(p, "gap") or 0), []).append(p["result"])
        pers_call.setdefault(_meta(p, "call") or "none", []).append(p["result"])

    t = lambda d: {k: _wl(v) for k, v in sorted(d.items())}
    return {"by_combo": t(by_combo), "by_groups": t(by_groups), "by_count": t(by_count),
            "conflicts": conflicts, "system_vs_personnel": t(vs_pers),
            "personnel_by_gap": t(pers_gap), "personnel_by_call": t(pers_call)}


def live_stacks(live: list[dict]) -> list[dict]:
    """Tonight's games where 2+ systems are on the same side."""
    st = {}
    for p in live:
        if p["system"] < 300 and p.get("line") is not None:
            st.setdefault((p["game_id"], p["bet"], p["side"]), []).append(p)
    out = []
    for (gid, bet, side), ps in st.items():
        if len({p["system"] for p in ps}) >= 2:
            out.append({"game_id": gid, "away": ps[0]["away"], "home": ps[0]["home"], "tip_utc": ps[0].get("tip_utc"),
                        "label": ps[0]["label"], "systems": sorted({p["tag"] for p in ps}),
                        "groups": sorted({p["group"] for p in ps})})
    return sorted(out, key=lambda x: (-len(x["systems"]), x["tip_utc"] or ""))


def build_board(now, today, slate, picks, usage, log, source):
    picks = [{**p, "tag": label(p["system"]), "group": group(p["system"])} for p in picks]
    t = today.isoformat()
    open_ = lambda p: p.get("result") is None and p["game_date"] >= t
    live = sorted([p for p in picks if p.get("active") and open_(p)],
                  key=lambda p: (p.get("tip_utc") or "", p["system"]))
    history = sorted([p for p in picks if p.get("result") and p.get("active")],
                     key=lambda p: p.get("tip_utc") or "", reverse=True)
    main = lambda p: p["system"] < 100
    test = lambda p: 100 <= p["system"] < 200
    early = lambda p: 200 <= p["system"] < 300
    return {
        "tracking": tracking(picks), "stacks": live_stacks(live),
        "shadow_systems": _records(SHADOW_SYSTEMS, picks),
        "generated_at": now.isoformat(), "today": t, "line_source": source,
        "odds_api": usage, "notes": log, "slate": slate,
        "systems": _records(SYSTEMS, picks), "test_systems": _records(TEST_SYSTEMS, picks),
        "early_systems": _records(EARLY_SYSTEMS, picks),
        "early": [p for p in live if early(p)],
        "early_history": [p for p in history if early(p)][:300],
        "bets": [p for p in live if main(p)],
        "tests": sorted([p for p in live if test(p)], key=lambda p: (group(p["system"]) != "FAV", p.get("tip_utc") or "")),
        "dropped": [p for p in picks if not p.get("active") and open_(p) and main(p)],
        "history": [p for p in history if main(p)][:200],
        "test_history": [p for p in history if test(p)][:300],
    }


if __name__ == "__main__":
    b = run(backfill="--backfill" in sys.argv)
    print(f"{b['generated_at']}  games on slate: {len(b['slate'])}  live bets: {len(b['bets'])}  "
          f"line source: {b['line_source']}  odds credits left: {b['odds_api'].get('remaining')}")
    for p in b["bets"] + b["tests"] + b["early"]:
        print(f"  {group(p['system']):4} {label(p['system'])}  {p['away']} @ {p['home']}  ->  {p['label']}")
    for n in b["notes"]:
        print("  note:", n)
