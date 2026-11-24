"""Placed bets on the website: what we bought, where, at what price, why, and how it finished."""
from datetime import date, datetime, timezone

from engine.placed import american, grade, holding, placed_bets
from engine.run import run
from engine.store import LocalStore
from tests.test_run import START, fake_kalshi, fake_lines, lal_reads, make_fetch_day


def test_american_odds_and_what_we_hold():
    assert american(0.43) == 133 and american(0.55) == -122 and american(0.5) == 100
    assert holding({"side": "NOP", "line": 1.5, "bet": "spread"}) == "NOP +1.5"
    assert holding({"side": "MEM", "line": -1.0, "bet": "spread"}) == "MEM −1"
    assert holding({"side": "OVER", "line": 221.5, "bet": "total"}) == "OVER 221.5"
    assert holding({"side": "NOP", "line": -0.5, "bet": "spread", "market": "KXNBAGAME-26OCT21INDNOP-NOP"}) == "NOP ML"


def test_graded_at_the_number_we_hold_not_the_card_number():
    g = {"final": True, "home": "NOP", "away": "IND", "home_score": 110, "away_score": 113}
    assert grade({"side": "NOP", "line": 3.5, "bet": "spread"}, g) == "W"     # card number covers
    assert grade({"side": "NOP", "line": 1.5, "bet": "spread"}, g) == "L"     # the number we bought doesn't
    assert grade({"side": "NOP", "line": 3.0, "bet": "spread"}, g) == "P"
    assert grade({"side": "UNDER", "line": 224.5, "bet": "total"}, g) == "W"
    assert grade({"side": "NOP", "line": 1.5}, {**g, "final": False}) is None


def test_summary_counts_risk_fees_and_results():
    now = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
    o = lambda **k: {"mode": "live", "venue": "kalshi", "bet_key": "k1", "game_id": "g1", "tip_utc": "2026-10-21T23:30:00+00:00",
                     "bet": "spread", "side": "NOP", "line": 1.5, "fill_count": 37, "fill_cost": 15.91, "fees": 0.63,
                     "created_at": "2026-10-21T01:40:00+00:00", "ev": 0.127, **k}
    games = {"g1": {"final": True, "home": "NOP", "away": "IND", "home_score": 115, "away_score": 108},
             "g2": {"final": False, "home": "MEM", "away": "UTA"}}
    picks = {"k1": {"key": "k1", "system": 113, "group": "FAV", "away": "IND", "home": "NOP", "meta": {
        "card_snap": {"name": "Players model", "why": "edge 4.2", "confidence": "Medium",
                      "history": {"w": 157, "l": 141, "label": "2 seasons"}}}}}
    out = placed_bets([o(), o(bet_key="k2", game_id="g2", venue="betopenly", fill_count=40, fill_cost=20.0, fees=0.2,
                         tip_utc="2026-10-23T00:00:00+00:00")],
                      picks, games, {}, lambda p: {"w": 1, "l": 0, "p": 0}, now)
    won, open_ = out["bets"][1], out["bets"][0]
    assert (won["status"], won["result"], won["holding"], won["venue_name"]) == ("FINAL", "W", "NOP +1.5", "Kalshi")
    assert won["risk"] == 16.54 and won["to_win"] == 20.46 and won["pnl"] == 20.46 and won["american"] == 124   # fee included: 20.46 / 16.54 (was +133 before the fee)
    assert won["price_note"] == "edge 4.2" and won["record"]["w"] == 158 and won["record"]["l"] == 141
    assert open_["status"] == "OPEN" and open_["risk"] == 20.0 and open_["to_win"] == 19.8      # BetOpenly: fee from winnings
    s = out["summary"]
    assert (s["open"], s["w"], s["l"], s["pnl"], s["at_risk"]) == (1, 1, 0, 20.46, 20.0)
    assert s["by_venue"]["Kalshi"]["pnl"] == 20.46 and s["by_venue"]["BetOpenly"]["open"] == 1


