"""Full pass of the runner, offline: real 2025 results, fake lines + fake Kalshi book."""
from datetime import date, datetime, timedelta, timezone

from engine.run import run
from engine.state import Game
from engine.store import LocalStore
from tests.load import fixture_games

ALL = fixture_games()
START = date(2025, 10, 21)


def make_fetch_day(sim_today: date, finals_through: date):
    def fetch_day(d):
        out = []
        for g in ALL:
            if g.game_date != d:
                continue
            tip = f"{(d + timedelta(1)).isoformat()}T00:30Z"           # 7:30pm ET
            if d <= finals_through:
                out.append((Game(g.id, d, g.away, g.home, g.away_score, g.home_score, g.periods, True, tip), None))
            else:
                out.append((Game(g.id, d, g.away, g.home, tip_utc=tip), None))
        return out
    return fetch_day


def fake_lines():
    # LAL @ MIL, Nov 15 2025: MIL -6 / 224.5 (MIL won in OT the night before → System 1 on LAL +6)
    return {(date(2025, 11, 15), "LAL", "MIL"): {"home_spread": -6.0, "total": 224.5,
                                                "source": "test", "books": 8}}, {"remaining": "999000"}


def fake_kalshi(series, g):
    if series != "KXNBASPREAD":
        return []
    return [{"ticker": f"KXNBASPREAD-25NOV15LALMIL-MIL{k}", "floor_strike": k - 0.5,
             "yes_bid_dollars": "0.45", "yes_ask_dollars": "0.47"} for k in range(3, 10)]


