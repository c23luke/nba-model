from engine import watch as W
from engine.store import LocalStore


def test_max_price_respects_fee():
    cap = W.max_price(0.57)
    assert cap is not None and cap + W.kalshi_fee(cap) <= 0.57
    assert (cap + 0.01) + W.kalshi_fee(cap + 0.01) > 0.57


def test_alerts_once_and_only_alert_groups(tmp_path):
    store = LocalStore(tmp_path)
    pick = {"key": "g1-S113-NOP", "system": 113, "game_id": "g1", "bet": "spread", "side": "NOP", "line": 3.5,
            "label": "NOP +3.5", "away": "IND", "home": "NOP", "tag": "T13", "group": "FAV", "evidence": ["x"],
            "meta": {}, "kalshi": {"contract": "YES · NOP wins", "price": 0.48, "url": "https://kalshi.com/x"},
            "tip_utc": "2099-01-01T00:00Z",
            "shop": [{"venue": "kalshi", "venue_name": "Kalshi", "bet": "spread", "side": "NOP", "line": 3.5,
                      "ml": False, "price": 0.48, "fee": 0.02, "cost": 0.50, "fee_counted": True, "size": None,
                      "contract": "NO · IND wins by over 3.5", "url": "https://kalshi.com/x", "ticker": "T"}]}
    test_pick = {**pick, "key": "g1-S106-NOP", "system": 106, "tag": "T6", "group": "TEST"}
    store.save_picks([pick, test_pick])
    board = {"bets": [], "tests": [pick, test_pick], "systems": {},
             "slate": [{"game_id": "g1", "personnel": {"case": {"side": "NOP", "win_est": 0.6}}}]}
    sent = []
    W.push = lambda *a: sent.append(a)
    assert W.alert_new(board, store, "topic", print) == 1
    assert "Max price" in sent[0][2] and sent[0][1].startswith("BET") and sent[0][3] == "https://kalshi.com/x"
    saved = {p["key"]: p for p in store.load_picks()}
    assert saved["g1-S113-NOP"]["meta"]["alerted"]
    board["tests"] = [saved["g1-S113-NOP"] | {"tag": "T13", "group": "FAV"}, test_pick]
    assert W.alert_new(board, store, "topic", print) == 0


def test_limit_alerts_then_alerts_again_when_it_becomes_a_bet(tmp_path):
    store = LocalStore(tmp_path)
    q = {"venue": "kalshi", "venue_name": "Kalshi", "bet": "spread", "side": "NOP", "line": 3.5, "ml": False,
         "price": 0.60, "fee": 0.02, "cost": 0.62, "fee_counted": True, "size": None,
         "contract": "NO · IND wins by over 3.5", "url": "https://kalshi.com/x", "ticker": "T"}
    pick = {"key": "g1-S113-NOP", "system": 113, "game_id": "g1", "bet": "spread", "side": "NOP", "line": 3.5,
            "label": "NOP +3.5", "away": "IND", "home": "NOP", "tag": "T13", "group": "FAV", "evidence": [],
            "meta": {}, "kalshi": None, "tip_utc": "2099-01-01T00:00Z", "shop": [q]}
    slate = [{"game_id": "g1", "personnel": {"case": {"side": "NOP", "win_est": 0.56}}}]
    sent = []
    W.push = lambda *a: sent.append(a)
    assert W.alert_new({"tests": [pick], "slate": slate}, store, "t", print) == 1 and sent[0][1].startswith("LIMIT")
    saved = store.load_picks()[0] | {"tag": "T13", "group": "FAV", "shop": [q]}
    assert W.alert_new({"tests": [saved], "slate": slate}, store, "t", print) == 0      # still LIMIT: quiet
    cheap = saved | {"shop": [q | {"price": 0.48, "cost": 0.50}]}
    assert W.alert_new({"tests": [cheap], "slate": slate}, store, "t", print) == 1 and sent[-1][1].startswith("BET")
