from engine.pricing import build_card, max_price, kalshi_fee


def pk(system, side, price=None, game="g1", line=-3.0, bet="spread"):
    return {"key": f"{game}-S{system}-{side}", "system": system, "game_id": game, "bet": bet, "side": side,
            "line": line, "label": f"{side} {line}", "away": "A", "home": "H", "tip_utc": "2026-10-22T00:00Z",
            "kalshi": None if price is None else {"price": price, "contract": "x", "url": "u"}}


def test_card_ranks_bets_first_and_prices_them():
    slate = [{"game_id": "g2", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    live = [pk(4, "OVER", price=0.50, bet="total", line=231.0),        # OG S4, card 57.4%
            pk(113, "NOP", price=0.60, game="g2", line=3.5),           # T13 56%: too pricey → LIMIT
            pk(112, "BOS", price=None),                                 # T12 52.5% no Kalshi → BET at a book
            pk(106, "BOS", price=0.40)]                                 # TEST: not on the card
    card = build_card(live, slate)
    assert [c["tag"] for c in card] == ["S4", "T12", "T13"]
    assert card[0]["verdict"] == "BET" and card[2]["verdict"] == "LIMIT"
    assert card[2]["max"] == max_price(0.56) and card[2]["max"] + kalshi_fee(card[2]["max"]) <= 0.56


def test_pass_when_no_edge_and_no_market():
    from engine.systems import TEST_SYSTEMS
    TEST_SYSTEMS[112]["win_est"], old = 0.51, TEST_SYSTEMS[112]["win_est"]
    try:
        card = build_card([pk(112, "BOS", price=None)], [])
        assert card[0]["verdict"] == "PASS"
    finally:
        TEST_SYSTEMS[112]["win_est"] = old
