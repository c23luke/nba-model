from datetime import datetime, timezone

from engine.pricing import build_card, max_price, kalshi_fee, outcome, feed_rows, expected_return

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def kq(side, line, price, bet="spread"):
    return {"venue": "kalshi", "venue_name": "Kalshi", "bet": bet, "side": side, "line": line, "ml": False,
            "price": price, "fee": kalshi_fee(price), "cost": round(price + kalshi_fee(price), 4),
            "fee_counted": True, "size": None, "contract": f"k {side} {line}", "url": "u", "ticker": "T"}


def xq(venue, side, line, american, bet="spread", size=500):
    cost = 100 / (american + 100) if american > 0 else -american / (-american + 100)
    return {"venue": venue, "venue_name": venue, "bet": bet, "side": side, "line": line, "ml": False,
            "american": american, "cost": round(cost, 4), "fee_counted": False, "size": size,
            "contract": f"{side} {line}", "url": None, "ticker": None}


def pk(system, side, shop=(), game="g1", line=-3.0, bet="spread", tip="2026-10-22T00:00Z"):
    return {"key": f"{game}-S{system}-{side}", "system": system, "game_id": game, "bet": bet, "side": side,
            "line": line, "label": f"{side} {line}", "away": "A", "home": "H", "tip_utc": tip,
            "game_date": "2026-10-21", "kalshi": None, "shop": list(shop)}