def test_placed_bet_keeps_its_reasoning_after_it_tips_and_grades(tmp_path):
    store = LocalStore(tmp_path)
    kw = dict(fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=lal_reads(), fetch_box=None)
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines, **kw)
    c = next(c for c in b["card"] if c["side"] == "LAL")           # S1 + T24 + players model: MONEYBALL
    assert c["tag"] == "MONEYBALL" and b["placed"]["bets"] == []
    store._write("bet_orders", [{"id": "o1", "mode": "live", "venue": "kalshi", "bet_key": c["key"], "game_id": c["game_id"],
                                 "tip_utc": c["tip_utc"], "pick": c["label"], "system": "MONEYBALL", "bet": "spread", "side": "LAL",
                                 "line": 6.5, "contract": "NO · MIL wins by over 6.5 (= LAL +6.5)", "status": "filled",
                                 "fill_count": 36, "fill_cost": 19.8, "fees": 0.6, "ev": 0.08,
                                 "created_at": "2025-11-15T15:01:00+00:00"}])
    # the next run (minutes later, as in production) freezes what the card said when we bet
    run(now=datetime(2025, 11, 15, 15, 6, tzinfo=timezone.utc),
        fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines, **kw)
    # during the game: off the card, but the bet still says why we took it
    b = run(now=datetime(2025, 11, 16, 1, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=lambda: ({}, {}), **kw)
    assert not any(x["key"] == c["key"] for x in b["card"])
    # the card's reasoning when we bet is frozen on the pick and never rewritten (Caden 2026-11-10, the Hawks bet)
    snap = next(p for p in store.load_picks() if p["key"] == c["key"])["meta"]["bet_snap"]
    assert snap["why"] == c["why"] and snap["players"] == c["players"] and snap["frozen_at"].startswith("2025-11-15T15:06")
    r = b["placed"]["bets"][0]
    assert (r["status"], r["holding"], r["price_note"], r["name"]) == ("LIVE", "LAL +6.5", c["why"], c["name"])
    assert r["evidence"] and "S1, T24" in r["evidence"][0]           # the MONEYBALL pick's own notes
    assert r["record"]["history"] == c["record"]["history"]
    # next morning: graded at +6.5 (LAL won 119-95)
    b = run(now=datetime(2025, 11, 16, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 16), date(2025, 11, 15)), fetch_lines=lambda: ({}, {}), **kw)
    r = b["placed"]["bets"][0]
    assert (r["status"], r["result"], r["pnl"]) == ("FINAL", "W", 15.6)
    assert r["record"]["season"]["w"] == 1                              # the system's own graded pick counts this season
    assert b["placed"]["summary"]["pnl"] == 15.6


def test_line_movement_and_beating_the_close():
    from engine.placed import beat_close, moved_our_way, number
    assert number("NOP +3.5") == 3.5 and number("MEM −1") == -1 and number("OVER 220.5") == 220.5 and number("x") is None
    assert moved_our_way("spread", "NOP", 3.5, 2.5) == 1.0          # dog got a point more than the close
    assert moved_our_way("total", "OVER", 220.5, 222.5) == 2.0 and moved_our_way("total", "UNDER", 220.5, 222.5) == -2.0
    o = {"bet": "spread", "side": "NOP", "line": 1.5}
    assert beat_close(o, 0.43, 1.5) == 7.0                              # 50¢ fair at the close, paid 43¢
    # +1.5 when the close is +3.5: two points short, worth 7.4% less (measured) -> 42.6¢, so 43¢ was 0.4¢ too much
    assert beat_close(o, 0.43, 3.5) == -0.4
    assert beat_close(o, 0.43, -0.5) > 7.0                               # market moved our way: NOP now favoured
    assert beat_close(o, 0.43, 8.5) < 0                                  # market moved hard against us


def test_open_bet_tracks_the_market_and_live_bet_shows_if_covering():
    now = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)
    o = {"mode": "live", "venue": "kalshi", "bet_key": "k1", "game_id": "g1", "pick": "NOP +3.5", "bet": "spread",
         "side": "NOP", "line": 1.5, "fill_count": 37, "fill_cost": 15.91, "fees": 0.63, "created_at": "2026-10-21T01:40:00+00:00"}
    picks = {"k1": {"key": "k1", "system": 113, "group": "FAV", "away": "IND", "home": "NOP"}}
    later = {**o, "tip_utc": "2026-10-23T00:00:00+00:00"}
    r = placed_bets([later], picks, {}, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now, lambda gid, bet, side: 2.5)["bets"][0]
    assert r["market"]["moved"] == 1.0 and r["market"]["closed"] is False and r["market"]["line"] == 2.5
    live = {**o, "tip_utc": "2026-10-22T00:00:00+00:00"}
    g = {"g1": {"final": False, "home": "NOP", "away": "IND", "home_score": 88, "away_score": 90, "home_spread": 3.5}}
    r = placed_bets([live], picks, g, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now)["bets"][0]
    assert r["status"] == "LIVE" and r["covering"] == -0.5                     # down 2 with +1.5
    assert r["market"]["line"] == 3.5 and r["market"]["closed"]                # NOP home dog +3.5 at the close