def test_full_pass_fires_prices_and_grades(tmp_path):
    store = LocalStore(tmp_path)
    morning = datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc)      # 10am ET Nov 15
    board = run(now=morning, fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)),
                fetch_lines=fake_lines, fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)

    bets = board["bets"]
    assert [(b["system"], b["side"], b["line"]) for b in bets] == [(1, "LAL", 6.0)]
    k = bets[0]["kalshi"]
    # LAL +6 → no 6.0 strike on Kalshi; take NO on "MIL wins by over 6.5" (= LAL +6.5, the better side of the tie)
    assert k["contract"].startswith("NO · MIL wins by over 6.5") and k["price"] == 0.55 and not k["exact"]
    assert any(s["away"] == "LAL" and s["home"] == "MIL" and s["picks"] for s in board["slate"])
    assert board["odds_api"]["remaining"] == "999000"

    # next morning: game is final (LAL won 119-95) → graded W
    nxt = datetime(2025, 11, 16, 15, 0, tzinfo=timezone.utc)
    board = run(now=nxt, fetch_day=make_fetch_day(date(2025, 11, 16), date(2025, 11, 15)),
                fetch_lines=lambda: ({}, {}), fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    h = [p for p in board["history"] if p["key"] == bets[0]["key"]]
    assert h and h[0]["result"] == "W" and "LAL 119 @ MIL 95" in h[0]["final_score"]
    assert board["systems"][1]["w"] == 1 and board["systems"][1]["l"] == 0


def seed_totals(store, day, total=224.0):
    """S4's bar is this season's average total over games already played: give the store those games."""
    from engine.run import row_from_game
    store.save_games([{**row_from_game(x, None), "total": total} for x in ALL if x.game_date < day])


def test_bet_drops_when_line_moves_out(tmp_path):
    from engine.state import team_state
    # first game in the fixture where the home team won its last game and the road team lost its last
    def fits(x):
        fin = [y for y in ALL if y.game_date < x.game_date]
        return (team_state(x.home, fin, x.game_date).last_won is True
                and team_state(x.away, fin, x.game_date).last_won is False)
    g = next(x for x in ALL if x.game_date >= date(2025, 11, 10) and fits(x))
    day = g.game_date
    t = lambda h: datetime(day.year, day.month, day.day, h, 0, tzinfo=timezone.utc)

    def lines(total):
        return lambda: ({(day, g.away, g.home): {"home_spread": -10.5, "total": total,
                                                 "source": "test", "books": 5}}, {})

    store = LocalStore(tmp_path)
    seed_totals(store, day)                      # season average 224: 228.5 is above it, 219.5 below
    fd = make_fetch_day(day, day - timedelta(1))
    b = run(now=t(15), fetch_day=fd,
            fetch_lines=lines(228.5), fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    assert any(p["system"] == 4 and p["game_id"] == g.id for p in b["bets"])

    # total drops to 219.5 an hour later (below the 224 average) → System 4 no longer qualifies
    b = run(now=t(16), fetch_day=fd,
            fetch_lines=lines(219.5), fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    assert not any(p["system"] == 4 and p["game_id"] == g.id for p in b["bets"])
    d = [p for p in b["dropped"] if p["system"] == 4 and p["game_id"] == g.id]
    assert d and d[0]["first_line"] == 228.5


def test_run_attaches_personnel_and_fires_t13(tmp_path):
    from engine import personnel as P
    from tests.test_personnel import ath, LAST
    day = date(2025, 11, 15)
    todays = [g for g in ALL if g.game_date == day]
    # fake league: every team average except LAL (stacked) → one big clean gap
    def fake_reads():
        reads = {}
        for g in todays:
            for t in (g.home, g.away):
                roster = [ath("Star Guard")] * 7 if t == "LAL" else [ath("Role Wing")] * 10
                reads[t] = P.rate_team(t, roster, LAST)
        return reads
    lines = {(day, g.away, g.home): {"home_spread": -2.0, "total": 225.0, "source": "t", "books": 9} for g in todays}
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(day, day - timedelta(1)), fetch_lines=lambda: (lines, {}),
            fetch_kalshi=fake_kalshi, store=LocalStore(tmp_path), season_start=START, personnel_fetch=fake_reads, fetch_box=None)
    assert all(s["personnel"] for s in b["slate"] if s["date"] == day.isoformat())
    t13 = [p for p in b["tests"] if p["system"] == 113]
    assert t13 and all(p["side"] == "LAL" for p in t13)


def test_dropped_pick_still_graded_but_not_official(tmp_path):
    from engine.state import team_state
    def fits(x):
        fin = [y for y in ALL if y.game_date < x.game_date]
        return (team_state(x.home, fin, x.game_date).last_won is True
                and team_state(x.away, fin, x.game_date).last_won is False)
    g = next(x for x in ALL if x.game_date >= date(2025, 11, 10) and fits(x))
    day = g.game_date
    t = lambda d, h: datetime(d.year, d.month, d.day, h, 0, tzinfo=timezone.utc)
    lines = lambda total: (lambda: ({(day, g.away, g.home): {"home_spread": -10.5, "total": total,
                                                             "source": "t", "books": 5}}, {}))
    store = LocalStore(tmp_path)
    seed_totals(store, day)
    kw = dict(fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    run(now=t(day, 15), fetch_day=make_fetch_day(day, day - timedelta(1)), fetch_lines=lines(228.5), **kw)
    run(now=t(day, 16), fetch_day=make_fetch_day(day, day - timedelta(1)), fetch_lines=lines(219.5), **kw)
    nxt = day + timedelta(1)
    b = run(now=t(nxt, 15), fetch_day=make_fetch_day(nxt, day), fetch_lines=lambda: ({}, {}), **kw)
    p = next(p for p in store.load_picks() if p["system"] == 4 and p["game_id"] == g.id)
    assert p["result"] in ("W", "L", "P") and not p["active"]
    assert p["meta"]["result_first"] in ("W", "L", "P") and p["meta"]["clv"] == -9.0   # over 228.5 → 219.5 close
    s4 = b["systems"][4]
    assert s4["dropped"]["n"] >= 1 and all(h["active"] for h in b["history"])


def test_t13_bet_gets_a_written_case(tmp_path):
    from engine import personnel as P
    from tests.test_personnel import ath, LAST
    day = date(2025, 11, 15)
    todays = [g for g in ALL if g.game_date == day]
    def fake_reads():
        return {t: P.rate_team(t, [ath("Star Guard")] * 7 if t == "LAL" else [ath("Role Wing")] * 10, LAST)
                for g in todays for t in (g.home, g.away)}
    lines = {(day, g.away, g.home): {"home_spread": -2.0, "total": 225.0, "source": "t", "books": 9} for g in todays}
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(day, day - timedelta(1)), fetch_lines=lambda: (lines, {}),
            fetch_kalshi=fake_kalshi, store=LocalStore(tmp_path), season_start=START, personnel_fetch=fake_reads, fetch_box=None)
    cases = [s["personnel"]["case"] for s in b["slate"] if s["personnel"] and s["personnel"].get("case")]
    assert cases and all(c["side"] == "LAL" for c in cases)
    titles = [x["title"] for x in cases[0]["sections"]]
    assert titles[0] == "The bet" and titles[-1] == "Confidence"
    assert "Why we think we're right" in titles and "What could make us wrong" in titles
    assert 0.5 < cases[0]["p_cover"] < 1 and cases[0]["level"] in ("High", "Medium", "Low")
    assert not [n for n in b["notes"] if "failed" in n]


def test_t13_locks_at_first_line_when_line_moves_our_way(tmp_path):
    from engine import personnel as P
    from tests.test_personnel import ath, LAST
    day = date(2025, 11, 15)
    todays = [g for g in ALL if g.game_date == day]
    def fake_reads():
        return {t: P.rate_team(t, [ath("Star Guard")] * 7 if t == "LAL" else [ath("Role Wing")] * 10, LAST)
                for g in todays for t in (g.home, g.away)}
    store = LocalStore(tmp_path)
    kw = dict(fetch_day=make_fetch_day(day, day - timedelta(1)), fetch_kalshi=fake_kalshi, store=store,
              season_start=START, personnel_fetch=fake_reads, fetch_box=None)
    lines = lambda hs: (lambda: ({(day, g.away, g.home): {"home_spread": hs if "LAL" in (g.home, g.away) else -2.0,
                                                          "total": 225.0, "source": "t", "books": 9} for g in todays}, {}))
    b1 = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc), fetch_lines=lines(-2.0), **kw)
    first = [p for p in b1["tests"] if p["system"] == 113]
    assert first
    # the market moves hard toward LAL (the model's side) — the gap disappears, the bet must stay
    lal = next(p for p in first)
    moved = -30.0 if lal["side"] == "LAL" and lal["home"] == "LAL" else 30.0
    b2 = run(now=datetime(2025, 11, 15, 16, 0, tzinfo=timezone.utc), fetch_lines=lines(moved), **kw)
    still = [p for p in b2["tests"] if p["key"] == lal["key"]]
    assert still and still[0]["line"] == lal["first_line"] and still[0]["active"]