def test_card_ranks_bets_first_and_prices_them():
    slate = [{"game_id": "g2", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    live = [pk(4, "OVER", [kq("OVER", 231.5, 0.50, "total")], bet="total", line=231.5),   # OG S4 ~57%: value
            pk(113, "NOP", [kq("NOP", 3.5, 0.60)], game="g2", line=3.5),                  # T13 56% at 60c → LIMIT
            pk(112, "BOS"),                                                               # T12, no market → BET at a book
            pk(106, "BOS", [kq("BOS", -3.0, 0.40)])]                                      # TEST: not on the card
    card = build_card(live, slate, now=NOW)
    assert [c["tag"] for c in card] == ["S4", "T12", "T13"]
    assert card[0]["verdict"] == "BET" and card[1]["verdict"] == "BET" and card[2]["verdict"] == "LIMIT"
    assert card[2]["max"] == max_price(0.56) and card[2]["max"] + kalshi_fee(card[2]["max"]) <= 0.56


def test_line_shopping_takes_the_better_number_at_a_venue_he_uses():
    slate = [{"game_id": "g1", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    shop = [kq("NOP", 3.5, 0.52),                    # his line, 54c with fee
            xq("prophetx", "NOP", 4.5, -105),        # a point better at about the same price
            xq("novig", "NOP", 5.5, -102),           # better still, but no account there
            xq("polymarket_us", "NOP", 4.5, -105, size=3),     # too little available
            xq("betopenly", "IND", -3.5, +100)]      # the other side: ignored
    c = build_card([pk(113, "NOP", shop, line=3.5)], slate, now=NOW)[0]
    assert c["verdict"] == "BET"
    assert c["best"]["venue"] == "prophetx" and c["best"]["line"] == 4.5
    venues = [q["venue"] for q in c["shop"]]
    assert "novig" in venues and "polymarket_us" not in venues and "betopenly" not in venues
    assert c["shop"][0]["venue"] == "novig" and not c["shop"][0]["mine"]
    assert c["contract"] == "k NOP 3.5"          # where the limit order would go


def test_outcome_moves_the_right_way_and_counts_pushes():
    assert abs(outcome(0.56, 3.5, "spread", "NOP", 3.5)[0] - 0.56) < 1e-9
    assert outcome(0.56, 3.5, "spread", "NOP", 4.5)[0] > 0.56 > outcome(0.56, 3.5, "spread", "NOP", 2.5)[0]
    assert outcome(0.57, 231.5, "total", "OVER", 230.5)[0] > 0.57 > outcome(0.57, 231.5, "total", "OVER", 232.5)[0]
    assert outcome(0.55, 220.5, "total", "UNDER", 221.5)[0] > 0.55
    w, push = outcome(0.56, 3.5, "spread", "NOP", 4.0)
    # +4 wins exactly when +3.5 wins, and wins-or-pushes exactly when +4.5 wins
    assert push > 0.01 and abs(w - 0.56) < 1e-9 and abs(w + push - outcome(0.56, 3.5, "spread", "NOP", 4.5)[0]) < 1e-9
    w, push = outcome(0.57, 231.5, "total", "OVER", 231.0)      # over 231: wins when over 231.5 wins
    assert abs(w - 0.57) < 1e-9 and push > 0.01
    assert abs(expected_return(0.5, 0.0, 0.5)) < 1e-12


def test_tipped_games_leave_the_card():
    live = [pk(112, "BOS", tip="2026-10-21T11:00Z"), pk(112, "NYK", game="g9", tip="2026-10-21T23:00Z")]
    assert [c["side"] for c in build_card(live, [], now=NOW)] == ["NYK"]


def test_pass_when_no_edge_and_no_market():
    from engine.systems import TEST_SYSTEMS
    TEST_SYSTEMS[112]["win_est"], old = 0.51, TEST_SYSTEMS[112]["win_est"]
    try:
        card = build_card([pk(112, "BOS")], [], now=NOW)
        assert card[0]["verdict"] == "PASS"
    finally:
        TEST_SYSTEMS[112]["win_est"] = old


def test_feed_rows_carry_what_a_scanner_needs():
    slate = [{"game_id": "g1", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    card = build_card([pk(113, "NOP", [kq("NOP", 3.5, 0.49)], line=3.5)], slate, now=NOW)
    row = feed_rows(card, NOW)[0]
    assert row["status"] == "bet" and row["best_venue"] == "kalshi" and row["best_ticker"] == "T"
    assert row["best_price"] == 0.49 and row["max_price"] == max_price(0.56)
    assert row["quotes"][0]["venue"] == "kalshi" and row["quotes"][0]["ticker"] == "T"
    assert {"order_side", "side", "ml", "price_txt"} <= set(row["quotes"][0])


def test_exchange_feed_parsing_and_kalshi_ladder():
    from engine import sources
    from engine.state import Game
    from datetime import date
    ev = [{"home_team": "Detroit Pistons", "away_team": "Boston Celtics", "commence_time": "2026-10-20T19:10:00Z",
           "bookmakers": [
               {"key": "kalshi", "markets": [{"key": "h2h", "outcomes": [{"name": "Detroit Pistons", "price": 113}]}]},
               {"key": "prophetx", "markets": [
                   {"key": "spreads", "outcomes": [{"name": "Detroit Pistons", "point": 1.0, "price": 106, "bet_limit": 6506}]},
                   {"key": "h2h", "outcomes": [{"name": "Detroit Pistons", "price": 112}]},
                   {"key": "totals", "outcomes": [{"name": "Under", "point": 220.0, "price": 106}]}]}]}]
    qs = sources.parse_exchange_events(ev)[(date(2026, 10, 20), "BOS", "DET")]
    assert {q["venue"] for q in qs} == {"prophetx"}               # Kalshi comes from Kalshi directly
    sp = next(q for q in qs if q["bet"] == "spread" and not q["ml"])
    assert sp["side"] == "DET" and sp["line"] == 1.0 and abs(sp["cost"] - 100 / 206) < 1e-4 and sp["size"] == 6506
    assert next(q for q in qs if q["ml"])["line"] == -0.5
    assert next(q for q in qs if q["bet"] == "total")["side"] == "UNDER"

    g = Game(id="1", game_date=date(2026, 10, 20), away="BOS", home="DET")
    mk = {"KXNBAGAME": [{"ticker": "KXNBAGAME-26OCT20BOSDET-DET", "yes_ask_dollars": "0.47"}],
          "KXNBASPREAD": [{"ticker": "KXNBASPREAD-26OCT20BOSDET-BOS2", "floor_strike": 1.5, "no_ask_dollars": "0.50"},
                          {"ticker": "KXNBASPREAD-26OCT20BOSDET-BOS4", "floor_strike": 3.5, "no_ask_dollars": "0.60"},
                          {"ticker": "KXNBASPREAD-26OCT20BOSDET-DET2", "floor_strike": 1.5, "yes_ask_dollars": "0.40"}]}
    from engine.systems import Pick
    lad = sources.kalshi_ladder(Pick(113, "1", "spread", "DET", 1.5), g, fetch=lambda s, _g: mk.get(s, []))
    got = sorted((q["line"], q["price"]) for q in lad)
    assert got == [(-1.5, 0.40), (-0.5, 0.47), (1.5, 0.50), (3.5, 0.60)]
    assert all(q["cost"] == round(q["price"] + kalshi_fee(q["price"]), 4) for q in lad)
    sides = {(q["line"], q["order_side"]) for q in lad}
    assert sides == {(-1.5, "yes"), (-0.5, "yes"), (1.5, "no"), (3.5, "no")}


def test_locked_bet_is_shopped_from_where_the_market_is_now():
    # T13 locked MEM -1; the market has since gone to MEM +1.5 and the case (rebuilt at +1.5) still says 52.9%
    slate = [{"game_id": "g1", "home": "MEM", "home_spread": 1.5,
              "personnel": {"case": {"side": "MEM", "win_est": 0.529, "line": 1.5}}}]
    shop = [xq("polymarket", "MEM", 1.5, -122)]
    c = build_card([pk(113, "MEM", shop, line=-1.0)], slate, now=NOW)[0]
    assert c["best"]["win"] == 0.529 and c["best"]["ev"] < 0       # no 2.5-point head start from the old number


def test_quote_far_off_the_market_is_treated_as_bad_data():
    slate = [{"game_id": "g1", "home": "H", "home_spread": -1.5}]   # H -1.5 consensus
    shop = [xq("polymarket", "H", 1.5, +113),     # H +1.5 priced like H -1.5 (teams swapped in the feed)
            xq("prophetx", "H", -1.5, +104)]
    c = build_card([pk(112, "H", shop, line=-1.5)], slate, now=NOW)[0]
    assert [q["venue"] for q in c["shop"]] == ["prophetx"]