def test_placer_skip_reasons_reach_the_board(tmp_path):
    store = LocalStore(tmp_path)
    store._write("bet_log", [{"ts": "2025-11-15T14:59:00+00:00", "message": "run (live, prod): 1 bets", "level": "info",
                              "data": {"skips": [{"pick": "LAL +6 (S1) LAL@MIL", "reason": "price moved"}]}}])
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines,
            fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    assert b["placer"]["skips"][0]["reason"] == "price moved"


def test_a_bet_placed_by_hand_counts_like_any_other():
    o = {"venue": "manual", "bet_key": "k", "game_id": "g", "tip_utc": "2026-10-20T19:00Z", "pick": "DET +1.5", "system": "T13",
         "bet": "spread", "side": "DET", "line": 1.5, "fill_count": 40.8, "fill_cost": 20.8, "fees": 0,
         "created_at": "2026-10-20T18:00:00Z"}
    g = {"g": {"final": True, "home": "DET", "away": "BOS", "home_score": 121, "away_score": 113, "home_spread": 1.5}}
    out = placed_bets([o], {"k": {"key": "k", "system": 113, "group": "FAV", "away": "BOS", "home": "DET"}}, g, {},
                      lambda p: {"w": 1, "l": 0, "p": 0}, datetime(2026, 10, 21, 3, tzinfo=timezone.utc), names={"T13": "Personnel gap"})
    r = out["bets"][0]
    assert (r["venue_name"], r["manual"], r["american"], r["risk"], r["to_win"]) == ("Other book", True, -104, 20.8, 20.0)
    assert (r["result"], r["pnl"], r["name"]) == ("W", 20.0, "Personnel gap")
    assert out["summary"]["w"] == 1 and out["summary"]["pnl"] == 20.0


def test_resting_orders_are_listed_as_waiting_for_a_price():
    now = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc)
    o = {"mode": "live", "venue": "kalshi", "status": "resting", "bet_key": "k", "game_id": "g", "pick": "NOP +3.5",
         "system": "T13", "bet": "spread", "side": "NOP", "line": 3.5, "limit_price": 0.54, "count": 44, "stake": 23.76,
         "fill_count": 0, "fill_cost": 0, "tip_utc": "2026-10-22T00:00:00+00:00", "created_at": "2026-10-21T15:00:00+00:00",
         "contract": "NO · IND wins by over 3.5 (= NOP +3.5)"}
    out = placed_bets([o], {}, {}, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now)
    assert out["bets"] == [] and out["resting"][0]["holding"] == "NOP +3.5" and out["resting"][0]["american"] == -117



def test_a_bet_bought_at_two_numbers_is_graded_where_most_of_the_money_is():
    # Nov 3: CHI +12 card pick; 6 contracts at +12.5 (53c), then 32 at +10.5 (43-44c)
    from engine.placed import merge_fills
    r = lambda i, hold, line, cnt, cost, res: {"id": i, "game_id": "g", "bet": "spread", "side": "CHI", "holding": hold,
        "line": line, "count": cnt, "cost": cost, "fees": 0.1, "risk": cost + 0.1, "to_win": cnt - cost - 0.1,
        "price": cost / cnt, "american": None, "venue_name": "Kalshi", "placed_at": i, "status": "FINAL",
        "result": res, "pnl": round(cnt - cost - 0.1, 2) if res == "W" else -round(cost + 0.1, 2), "system": "E4", "with": []}
    out = merge_fills([r("a", "CHI +12.5", 12.5, 6, 3.18, "W"), r("b", "CHI +10.5", 10.5, 25, 11.0, "L"),
                       r("c", "CHI +10.5", 10.5, 7, 3.01, "L")])
    assert len(out) == 1
    b = out[0]
    assert b["holding"] == "CHI +10.5" and b["line"] == 10.5 and b["result"] == "L"
    assert b["price"] == round(14.01 / 32, 4)                       # the +10.5 piece's own price, not an average
    assert [p["count"] for p in b["pieces"]] == [32, 6] and b["placed_at"] == "a" and b["pnl"] == round(2.72 - 11.1 - 3.11, 2)