def test_card_line_shops_kalshi_and_exchanges(tmp_path):
    store = LocalStore(tmp_path)
    morning = datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc)
    px = {"venue": "prophetx", "venue_name": "ProphetX", "bet": "spread", "side": "LAL", "line": 7.0, "ml": False,
          "american": -105, "cost": round(105 / 205, 4), "fee_counted": False, "size": 900,
          "contract": "LAL +7", "url": None, "ticker": None}
    board = run(now=morning, fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)),
                fetch_lines=fake_lines, fetch_kalshi=fake_kalshi, store=store, season_start=START,
                personnel_fetch=None, fetch_box=None,
                fetch_exchanges=lambda: ({(date(2025, 11, 15), "LAL", "MIL"): [px]}, {}))
    c = next(c for c in board["card"] if c["tag"] == "S1")
    venues = {q["venue"] for q in c["shop"]}
    assert venues == {"kalshi", "prophetx"}
    assert c["best"]["venue"] == "prophetx" and c["best"]["line"] == 7.0      # a point better at -105
    assert all("shop" not in p for p in board["bets"])                         # prices only on the card
    feed = store._read("bet_feed", [])
    assert feed and feed[0]["best_venue"] == "prophetx" and feed[0]["status"] == c["verdict"].lower()


def test_tipped_card_bets_stay_up_with_their_result(tmp_path):
    store = LocalStore(tmp_path)
    kw = dict(fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines, **kw)
    assert any(c["tag"] == "S1" for c in b["card"]) and not b["card_done"]
    # during the game: off the card, shown as in progress
    b = run(now=datetime(2025, 11, 16, 1, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=lambda: ({}, {}), **kw)
    assert not any(c["tag"] == "S1" for c in b["card"])
    assert [(r["tag"], r["status"]) for r in b["card_done"] if r["tag"] == "S1"] == [("S1", "IN PROGRESS")]
    assert all(r["status"] == "IN PROGRESS" for r in b["card_done"])
    # next morning: graded, still shown
    b = run(now=datetime(2025, 11, 16, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 16), date(2025, 11, 15)), fetch_lines=lambda: ({}, {}), **kw)
    r = next(r for r in b["card_done"] if r["tag"] == "S1")
    assert (r["tag"], r["status"], r["result"]) == ("S1", "FINAL", "W") and "119" in r["final_score"]


