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
                      evaluate_early, evaluate_personnel, evaluate_personnel_shadow, personnel_call, LOCK_ON_FIRE,
                      evaluate_mined,
                      SHADOW_SYSTEMS, grade, label, group)
from . import personnel as personnel_mod
from . import boxscore
from . import case as case_mod

PRICED = {113, 121, 122, 123, 124}          # test systems that also get a live Kalshi price (the main 4 always do)
SEASON_START = date.fromisoformat(os.environ.get("SEASON_START", "2026-10-20"))
SEASON_END = date.fromisoformat(os.environ.get("SEASON_END", "2027-04-11"))      # NBA release
ALL_STAR = date.fromisoformat(os.environ.get("ALL_STAR", "2027-02-21"))          # All-Star Sunday


def games_in(team, finals, day, back):
    return sum(1 for g in finals if team in (g.home, g.away) and 1 <= (day - g.game_date).days <= back)


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
        fetch_lines=None, fetch_kalshi=sources.kalshi_markets, store=None, fetch_exchanges=None,
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

    # exchange prices (Polymarket, ProphetX, BetOpenly, Novig) — fetched only once a pick needs shopping
    if fetch_exchanges is None and key:
        fetch_exchanges = lambda: sources.exchange_quotes(key)
    exch: dict = {}

    def exchange_for(g):
        if "data" not in exch:
            exch["data"] = {}
            if fetch_exchanges:
                try:
                    exch["data"], exch["usage"] = fetch_exchanges()
                except Exception as e:
                    log.append(f"Exchange prices: {e}")
        return exch["data"].get((g.game_date, g.away, g.home), [])

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
    live, played, recent = {}, {}, {}
    try:
        box_rows = store.load_player_games()
        # games with a 0-minute (coach's decision) row were parsed with DNPs; recent games without one are
        # fetched again once so last week's benchings count (older games don't change who plays tonight)
        recent_cut = (today - timedelta(days=7)).isoformat()
        dnp_done = {r["game_id"] for r in box_rows if not r.get("min")}
        have = {r["game_id"] for r in box_rows
                if r["game_id"] in dnp_done or str(r.get("game_date")) < recent_cut}
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
        refetched = {r["game_id"] for r in new_rows}
        box_rows = [r for r in box_rows if r["game_id"] not in refetched] + new_rows
        live = boxscore.season_impact(box_rows)
        played = boxscore.team_dates(box_rows)
        recent = boxscore.recent_players(box_rows)
    except Exception as e:
        log.append(f"Box score step failed: {e}")

    # ---- 2b. personnel read (current rosters x each player's own last two seasons + this season)
    views, reads, stress, cal = {}, {}, {}, None
    if personnel_fetch == "default":
        def personnel_fetch():
            from . import injury_report
            try:
                official = injury_report.latest(now)
                if official is None:
                    log.append("Official injury report: none found in the last 3 hours (using ESPN)")
            except Exception as e:
                official = None
                log.append(f"Official injury report failed (using ESPN): {e}")
            return personnel_mod.read_all(live=live, official=official, notes=log,
                                          games=[(g.game_date, g.away, g.home) for g in upcoming],
                                          team_games=played, recent=recent)
    if personnel_fetch:
        try:
            reads = personnel_fetch()
            rest = {}
            for g in upcoming:
                hs_, as_ = team_state(g.home, finals, g.game_date), team_state(g.away, finals, g.game_date)
                rest[g.id] = (hs_.days_rest == 0, as_.days_rest == 0)
            raw = {g.id: personnel_mod.fair_home_spread(reads[g.home], reads[g.away], *rest[g.id])
                   for g in upcoming if g.home in reads and g.away in reads}
            cal = personnel_mod.calibrate([(stored[gid].get("home_spread"), f) for gid, f in raw.items()])
            ranks = personnel_mod.market_ranks(list(stored.values()), season_start.isoformat(),
                                               (today + timedelta(1)).isoformat())
            for g in upcoming:
                if g.id in raw:
                    views[g.id] = personnel_mod.game_view(reads[g.away], reads[g.home],
                                                          stored[g.id].get("home_spread"), cal, *rest[g.id])
                    personnel_mod.flag_bad_team(views[g.id], g.away, g.home, ranks)
            try:
                stress = personnel_mod.stress_lines(
                    reads, [(g.id, g.away, g.home, stored[g.id].get("home_spread")) for g in upcoming if g.id in raw],
                    rest)
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
    totals_seen = sorted(r["total"] for r in stored.values() if r.get("total") is not None)
    tot_low_cut = totals_seen[len(totals_seen) // 4] if len(totals_seen) >= 100 else None
    for g in upcoming:
        row = stored[g.id]
        hs, at = team_state(g.home, finals, g.game_date), team_state(g.away, finals, g.game_date)
        ctx = {"last21": g.game_date >= SEASON_END - timedelta(21), "post_asb": g.game_date > ALL_STAR,
               "tot_low_cut": tot_low_cut,
               "home_4in6": games_in(g.home, finals, g.game_date, 5) >= 3,
               "away_4in6": games_in(g.away, finals, g.game_date, 5) >= 3}
        picks = (evaluate(g, hs, at, row.get("home_spread"), row.get("total"))
                 + evaluate_tests(g, hs, at, row.get("home_spread"), row.get("total"))
                 + evaluate_early(g, hs, at, row.get("home_spread"), row.get("total"),
                                  (g.game_date - season_start).days)
                 + evaluate_personnel(g, row.get("home_spread"), views.get(g.id),
                                      season_day=(g.game_date - season_start).days)
                 + evaluate_personnel_shadow(g, row.get("home_spread"), views.get(g.id))
                 + evaluate_mined(g, hs, at, row.get("home_spread"), row.get("total"), ctx))
        keys = []
        for p in picks:
            prev = old.get(p.key, {})
            # Kalshi prices only for the 4 main systems
            priced = p.line is not None and (p.system < 100 or p.system in PRICED
                                             or (200 <= p.system < 300 and p.bet == "spread"))
            quote = sources.kalshi_quote(p, g, fetch=fetch_kalshi) if priced else None
            shop = (sources.kalshi_ladder(p, g, fetch=fetch_kalshi) + exchange_for(g)) if priced else None
            locked = p.system in LOCK_ON_FIRE and prev.get("first_line") is not None
            if locked:                                   # bet stays at the line it fired at
                p.line = prev["first_line"]
            r = {
                **prev,
                "key": p.key, "game_id": g.id, "game_date": g.game_date.isoformat(), "tip_utc": g.tip_utc,
                "away": g.away, "home": g.home, "system": p.system,
                "bet": p.bet, "side": p.side,
                "label": p.label(), "line": p.line, "evidence": p.evidence, "active": True,
                "kalshi": quote or prev.get("kalshi"),
                "shop": shop,
                "first_seen": prev.get("first_seen") or now.isoformat(),
                "first_line": prev.get("first_line") if prev.get("first_line") is not None else p.line,
                "last_checked": now.isoformat(),
                "meta": {**(prev.get("meta") or {}), **p.meta},
            }
            if p.system == 301 and r["meta"].get("gap") is not None:
                r["meta"].setdefault("gap_first", r["meta"]["gap"])     # the gap when the line was first seen
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
                                                    reads, stress.get(g.id), cal, others, t13_record,
                                                    (g.game_date - season_start).days)
            except Exception as e:
                log.append(f"Case for {g.away} @ {g.home} failed: {e}")
        level = ((pview or {}).get("case") or {}).get("level")
        lside = ((pview or {}).get("case") or {}).get("side")
        for r in pick_rows:
            if r["game_id"] == g.id and r["system"] in (113, 301):
                m = r["meta"]
                if level and r["side"] == lside:
                    m["level"] = level
                    m.setdefault("level_first", level)
                elif r["system"] == 301:
                    m["level"] = None
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
            if p["system"] in LOCK_ON_FIRE and p.get("first_line") is not None:
                # already bet at the first line: keep it; note where the line has gone since.
                # Still shop it — if the model still likes the side, a better number may be out there.
                g = next(x for x in upcoming if x.id == p["game_id"])
                pk = Pick(p["system"], p["game_id"], p["bet"], p["side"], p["line"])
                pick_rows.append({**p, "last_checked": now.isoformat(), "dropped_reason": None,
                                  "shop": sources.kalshi_ladder(pk, g, fetch=fetch_kalshi) + exchange_for(g)})
                continue
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
    for r in pick_rows:                       # venue prices aren't stored with the pick; carry them to the card
        if r.get("shop") is not None and r["key"] in all_picks:
            all_picks[r["key"]]["shop"] = r["shop"]
    # how this season's scoring compares with the closing totals (the market catching up, or not)
    tot_rows = [(g, stored[g.id].get("total")) for g in finals if stored.get(g.id, {}).get("total") is not None]
    def drift(rows):
        o = sum(1 for g, t in rows if g.home_score + g.away_score > t)
        u = sum(1 for g, t in rows if g.home_score + g.away_score < t)
        avg = sum(g.home_score + g.away_score - t for g, t in rows) / len(rows) if rows else None
        return {"overs": o, "unders": u, "avg": None if avg is None else round(avg, 1), "n": len(rows)}
    scoring = {"season": drift(tot_rows),
               "last7": drift([(g, t) for g, t in tot_rows if (today - g.game_date).days <= 7])}
    try:
        bench_cfg = store.get_config("bench")
    except Exception as e:
        bench_cfg = None
        log.append(f"bench settings: {e}")
    try:
        exclude_cfg = store.get_config("exclude")
    except Exception as e:
        exclude_cfg = None
        log.append(f"excluded bets: {e}")
    orders, placer = [], None
    try:
        orders = store.load_orders() if hasattr(store, "load_orders") else []
    except Exception as e:
        log.append(f"placed bets: {e}")
    try:
        placer = store.load_placer_run() if hasattr(store, "load_placer_run") else None
    except Exception as e:
        log.append(f"order placer notes: {e}")
    board = build_board(now, today, slate, list(all_picks.values()), usage, log,
                        source="Odds API" if odds_lines else ("ESPN / DraftKings" if espn_lines else "none yet"), season_day=max(0, (today - season_start).days),
                        orders=orders, games=stored, bench_cfg=bench_cfg, exclude_cfg=exclude_cfg)
    board["scoring"] = scoring
    if reads:
        audit = personnel_mod.roster_audit(reads)
        board["roster_audit"] = audit
        miss = [f"{t}: {m['name']} ({m['mpg']:.0f} mpg)" for t, a in audit.items() for m in a["missing"]]
        if miss:
            board.setdefault("notes", []).append("Roster check — playing but not on the roster we used: " + "; ".join(miss))
    board["placer"] = placer
    # keep each card bet's reasoning on its pick, so a placed bet can still explain itself after it tips
    from .placed import snapshot
    snaps = []
    for c in board["card"]:
        p = all_picks.get(c["key"])
        if p is None:
            continue
        meta, s = p.get("meta") or {}, snapshot(c)
        if meta.get("card_snap") != s:
            snaps.append({**p, "meta": {**meta, "card_snap": s}})
    if snaps:
        store.save_picks(snaps)
    store.save_board(board)
    try:
        from .pricing import feed_rows
        store.save_feed(feed_rows(board["card"], now), now)
    except Exception as e:
        board["notes"].append(f"bet feed: {e}")
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
            "units": round(w - 1.1 * l, 2)}                   # risk 1.1u to win 1u (-110)


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
                    "avg_clv": round(sum(clvs) / len(clvs), 2) if clvs else None, "n_clv": len(clvs)}
    return out


