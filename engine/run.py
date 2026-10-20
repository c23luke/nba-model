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
from .systems import SYSTEMS, TEST_SYSTEMS, Pick, evaluate, evaluate_tests, grade, label

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
        season_start: date = SEASON_START) -> dict:
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

    # ---- 3 + 4. run systems on every game that hasn't tipped
    old = {p["key"]: p for p in store.load_picks()}
    seen_now = set()
    pick_rows = []
    slate = []
    for g in upcoming:
        row = stored[g.id]
        hs, at = team_state(g.home, finals, g.game_date), team_state(g.away, finals, g.game_date)
        picks = (evaluate(g, hs, at, row.get("home_spread"), row.get("total"))
                 + evaluate_tests(g, hs, at, row.get("home_spread"), row.get("total")))
        keys = []
        for p in picks:
            prev = old.get(p.key, {})
            # Kalshi prices only for the 4 main systems
            quote = (sources.kalshi_quote(p, g, fetch=fetch_kalshi)
                     if p.line is not None and p.system < 100 else None)
            r = {
                **prev,
                "key": p.key, "game_id": g.id, "game_date": g.game_date.isoformat(), "tip_utc": g.tip_utc,
                "away": g.away, "home": g.home, "system": p.system, "tag": label(p.system),
                "bet": p.bet, "side": p.side,
                "label": p.label(), "line": p.line, "evidence": p.evidence, "active": True,
                "kalshi": quote or prev.get("kalshi"),
                "first_seen": prev.get("first_seen") or now.isoformat(),
                "first_line": prev.get("first_line") if prev.get("first_line") is not None else p.line,
                "last_checked": now.isoformat(),
            }
            pick_rows.append(r)
            seen_now.add(p.key)
            keys.append(p.key)
        slate.append({
            "game_id": g.id, "date": g.game_date.isoformat(), "tip_utc": g.tip_utc,
            "away": g.away, "home": g.home,
            "away_state": _state(at), "home_state": _state(hs),
            "home_spread": row.get("home_spread"), "total": row.get("total"),
            "line_source": row.get("line_source"), "line_books": row.get("line_books"),
            "line_updated": row.get("line_updated"), "picks": keys,
        })

    # bets that fired earlier but no longer qualify (line moved) — keep, mark inactive
    upcoming_ids = {g.id for g in upcoming}
    for k, p in old.items():
        if p["game_id"] in upcoming_ids and k not in seen_now and p.get("active"):
            pick_rows.append({**p, "active": False, "last_checked": now.isoformat(),
                              "dropped_reason": "No longer qualifies at the current line"})

    # ---- 5. grade
    by_id = {g.id: g for g in games}
    for k, p in old.items():
        g = by_id.get(p["game_id"])
        if p.get("active") and p.get("result") is None and g and g.final and p.get("line") is not None:
            res = grade(Pick(p["system"], p["game_id"], p["bet"], p["side"], p["line"]), g)
            pick_rows.append({**p, "result": res, "final_score": g.score_line(), "graded_at": now.isoformat()})
    store.save_picks(pick_rows)

    # ---- 6. board
    all_picks = {p["key"]: p for p in store.load_picks()}
    board = build_board(now, today, slate, list(all_picks.values()), usage, log,
                        source="Odds API" if odds_lines else ("ESPN / DraftKings" if espn_lines else "none yet"))
    store.save_board(board)
    return board


def _state(st) -> dict:
    rest = "first game" if st.days_rest is None else ("B2B" if st.days_rest == 0 else f"{st.days_rest}d rest")
    last = None
    if st.last_game:
        g = st.last_game
        last = {"won": st.last_won, "ot": st.last_ot, "score": g.score_line(), "date": g.game_date.isoformat()}
    return {"record": st.record, "streak": st.streak, "rest": rest, "last": last}


def _records(defs, picks):
    out = {}
    for sid, meta in defs.items():
        mine = [p for p in picks if p["system"] == sid and p.get("result")]
        w = sum(p["result"] == "W" for p in mine)
        l = sum(p["result"] == "L" for p in mine)
        pu = sum(p["result"] == "P" for p in mine)
        out[sid] = {**meta, "tag": label(sid), "w": w, "l": l, "p": pu,
                    "win_pct": round(w / (w + l), 4) if w + l else None,
                    "units": round(w * (100 / 110) - l, 2)}   # 1u risked at -110
    return out


def build_board(now, today, slate, picks, usage, log, source):
    t = today.isoformat()
    open_ = lambda p: p.get("result") is None and p["game_date"] >= t
    live = sorted([p for p in picks if p.get("active") and open_(p)],
                  key=lambda p: (p.get("tip_utc") or "", p["system"]))
    history = sorted([p for p in picks if p.get("result")], key=lambda p: p.get("tip_utc") or "", reverse=True)
    main, test = (lambda p: p["system"] < 100), (lambda p: p["system"] >= 100)
    return {
        "generated_at": now.isoformat(), "today": t, "line_source": source,
        "odds_api": usage, "notes": log, "slate": slate,
        "systems": _records(SYSTEMS, picks), "test_systems": _records(TEST_SYSTEMS, picks),
        "bets": [p for p in live if main(p)], "tests": [p for p in live if test(p)],
        "dropped": [p for p in picks if not p.get("active") and open_(p) and main(p)],
        "history": [p for p in history if main(p)][:200],
        "test_history": [p for p in history if test(p)][:300],
    }


if __name__ == "__main__":
    b = run(backfill="--backfill" in sys.argv)
    print(f"{b['generated_at']}  games on slate: {len(b['slate'])}  live bets: {len(b['bets'])}  "
          f"line source: {b['line_source']}  odds credits left: {b['odds_api'].get('remaining')}")
    for p in b["bets"] + b["tests"]:
        print(f"  {label(p['system'])}  {p['away']} @ {p['home']}  ->  {p['label']}")
    for n in b["notes"]:
        print("  note:", n)