def test_units_risk_one_point_one_to_win_one():
    from engine.run import _wl
    assert _wl(["W"])["units"] == 1.0 and _wl(["W", "L"])["units"] == -0.1


def test_gap_tracker_splits_every_game_by_gap_and_confidence():
    from engine.run import gap_tracker
    def x1(gid, gap, res, level=None):
        return {"system": 301, "active": True, "game_id": gid, "result": res,
                "meta": {"gap_first": gap, "result_first": res, "clv": 0.5, "level_first": level}}
    picks = [x1("a", 1.0, "W"), x1("b", 3.2, "W", "Medium"), x1("c", 3.6, "L", "Low"), x1("d", 5.5, "W", "High"),
             x1("e", 2.5, None)]
    t = gap_tracker(picks, season_day=1)
    assert t["by_gap"]["0-2"]["w"] == 1 and t["by_gap"]["3-4"]["w"] == 1 and t["by_gap"]["3-4"]["l"] == 1
    assert t["by_gap"]["5+"]["w"] == 1 and t["by_gap"]["3+"]["n"] == 3
    assert t["by_confidence"]["Low"]["l"] == 1 and t["by_confidence"]["High"]["w"] == 1
    assert t["pending"] == 1 and t["window"] == "days 0-30"
    assert "3+" in t["history_by_gap"]["whole season"]


def test_card_bet_shows_its_real_record_and_it_grows():
    store = LocalStore(tmp := __import__("tempfile").mkdtemp())
    kw = dict(fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines, **kw)
    c = next(c for c in b["card"] if c["tag"] == "S1")
    assert c["record"]["history"]["w"] == 218 and c["record"]["history"]["l"] == 143      # the 23-year card, as-is
    assert (c["record"]["w"], c["record"]["l"]) == (218 + c["record"]["season"]["w"], 143 + c["record"]["season"]["l"])


def test_systems_behind_the_close_get_benched_until_switched_back_on():
    from engine.run import benched_systems
    recs = {1: {"tag": "S1", "avg_clv": -0.4, "n_clv": 31}, 2: {"tag": "S2", "avg_clv": -0.4, "n_clv": 29},
            3: {"tag": "S3", "avg_clv": 0.3, "n_clv": 50}, 4: {"tag": "S4", "avg_clv": 0.1, "n_clv": 5}}
    b = benched_systems(recs, None)
    assert list(b) == ["S1"] and "31 picks" in b["S1"]["why"]          # S2 has too few picks to judge
    assert benched_systems(recs, {"unbench": ["S1"]}) == {}
    assert set(benched_systems(recs, {"bench": ["S4"]})) == {"S1", "S4"}


def test_a_benched_system_stays_on_the_card_but_is_not_a_bet(tmp_path, monkeypatch):
    import engine.run as R
    monkeypatch.setattr(R, "BENCH_MIN_PICKS", 0)
    store = LocalStore(tmp_path)
    store._write("config", {"bench": {"bench": ["S1"]}})
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines,
            fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    c = next(c for c in b["card"] if c["tag"] == "S1")
    assert c["verdict"] == "BENCHED" and "benched by hand" in c["why"] and "S1" in b["benched"]
    feed = {r["key"]: r for r in store._read("bet_feed", [])}
    assert feed[c["key"]]["status"] == "benched"                      # the order placer only bets status 'bet'


def test_excluded_bets_leave_every_record_but_stay_visible():
    from engine.run import excluded_keys
    ex = excluded_keys([{"game_id": 401909843, "side": "CHA", "why": "model bug"}, {"side": "X"}])
    assert ex == {("401909843", "CHA"): "model bug"}