BENCH_MIN_PICKS = 30      # a system needs this many graded picks with a closing line before it can be benched


def benched_systems(recs: dict, cfg: dict | None) -> dict:
    """Systems the order placer should stop betting: behind the closing line on average over 30+ picks
    (the line moved against the side it fired on), unless Caden switched them back on. Caden can also
    bench one by hand. cfg (private config 'bench'): {"unbench": ["S1"], "bench": ["T7"]}."""
    cfg = cfg or {}
    unbench, manual = set(cfg.get("unbench") or []), set(cfg.get("bench") or [])
    out = {}
    for r in recs.values():
        tag = r["tag"]
        if tag in manual:
            out[tag] = {"why": "benched by hand", "avg_clv": r.get("avg_clv"), "n": r.get("n_clv", 0)}
        elif tag not in unbench and (r.get("n_clv") or 0) >= BENCH_MIN_PICKS and (r.get("avg_clv") or 0) < 0:
            out[tag] = {"why": f"behind the closing line by {abs(r['avg_clv']):.2f} pts on average over {r['n_clv']} picks",
                        "avg_clv": r["avg_clv"], "n": r["n_clv"]}
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

    # each system's spread picks: did the players model agree, and by how much?
    from .pricing import agree_bucket
    vs_pers = {}
    for p in real:
        sh = shadow.get(p["game_id"])
        if p["bet"] != "spread" or not sh or p["system"] == 113:
            continue
        gap = _meta(sh, "gap_first") or _meta(sh, "gap") or 0
        k = f"{group(p['system'])} + {agree_bucket(gap if sh['side'] == p['side'] else -gap)}"
        vs_pers.setdefault(k, []).append(p["result"])

    pers_gap, pers_call = {}, {}
    for p in shadow.values():
        pers_gap.setdefault(_bucket(_meta(p, "gap") or 0), []).append(p["result"])
        pers_call.setdefault(_meta(p, "call") or "none", []).append(p["result"])

    t = lambda d: {k: _wl(v) for k, v in sorted(d.items())}
    return {"by_combo": t(by_combo), "by_groups": t(by_groups), "by_count": t(by_count),
            "conflicts": conflicts, "system_vs_personnel": t(vs_pers),
            "personnel_by_gap": t(pers_gap), "personnel_by_call": t(pers_call)}


