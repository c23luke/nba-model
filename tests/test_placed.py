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
    # during the game: off the card, but the bet still says why we took it
    b = run(now=datetime(2025, 11, 16, 1, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=lambda: ({}, {}), **kw)
    assert not any(x["key"] == c["key"] for x in b["card"])
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


def test_rules_now_drops_small_t13_and_both_sides_and_resizes_to_20():
    from engine.placed import rules_now
    base = {"status": "FINAL", "bet": "spread", "manual": False}
    rows = [
        {**base, "game_id": "g1", "side": "DET", "system": "T13", "t13_gap": 3.4, "holding": "DET +4",
         "result": "W", "pnl": 20.0, "risk": 24.6, "to_win": 20.0},                     # gap under 4 -> dropped
        {**base, "game_id": "g2", "side": "BOS", "system": "T13", "t13_gap": 5.0, "holding": "BOS -7",
         "result": "L", "pnl": -11.0, "risk": 11.0, "to_win": 10.0},                     # $10 bet -> $20 at -110
        {**base, "game_id": "g3", "side": "MIA", "system": "S4", "t13_gap": None, "holding": "MIA +3",
         "result": "W", "pnl": 20.0, "risk": 22.0, "to_win": 20.0},
        {**base, "game_id": "g3", "side": "NYK", "system": "T2", "t13_gap": None, "holding": "NYK -3",
         "result": "L", "pnl": -22.0, "risk": 22.0, "to_win": 20.0},                     # both sides of g3 -> both dropped
    ]
    r = rules_now(rows)
    assert (r["w"], r["l"]) == (0, 1)
    assert r["pnl"] == -22.0 and len(r["dropped"]) == 3
    assert r["resized"][0]["had"] == 10.0 and r["resized"][0]["pnl_now"] == -22.0


def test_rules_now_marks_every_row_and_projects_open_bets_at_20():
    from engine.placed import rules_now
    rows = [{"status": "OPEN", "bet": "spread", "game_id": "g9", "side": "BOS", "system": "MONEYBALL", "t13_gap": None,
             "holding": "BOS -7.5", "result": None, "pnl": None, "risk": 12.0, "to_win": 11.51},
            {"status": "OPEN", "bet": "spread", "game_id": "g8", "side": "DET", "system": "T13", "t13_gap": 3.2,
             "holding": "DET +4", "result": None, "pnl": None, "risk": 24.6, "to_win": 20.0}]
    r = rules_now(rows)
    assert rows[0]["rules"] == {"counted": True, "to_win": 40.0, "risk": round(40 * 12.0 / 11.51, 2), "pnl": None}
    assert rows[1]["rules"]["counted"] is False and r["open"] == 1 and r["open_to_win"] == 40.0


def test_rules_now_no_totals_count_s4_is_tracking_only():
    # Caden 2026-11-03: only bets that hit a lot; S4 (56%) is tracking only, so no total counts in the record
    from engine.placed import rules_now
    base = {"status": "FINAL", "bet": "total", "side": "OVER", "system": "S4", "t13_gap": None, "result": "W", "pnl": 20,
            "risk": 19.0, "to_win": 20.0, "ev": 0.1, "s4_bar": 230.0}
    rows = [{**base, "game_id": "a", "holding": "OVER 233.5", "line": 233.5, "card_pick": "OVER 233.5"}]
    out = rules_now(rows)
    assert rows[0]["rules"]["counted"] is False and "totals" in rows[0]["rules"]["why"] and out["w"] == 0


def test_rules_now_applies_todays_price_rules():
    from engine.placed import rules_now
    base = {"status": "OPEN", "bet": "spread", "side": "BOS", "system": "MONEYBALL", "t13_gap": None, "result": None,
            "pnl": None, "risk": 20.0, "to_win": 20.0}
    rows = [{**base, "game_id": "a", "holding": "BOS +3.5", "line": 3.5, "card_pick": "BOS +3.5", "ev": 0.038},   # under 4%
            {**base, "game_id": "b", "holding": "BOS +3.5", "line": 3.5, "card_pick": "BOS +5.5", "ev": 0.06,
             "resting_fill": True},                                                                         # standing, 2 pts off
            {**base, "game_id": "c", "holding": "BOS +4.5", "line": 4.5, "card_pick": "BOS +5.5", "ev": 0.06,
             "risk": 22.0}]                                                                                 # fine
    rules_now(rows)
    assert [r["rules"]["counted"] for r in rows] == [False, False, True]
    assert "4%" in rows[0]["rules"]["why"] and "within 1" in rows[1]["rules"]["why"]


def test_split_fills_are_one_bet_and_systems_need_the_players_model():
    # Nov 1: LAL -2.5 filled in two pieces on ProphetX (8.99 then 30.99 contracts): ONE bet.
    # Nov 2: WAS +1.5 (T2) with the players model liking the other side: not counted under today's rule.
    from engine.placed import placed_bets
    now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
    games = {"g1": {"final": True, "home": "LAL", "away": "TOR", "home_score": 131, "away_score": 125},
             "g2": {"final": True, "home": "ORL", "away": "WAS", "home_score": 94, "away_score": 103}}
    o = lambda **k: {"mode": "live", "venue": "prophetx", "bet": "spread", "status": "filled", "ev": 0.30,
                     "tip_utc": "2026-11-02T02:00:00+00:00", **k}
    orders = [o(id="a", bet_key="g1-S204-LAL", game_id="g1", side="LAL", line=-2.5, pick="LAL -4.5", system="E4",
                fill_count=8.99, fill_cost=4.26, fees=0.09, created_at="2026-11-01T15:01:05Z"),
              o(id="b", bet_key="g1-S204-LAL", game_id="g1", side="LAL", line=-2.5, pick="LAL -4.5", system="E4",
                fill_count=30.99, fill_cost=14.83, fees=0.32, created_at="2026-11-01T15:02:05Z"),
              o(id="c", bet_key="g2-S102-WAS", game_id="g2", side="WAS", line=1.5, pick="WAS +1.5", system="T2",
                fill_count=41, fill_cost=20.5, fees=0.41, ev=0.0445, created_at="2026-11-02T01:11:06Z",
                tip_utc="2026-11-03T00:30:00+00:00")]
    picks = {"g1-S204-LAL": {"key": "g1-S204-LAL", "system": 204, "away": "TOR", "home": "LAL", "meta": {"card_snap": {"players": 3.1}}},
             "g2-S102-WAS": {"key": "g2-S102-WAS", "system": 102, "away": "WAS", "home": "ORL", "meta": {"card_snap": {"players": -0.7}}}}
    out = placed_bets(orders, picks, games, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now)
    lal = next(r for r in out["bets"] if r["side"] == "LAL")
    assert len([r for r in out["bets"] if r["side"] == "LAL"]) == 1 and len(lal["fills"]) == 2
    assert lal["count"] == 39.98 and lal["cost"] == 19.09 and lal["result"] == "W"
    assert lal["rules"]["counted"] and lal["rules"]["to_win"] == 20.0
    was = next(r for r in out["bets"] if r["side"] == "WAS")
    assert not was["rules"]["counted"] and "other side by 0.7" in was["rules"]["why"]
    assert (out["rules_now"]["w"], out["rules_now"]["l"]) == (1, 0)



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
