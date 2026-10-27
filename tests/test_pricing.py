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
    from engine.pricing import PRICE_WIN          # the win rate a system is priced at lives here now
    PRICE_WIN[112], old = 0.51, PRICE_WIN[112]
    try:
        card = build_card([pk(112, "BOS")], [], now=NOW)
        assert card[0]["verdict"] == "PASS"
    finally:
        PRICE_WIN[112] = old


def test_systems_are_priced_at_recent_records_not_30_year_cards():
    from engine.pricing import PRICE_WIN, win_estimate
    assert PRICE_WIN[2] < 0.60 < 0.6593                      # S2's 30-year 65.9% no longer sets the price
    assert PRICE_WIN[122] < 110 / 210                        # T22 held up worst on unseen seasons: below break-even
    assert win_estimate({"system": 2, "line": -3.0, "bet": "spread", "game_id": "g"}, []) == PRICE_WIN[2]


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
    c = build_card([pk(102, "H", shop, line=-1.5)], slate, now=NOW)[0]       # T2: no line limits
    assert [q["venue"] for q in c["shop"]] == ["prophetx"]


def test_every_card_bet_wins_20_whatever_the_stress_test_level():
    # Caden 2026-10-27: confidence sizing removed; T13 needs a 4+ gap instead
    slate = [{"game_id": "g1", "home": "H", "home_spread": 1.0,
              "personnel": {"case": {"side": "MEM", "win_est": 0.529, "line": -1.0, "level": "Low"}}}]
    c = build_card([pk(113, "MEM", [xq("prophetx", "MEM", 1.0, -116)], line=-1.0)], slate, now=NOW)[0]
    assert c["verdict"] == "BET" and c["to_win"] == 20 and "confidence" not in c
    slate[0]["personnel"]["case"]["level"] = "Medium"
    c = build_card([pk(113, "MEM", [xq("prophetx", "MEM", 1.0, -116)], line=-1.0)], slate, now=NOW)[0]
    assert c["verdict"] == "BET" and c["to_win"] == 20
    assert feed_rows([c], NOW)[0]["to_win"] == 20
    m = feed_rows([c], NOW)[0]["model"]
    assert m["win0"] == 0.529 and m["base"] == -1.0 and m["side"] == "MEM" and m["sd"] == 14.14


def test_card_shows_how_much_the_players_model_agrees():
    slate = [{"game_id": "g1", "home": "H", "home_spread": -3.0, "personnel": {"gap": -5.6}}]   # likes the away side
    c = build_card([pk(1, "A", [kq("A", 3.0, 0.45)], line=3.0)], slate, now=NOW)[0]
    assert c["players"] == 5.6 and c["players_bucket"] == "agrees by 5+"
    from engine.pricing import players_history
    h = players_history("OG", 5.6)
    assert h is None or (h["label"] == "agrees by 3+" and h["w"] + h["l"] > 0)
    c = build_card([pk(1, "H", [kq("H", -3.0, 0.45)], line=-3.0)], slate, now=NOW)[0]
    assert c["players"] == -5.6 and c["players_bucket"] == "players model disagrees"


def test_early_system_makes_the_card_only_with_players_model_3_plus():
    slate = [{"game_id": "g1", "home": "H", "home_spread": 4.0, "personnel": {"gap": 3.6}},     # likes H by 3.6
             {"game_id": "g2", "home": "H", "home_spread": 4.0, "personnel": {"gap": 1.2}}]
    live = [pk(202, "H", [kq("H", 4.0, 0.47)], line=4.0),
            pk(202, "H", [kq("H", 4.0, 0.47)], game="g2", line=4.0)]
    card = build_card(live, slate, now=NOW)
    assert [c["game_id"] for c in card] == ["g1"]
    c = card[0]
    assert c["group"] == "EARLY" and c["win"] == 0.559 and c["verdict"] == "BET" and "players model agrees by 3.6" in c["name"]
    assert (c["history"]["w"], c["history"]["l"]) == (26, 10)                # the whole combo
    assert (c["history"]["part"]["tag"], c["history"]["part"]["w"], c["history"]["part"]["l"]) == ("E2", 6, 4)
    # an OG/FAV bet on the same side already covers it: no duplicate row
    card = build_card(live + [pk(112, "H", [kq("H", 4.0, 0.47)], line=4.0)], slate, now=NOW)
    assert [c["tag"] for c in card if c["game_id"] == "g1"] == ["T12"]
    assert card[0]["also_combo"]["w"] == 26 and card[0]["also_combo"]["tag"] == "E2"


def test_shopping_never_leaves_what_the_system_allows():
    # E2 = home underdog of 7 or less: +7.5 at a better price is NOT this system's bet
    slate = [{"game_id": "g1", "home": "H", "home_spread": 6.5, "personnel": {"gap": 4.0}}]
    shop = [kq("H", 6.5, 0.50), kq("H", 7.5, 0.47), kq("H", 5.5, 0.45)]
    c = build_card([pk(202, "H", shop, line=6.5)], slate, now=NOW)[0]
    assert {q["line"] for q in c["shop"]} == {6.5, 5.5}
    # T13: edge must stay 3+ at the number taken — gap 4.0 at +3.5 allows down to +2.5, not +1.5
    slate = [{"game_id": "g1", "home": "H", "home_spread": 3.5,
              "personnel": {"case": {"side": "H", "win_est": 0.56, "line": 3.5, "cushion": 4.0, "level": "High"}}}]
    shop = [kq("H", 3.5, 0.50), kq("H", 2.5, 0.45), kq("H", 1.5, 0.38)]
    c = build_card([pk(113, "H", shop, line=3.5)], slate, now=NOW)[0]
    assert {q["line"] for q in c["shop"]} == {3.5, 2.5}