GAP_BUCKETS = [("0-2", 0, 2), ("2-3", 2, 3), ("3-4", 3, 4), ("4-5", 4, 5), ("5+", 5, 99)]


def gap_tracker(picks: list[dict], season_day: int) -> dict:
    """Every game, the side the personnel line likes, graded at the line it was first seen
    (the opener — how Caden bets), split by gap size and by confidence. Next to it, the same
    split from the two-season replay at the opening line."""
    x1 = [p for p in picks if p["system"] == 301 and p.get("active")]
    def res(p):
        return _meta(p, "result_first") or p.get("result")
    rows = {}
    for name, lo, hi in GAP_BUCKETS + [("3+", 3, 99), ("5+ only", 5, 99)]:
        ps = [p for p in x1 if res(p) and lo <= (_meta(p, "gap_first") or _meta(p, "gap") or 0) < hi]
        if name == "5+ only":
            continue
        clv = [c for c in (_meta(p, "clv") for p in ps) if c is not None]
        rows[name] = {**_wl([res(p) for p in ps]), "avg_clv": round(sum(clv) / len(clv), 2) if clv else None}
    conf = {}
    for lv in ("High", "Medium", "Low"):
        ps = [p for p in x1 if res(p) and (_meta(p, "gap_first") or 0) >= 3
              and (_meta(p, "level_first") or _meta(p, "level")) == lv]
        clv = [c for c in (_meta(p, "clv") for p in ps) if c is not None]
        conf[lv] = {**_wl([res(p) for p in ps]), "avg_clv": round(sum(clv) / len(clv), 2) if clv else None}
    window = next(n for n, lo, hi in case_mod.WINDOWS if lo <= season_day <= hi)
    def hist(src, keys):
        out = {}
        for wname in (window, "whole season"):
            t = src.get(wname) or {}
            out[wname] = {k: t[k] for k in keys if k in t}
        return out
    # 3+ from the cumulative tiers the replay already had
    bt = case_mod.BACKTEST
    buckets_hist = hist(case_mod.BACKTEST_BUCKETS, [b[0] for b in GAP_BUCKETS])
    for wname in buckets_hist:
        if (bt.get(wname) or {}).get("3"):
            buckets_hist[wname]["3+"] = bt[wname]["3"]
    pending = sum(1 for p in x1 if not res(p))
    return {"by_gap": rows, "by_confidence": conf, "window": window, "pending": pending,
            "history_by_gap": buckets_hist,
            "history_by_confidence": hist(case_mod.BACKTEST_CONFIDENCE, ["High", "Medium", "Low"])}


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