def test_excluded_game_leaves_records_and_placed_ledger(tmp_path):
    store = LocalStore(tmp_path)
    morning = datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc)
    board = run(now=morning, fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)),
                fetch_lines=fake_lines, fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    b = board["bets"][0]
    store._write("bet_orders", [{"id": "o1", "mode": "live", "status": "filled", "venue": "kalshi", "bet_key": b["key"],
                                 "game_id": b["game_id"], "side": "LAL", "line": 6.5, "bet": "spread", "pick": "LAL +6",
                                 "fill_count": 40, "fill_cost": 22.0, "fees": 0.5, "tip_utc": b["tip_utc"],
                                 "created_at": "2025-11-15T15:00:00+00:00", "system": "S1"}])
    store._write("config", {"exclude": [{"game_id": b["game_id"], "side": "LAL", "why": "test bug"}]})
    nxt = datetime(2025, 11, 16, 15, 0, tzinfo=timezone.utc)
    board = run(now=nxt, fetch_day=make_fetch_day(date(2025, 11, 16), date(2025, 11, 15)),
                fetch_lines=lambda: ({}, {}), fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    assert board["systems"][1]["w"] == 0 and board["systems"][1]["l"] == 0          # out of the system record
    assert not [p for p in board["history"] if p["key"] == b["key"]]
    assert board["placed"]["bets"] == [] and board["placed"]["summary"]["w"] == 0  # out of the money record
    ex = board["placed"]["excluded"]
    assert len(ex) == 1 and ex[0]["result"] == "W" and ex[0]["why"] == "test bug"      # but still shown
    assert board["placed"]["summary"]["excluded_pnl"] == ex[0]["pnl"] > 0


def test_restart_drops_old_bets_but_keeps_every_tracked_pick(monkeypatch):
    """Caden 2026-10-27: money restarts Oct 27; system tracking keeps every pick each system really made."""
    import engine.run as R
    monkeypatch.setattr(R, "RESTART_UTC", "2026-10-27T04:00:00+00:00")
    picks = [{"system": 4, "result": "W", "line": 224.5, "game_date": "2026-10-26", "meta": {}},
             {"system": 113, "result": "W", "line": 3.0, "game_date": "2026-10-26", "meta": {"worst_gap": 3.4}},
             {"system": 102, "result": "L", "line": -3.0, "game_date": "2026-10-22", "meta": {}}]
    orders = [{"created_at": "2026-10-26T15:00:00+00:00", "tip_utc": "2026-10-26T23:00:00+00:00"},
              {"created_at": "2026-10-26T22:00:00+00:00", "tip_utc": "2026-10-28T00:00:00+00:00"}]
    p, o = R.since_restart(picks, orders, {})
    assert p == picks and o == [orders[1]]

def test_bet_on_a_pick_that_no_longer_counts_is_still_judged(tmp_path, monkeypatch):
    """A T13 bet placed under the old 3-point rule: its pick is out of the records, but the ledger must still
    see the pick's gap (and group) so the bet is marked not counted, without crashing the board."""
    import engine.run as R
    from datetime import date, datetime, timezone
    pick = {"key": "g1-S113-LAL", "system": 113, "game_id": "g1", "bet": "spread", "side": "LAL", "line": -3.0,
            "label": "LAL -3", "away": "X", "home": "LAL", "game_date": "2026-10-27", "tip_utc": "2026-10-28T02:00:00+00:00",
            "active": True, "result": None, "meta": {"worst_gap": 3.3}}
    order = {"id": 1, "bet_key": "g1-S113-LAL", "game_id": "g1", "side": "LAL", "bet": "spread", "line": -3.0, "system": "T13",
             "venue": "prophetx", "status": "filled", "fill_count": 24.4, "fill_cost": 14.0, "fees": 0, "pick": "LAL -3",
             "created_at": "2026-10-27T12:00:00+00:00", "tip_utc": "2026-10-28T02:00:00+00:00"}
    now = datetime(2026, 10, 27, 20, tzinfo=timezone.utc)
    b = R.build_board(now, date(2026, 10, 27), [], [pick], {}, [], "t", orders=[order], games={})
    row = b["placed"]["bets"][0]
    assert row["t13_gap"] == 3.3 and row["rules"]["counted"] is False