def test_a_game_that_lands_between_our_two_numbers_counts_once_at_the_main_number():
    # Bulls lose by 11: the 6 at +12.5 win, the 32 at +10.5 lose. ONE bet in the record, graded at +10.5: a loss.
    from engine.placed import merge_fills, rules_now
    r = lambda i, hold, line, cnt, cost, res, pnl: {"id": i, "game_id": "g", "bet": "spread", "side": "CHI",
        "holding": hold, "line": line, "count": cnt, "cost": cost, "fees": 0.0, "risk": cost, "to_win": cnt - cost,
        "price": cost / cnt, "american": None, "venue_name": "Kalshi", "placed_at": i, "status": "FINAL",
        "result": res, "pnl": pnl, "system": "E4", "with": [], "ev": 0.08, "card_pick": "CHI +12",
        "players": 4.0}
    b = merge_fills([r("a", "CHI +12.5", 12.5, 6, 3.2, "W", 2.80), r("b", "CHI +10.5", 10.5, 32, 14.47, "L", -14.47)])[0]
    assert b["result"] == "L" and b["pnl"] == -11.67                 # real money: both pieces
    out = rules_now([b])
    assert (out["w"], out["l"]) == (0, 1) and out["pnl"] == -b["rules"]["risk"]   # record: one full $20-size loss



def test_clv_in_points_against_the_close():
    # Nov 4: MEM -4.5 held, closed MEM -6 -> +1.5 points; MIN +8.5 held, closed MIN +7.5 -> +1
    from engine.placed import placed_bets
    now = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
    games = {"g": {"final": True, "home": "MEM", "away": "IND", "home_score": 103, "away_score": 107, "home_spread": -6.0}}
    o = {"id": "o", "mode": "live", "venue": "prophetx", "bet_key": "k", "game_id": "g", "tip_utc": "2026-11-05T00:00:00+00:00",
         "bet": "spread", "side": "MEM", "line": -4.5, "pick": "MEM -6", "fill_count": 37.14, "fill_cost": 17.14, "fees": 0,
         "created_at": "2026-11-04T15:00:00+00:00", "ev": 0.25, "system": "T13"}
    picks = {"k": {"key": "k", "system": 113, "home": "MEM", "away": "IND", "meta": {"close_line": -6.0, "worst_gap": 4.3}}}
    r = placed_bets([o], picks, games, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now)["bets"][0]
    assert r["clv_pts"] == 1.5 and r["market"]["closed"]


def test_ticket_price_includes_the_fee_like_kalshi_shows_it():
    # MEM +2.5, Nov 6: 30 contracts at 46c + 52c fee = $14.32 for a $30 payout. that is +109 (15.68 / 14.32), not the pre-fee +117.
    from engine.placed import all_in
    assert all_in(14.32, 30 - 14.32) == 109
    assert all_in(0, 5) is None and all_in(5, 0) is None


def test_a_bet_placed_under_todays_rules_stays_in_the_record_when_a_later_read_changes():
    # Nov 9, ATL +2.5 (S109): the players model backed ATL by 3.4 when we bet at 10:44 PM; by morning it had moved
    # to the Lakers. The bet lost. It must stay in the record (it was a BET under today's rule when placed).
    # A T13 bet placed at a 4+ gap stays in too after its gap later shrinks.
    from engine.placed import placed_bets
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    games = {"g": {"final": True, "home": "ATL", "away": "LAL", "home_score": 114, "away_score": 124},
             "h": {"final": True, "home": "MEM", "away": "OKC", "home_score": 110, "away_score": 100}}
    o = lambda **k: {"mode": "live", "venue": "prophetx", "bet": "spread", "status": "filled", "ev": 0.12,
                     "fill_count": 43, "fill_cost": 22.42, "fees": 0, **k}
    orders = [o(id="a", bet_key="g-S109-ATL", game_id="g", side="ATL", line=2.5, pick="ATL +2.5", system="S109",
                created_at="2026-11-09T03:44:06Z", tip_utc="2026-11-10T00:00:00+00:00"),
              o(id="b", bet_key="h-S113-MEM", game_id="h", side="MEM", line=3.5, pick="MEM +4", system="T13",
                created_at="2026-11-06T12:23:04Z", tip_utc="2026-11-07T01:00:00+00:00")]
    picks = {"g-S109-ATL": {"key": "g-S109-ATL", "system": 109, "away": "LAL", "home": "ATL",
                            "meta": {"card_snap": {"players": None, "why": "No bet: no clean read"},
                                     "bet_snap": {"players": 3.4, "why": "Best price: ProphetX ATL +2.5"}}},
             "h-S113-MEM": {"key": "h-S113-MEM", "system": 113, "away": "OKC", "home": "MEM",
                            "meta": {"worst_gap": 1.5, "bet_snap": {"players": 5.0, "worst_gap": 5.0}}}}
    out = placed_bets(orders, picks, games, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now, agree=lambda g, s: 0.1)
    atl = next(r for r in out["bets"] if r["side"] == "ATL")
    mem = next(r for r in out["bets"] if r["side"] == "MEM")
    assert atl["rules"]["counted"] and atl["result"] == "L" and atl["players"] == 3.4
    assert atl["price_note"] == "Best price: ProphetX ATL +2.5"            # the reason we bet, not the later one
    assert mem["rules"]["counted"] and mem["players"] == 5.0
    assert (out["rules_now"]["w"], out["rules_now"]["l"]) == (1, 1)