def test_points_are_priced_from_the_measured_six_season_table():
    from engine.pricing import outcome, point_gain
    # near a 3-4 point line, 2 points are worth 7.4% (a bell curve said 5.6%)
    assert round(point_gain(3.5, 2), 3) == 0.074 and round(point_gain(3.5, -2), 3) == -0.074
    # lines within 3 match the bell curve (~2.8% a point)
    assert round(point_gain(1.5, 1), 3) == 0.028
    win, push = outcome(0.56, 3.5, "spread", "NOP", 1.5)
    assert round(win, 3) == 0.486 and push == 0
    win, push = outcome(0.56, 3.5, "spread", "NOP", 4)           # whole number: push = the value of that point
    assert round(win, 3) == 0.56 and round(push, 3) == 0.039
    # totals keep the bell curve
    w2, _ = outcome(0.55, 220.5, "total", "OVER", 218.5)
    assert 0.59 < w2 < 0.61


def test_near_ties_go_to_the_number_that_wins_more_often():
    from engine.pricing import prefer_points
    plus15 = {"contract": "NOP +1.5", "ev": 0.114, "win": 0.486, "push": 0}
    plus35 = {"contract": "NOP +3.5", "ev": 0.109, "win": 0.56, "push": 0}
    plus4_bad = {"contract": "NOP +4", "ev": 0.076, "win": 0.56, "push": 0.039}
    assert [q["contract"] for q in prefer_points([plus15, plus4_bad, plus35])] == ["NOP +3.5", "NOP +1.5", "NOP +4"]
    # a clearly better price (more than 2 points of expected return) still wins
    big = {**plus15, "ev": 0.14}
    assert prefer_points([plus35, big])[0]["contract"] == "NOP +1.5"


def test_players_gap_uses_the_version_that_holds_either_way():
    from engine.pricing import players_gap
    slate = [{"game_id": "g", "home": "CHA", "personnel": {"gap": 4.1, "scenarios": [
        {"gap": 4.1}, {"gap": 1.6}]}}]
    assert players_gap({"bet": "spread", "game_id": "g", "side": "CHA"}, slate) == 1.6
    assert players_gap({"bet": "spread", "game_id": "g", "side": "MIA"}, slate) == -4.1
    slate[0]["personnel"]["scenarios"] = []
    assert players_gap({"bet": "spread", "game_id": "g", "side": "CHA"}, slate) == 4.1


def test_card_bet_means_the_placer_will_bet_it():
    # +1% expected return: above zero but under the placer's 2% bar → LIMIT (rests at a 2% price), not BET
    from engine.pricing import MIN_EV
    slate = [{"game_id": "g2", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    for price, want in ((0.53, "LIMIT"), (0.50, "BET")):
        c = build_card([pk(113, "NOP", [kq("NOP", 3.5, price)], game="g2", line=3.5)], slate, now=NOW)[0]
        assert c["verdict"] == want, (price, c["best"]["ev"], c["verdict"])
        assert (c["best"]["ev"] >= MIN_EV) == (want == "BET")


def test_both_sides_of_a_game_are_never_bet():
    slate = [{"game_id": "g1", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    live = [pk(112, "BOS", game="g1"), pk(102, "NYK", game="g1"), pk(112, "LAL", game="g9")]
    for p in live[:2]:
        p["away"], p["home"] = "NYK", "BOS"
    card = build_card(live, slate, now=NOW)
    v = {c["side"]: c["verdict"] for c in card}
    assert v["BOS"] == "CONFLICT" and v["NYK"] == "CONFLICT" and v["LAL"] == "BET"
    assert "other side of this game" in next(c for c in card if c["side"] == "BOS")["why"]


def test_moneyball_replaces_the_other_bets_on_its_side_and_wins_30():
    slate = [{"game_id": "g1", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    live = [pk(130, "BOS", game="g1"), pk(112, "BOS", game="g1"), pk(102, "BOS", game="g1")]
    card = build_card(live, slate, now=NOW)
    assert [c["tag"] for c in card] == ["MONEYBALL"] and card[0]["to_win"] == 30
    assert set(card[0]["with"]) == {"T12", "T2"}


def test_never_bets_a_price_worse_than_minus_150_or_far_from_the_number():
    from engine.pricing import PRICE_WIN
    PRICE_WIN[102], old = 0.70, PRICE_WIN[102]           # huge edge on paper: the guards must still hold
    try:
        pricey = build_card([pk(102, "BOS", [xq("prophetx", "BOS", -3.0, -160)])], [], now=NOW)[0]
        assert pricey["verdict"] != "BET" and pricey["best"]["too_pricey"]
        far = build_card([pk(102, "BOS", [xq("prophetx", "BOS", 0.5, -110)])], [], now=NOW)[0]   # 3.5 pts bought
        assert not far["shop"] or all(abs(q["line"] - -3.0) <= 2.0 for q in far["shop"])
        fine = build_card([pk(102, "BOS", [xq("prophetx", "BOS", -2.0, -140)])], [], now=NOW)[0]
        assert fine["verdict"] == "BET" and fine["best"]["line"] == -2.0
    finally:
        PRICE_WIN[102] = old