def excluded_keys(cfg) -> dict:
    """Bets taken out of all tracking because a model bug made them (private config 'exclude'):
    [{"game_id": "401909843", "side": "CHA", "why": "..."}]. Matches every system's pick and every
    placed order on that side of that game. Nothing is deleted; they're listed on the site separately."""
    return {(str(x["game_id"]), x["side"]): x.get("why") or "excluded" for x in (cfg or []) if x.get("game_id") and x.get("side")}


def build_board(now, today, slate, picks, usage, log, source, season_day: int = 0, orders=None, games=None,
                bench_cfg=None, exclude_cfg=None):
    ex = excluded_keys(exclude_cfg)
    out_picks = [p for p in picks if (str(p["game_id"]), p["side"]) in ex]
    picks = [{**p, "tag": label(p["system"]), "group": group(p["system"])} for p in picks
             if (str(p["game_id"]), p["side"]) not in ex]
    out_orders = [o for o in (orders or []) if (str(o.get("game_id")), o.get("side")) in ex]
    orders = [o for o in (orders or []) if (str(o.get("game_id")), o.get("side")) not in ex]
    t = today.isoformat()
    open_ = lambda p: p.get("result") is None and p["game_date"] >= t
    live = sorted([p for p in picks if p.get("active") and open_(p)],
                  key=lambda p: (p.get("tip_utc") or "", p["system"]))
    history = sorted([p for p in picks if p.get("result") and p.get("active")],
                     key=lambda p: p.get("tip_utc") or "", reverse=True)
    main = lambda p: p["system"] < 100
    test = lambda p: 100 <= p["system"] < 200
    early = lambda p: 200 <= p["system"] < 300
    from .pricing import build_card, agree_bucket
    card = build_card(live, slate, now)
    # each card bet's record = its history + this season's graded bets of the same kind
    graded = [p for p in picks if p.get("result") and p.get("active")]
    x1 = {p["game_id"]: p for p in graded if p["system"] == 301}
    def live_wl(row):
        if row["group"] == "EARLY":           # early system + players model 3+ on the same side
            res = []
            for p in graded:
                sh = x1.get(p["game_id"])
                if 200 <= p["system"] < 300 and p["bet"] == "spread" and sh and sh["side"] == p["side"] \
                        and (_meta(sh, "gap_first") or _meta(sh, "gap") or 0) >= 3:
                    res.append(p["result"])
            return _wl(res)
        return _wl(p["result"] for p in graded if p["system"] == row["system"])
    recs = {"systems": _records(SYSTEMS, picks), "test_systems": _records(TEST_SYSTEMS, picks),
            "early_systems": _records(EARLY_SYSTEMS, picks)}
    benched = benched_systems({**recs["systems"], **recs["test_systems"], **recs["early_systems"]}, bench_cfg)
    for row in card:
        if row["tag"] in benched and row["verdict"] in ("BET", "LIMIT"):
            row["verdict"], row["why"] = "BENCHED", f"{row['tag']} is benched: {benched[row['tag']]['why']}. {row['why']}"
    for row in card:
        lv = live_wl(row)
        h = row.get("history") or {"w": 0, "l": 0, "label": None}
        row["record"] = {"history": h, "season": {"w": lv["w"], "l": lv["l"], "p": lv["p"]},
                         "w": h["w"] + lv["w"], "l": h["l"] + lv["l"]}
    # the card's own history: OG/FAV bets that already tipped in the last 30 hours (in progress or graded),
    # and fired bets the model no longer adds to at today's number (still graded where they fired)
    now_iso = now.isoformat()
    on_card = {c["key"] for c in card}
    since = (now - timedelta(hours=30)).isoformat()
    cardish = [p for p in picks if p["group"] in ("OG", "FAV") and p.get("line") is not None and p.get("active")]
    def brief(p, status):
        return {"key": p["key"], "label": p["label"], "away": p["away"], "home": p["home"], "tip_utc": p.get("tip_utc"),
                "tag": p["tag"], "group": p["group"], "status": status, "result": p.get("result"),
                "final_score": p.get("final_score"), "clv": (p.get("meta") or {}).get("clv"),
                "close_line": (p.get("meta") or {}).get("close_line")}
    card_done = sorted([brief(p, "FINAL" if p.get("result") else "IN PROGRESS") for p in cardish
                        if since <= (p.get("tip_utc") or "") < now_iso], key=lambda r: r["tip_utc"] or "", reverse=True)
    lines_now = {g["game_id"]: g for g in slate}
    def line_now(p):
        g = lines_now.get(p["game_id"]) or {}
        if p["bet"] == "total":
            return g.get("total")
        hs = g.get("home_spread")
        return None if hs is None else (hs if p["side"] == p["home"] else -hs)
    # fired earlier at a better number; the model doesn't want it at today's number
    holding = [{**brief(p, "MOVED"), "fired_at": p.get("first_seen"), "now_line": line_now(p)}
               for p in cardish if p.get("result") is None and (p.get("tip_utc") or "") >= now_iso
               and p["key"] not in on_card]
    from .placed import placed_bets
    def season_wl(p):
        r = live_wl({"group": p["group"], "system": p["system"]})
        return {"w": r["w"], "l": r["l"], "p": r["p"]}
    lines_now = {g["game_id"]: g for g in slate}
    def market_now(gid, bet, side):
        g = lines_now.get(gid) or {}
        if bet == "total":
            return g.get("total")
        hs = g.get("home_spread")
        return None if hs is None else (hs if side == g.get("home") else -hs)
    placed = placed_bets(orders or [], {p["key"]: p for p in picks}, games or {}, {c["key"]: c for c in card},
                         season_wl, now, market_now,
                         {label(i): x.get("name") for d in (SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS) for i, x in d.items()})
    if out_orders:
        gone = placed_bets(out_orders, {p["key"]: p for p in out_picks}, games or {}, {}, lambda p: {"w": 0, "l": 0, "p": 0},
                           now, None, {})
        placed["excluded"] = [{"holding": r["holding"], "venue_name": r["venue_name"], "status": r["status"],
                               "result": r["result"], "pnl": r["pnl"], "risk": r["risk"], "tip_utc": r["tip_utc"],
                               "why": ex.get((str(r["game_id"]), r["side"]))} for r in gone["bets"]]
        placed["summary"]["excluded_pnl"] = round(sum(r["pnl"] or 0 for r in gone["bets"]), 2)
    for p in picks:
        p.pop("shop", None)        # every venue's prices live on the card; keep the rest of the board lean
    return {
        "placed": placed,
        "card": card, "card_done": card_done, "card_holding": holding,
        "gap_tracker": gap_tracker(picks, season_day),
        "tracking": tracking(picks), "stacks": live_stacks(live),
        "shadow_systems": _records(SHADOW_SYSTEMS, picks),
        "generated_at": now.isoformat(), "today": t, "line_source": source,
        "odds_api": usage, "notes": log, "slate": slate,
        "systems": recs["systems"], "test_systems": recs["test_systems"],
        "early_systems": recs["early_systems"], "benched": benched,
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