def test_an_old_ticket_never_shows_a_later_no_bet_reason_as_why_we_bet():
    # POR +1.5 (T7), placed Nov 10 03:01 UTC before snapshots were frozen; the card later said "No bet: players
    # model only likes POR by 1.2". That isn't why we bet. Still counted (it passed the rule when placed).
    from engine.placed import OLD_NOTE, placed_bets
    now = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
    o = {"id": "o", "mode": "live", "venue": "betopenly", "bet_key": "k", "game_id": "g", "bet": "spread", "side": "POR",
         "line": 1.5, "pick": "POR +1.5", "system": "T7", "fill_count": 41, "fill_cost": 20.4, "fees": 0, "ev": 0.11,
         "created_at": "2026-11-10T03:01:03Z", "tip_utc": "2026-11-11T04:00:00+00:00", "status": "filled"}
    picks = {"k": {"key": "k", "system": 107, "away": "OKC", "home": "POR",
                   "meta": {"card_snap": {"players": 1.2, "why": "No bet: the players model only likes POR by 1.2"}}}}
    r = placed_bets([o], picks, {}, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now)["bets"][0]
    assert r["price_note"] == OLD_NOTE and r["players"] is None and r["rules"]["counted"]


def test_rules_now_counts_a_t13_thin_fade_bet_at_40():
    from engine.placed import rules_now
    rows = [{"status": "FINAL", "bet": "spread", "manual": False, "game_id": "g1", "side": "BOS", "system": "T13",
             "t13_gap": 4.5, "holding": "BOS -3", "result": "W", "pnl": 40.0, "risk": 44.0, "to_win": 40.0, "target": 40},
            {"status": "FINAL", "bet": "spread", "manual": False, "game_id": "g2", "side": "DET", "system": "T13",
             "t13_gap": 4.5, "holding": "DET -3", "result": "W", "pnl": 20.0, "risk": 22.0, "to_win": 20.0, "target": 20}]
    r = rules_now(rows)
    assert rows[0]["rules"]["to_win"] == 40.0 and rows[1]["rules"]["to_win"] == 20.0 and r["pnl"] == 60.0



def test_every_placed_bet_counts_and_rules_only_change_its_size():
    # Caden 2026-11-24: a placed bet always counts; a later rule change can't create "not counted" bets. Sizes still
    # follow today's rules (MONEYBALL is 2 units only as the underdog).
    from engine.placed import rules_now
    base = {"status": "FINAL", "bet": "spread", "t13_gap": 5.0, "result": "W", "pnl": 20.0, "risk": 21.0,
            "to_win": 20.0, "ev": 0.01}
    rows = [{**base, "game_id": "a", "side": "DET", "system": "MONEYBALL", "holding": "DET -9.5", "line": -9.5},
            {**base, "game_id": "b", "side": "WAS", "system": "MONEYBALL", "holding": "WAS +6.5", "line": 6.5},
            {**base, "game_id": "c", "side": "GSW", "system": "T6", "holding": "GSW -2.5", "line": -2.5, "players": 0.5},
            {**base, "game_id": "d", "side": "O", "system": "S4", "bet": "total", "holding": "OVER 231.5", "line": 231.5},
            {**base, "game_id": "e", "side": "TOR", "system": "MOVE+THIN", "holding": "TOR +6.5", "line": 6.5,
             "card_pick": "TOR +2.5", "resting_fill": True}]
    out = rules_now(rows)
    assert all(r["rules"]["counted"] for r in rows) and out["w"] == 5 and not out["dropped"]
    assert rows[0]["rules"]["to_win"] == 20.0 and rows[1]["rules"]["to_win"] == 40.0


def test_the_13_not_counted_bets_are_deleted_from_courtside():
    from engine.placed import HIDDEN
    for k in ("401909899-S4-OVER", "401909910-S130-BKN", "401909910-S112-NYK", "401909921-S204-LAL",
              "401909921-S102-MIA", "401909957-S113-DEN", "401910000-S106-GSW", "401910012-S135-WAS"):
        assert k in HIDDEN
