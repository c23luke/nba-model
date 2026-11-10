"""The injury desk: tracking only. It records our read and the market each run, and judges each report change."""
from datetime import datetime, timedelta, timezone

from engine import injury_desk as D
from engine.store import LocalStore

T0 = datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)


def slate_game(mkt, fair, scen=None, dtd=None):
    return {"game_id": "g1", "home_spread": mkt,
            "personnel": {"fair": fair, "scenarios": [{"fair": f} for f in (scen or [fair])], "waiting_on": dtd or []}}


def test_reads_are_saved_only_when_something_changes(tmp_path):
    st = LocalStore(tmp_path)
    assert D.record_reads(st, [slate_game(-8.5, -9.0, [-9.0, -4.0], ["DEN: Nikola Jokic"])], T0) == 1
    assert D.record_reads(st, [slate_game(-8.5, -9.0, [-9.0, -4.0], ["DEN: Nikola Jokic"])], T0 + timedelta(minutes=5)) == 0
    assert D.record_reads(st, [slate_game(-8.5, -13.5)], T0 + timedelta(minutes=16)) == 1
    h = st.load_state(["read:g1"])["read:g1"]["h"]
    assert [(e["mkt"], e["fair"], e["lo"], e["hi"], e["dtd"]) for e in h] == [
        (-8.5, -9.0, -9.0, -4.0, ["DEN: Nikola Jokic"]), (-8.5, -13.5, -13.5, -13.5, [])]
    assert D.record_reads(st, [{"game_id": "g2", "home_spread": None, "personnel": {"fair": -3}}], T0) == 0


def test_report_rows_become_events_of_real_changes():
    rows = [{"team": "DEN", "game_date": "2026-11-09", "player": "Nikola Jokic", "player_key": "jokic", "status": "Questionable",
             "first_seen": "2026-11-08T22:30:31+00:00"},
            {"team": "DEN", "game_date": "2026-11-09", "player": "Jamal Murray", "player_key": "murray", "status": "Questionable",
             "first_seen": "2026-11-08T22:30:31+00:00"},
            {"team": "DEN", "game_date": "2026-11-09", "player": "Nikola Jokic", "player_key": "jokic", "status": "Probable",
             "first_seen": "2026-11-09T19:15:33+00:00"},
            {"team": "DEN", "game_date": "2026-11-09", "player": "Jamal Murray", "player_key": "murray", "status": "Probable",
             "first_seen": "2026-11-09T19:16:10+00:00"}]
    ev = D.events_from_log(rows)
    assert [(e["at"][:16], len(e["changes"])) for e in ev] == [("2026-11-08T22:30", 2), ("2026-11-09T19:15", 2)]
    assert ev[1]["changes"][0] == "Nikola Jokic: Questionable → Probable"


def test_news_that_moves_our_number_is_judged_against_the_market():
    # Nov 9, DEN at HOU: Denver's starters cleared at 19:15. Before: worst case had them sitting (HOU by 13).
    # After our read (19:16) we have HOU by only 1.5 against a market of HOU -8.5: a paper bet on DEN +8.5.
    # The market went to -4.5 within 15 minutes and closed -5: our number beat the close by 3.5. HOU won by 10, so DEN +8.5 lost.
    t = lambda m: (T0 + timedelta(minutes=m)).isoformat()
    h = [{"ts": t(-60), "mkt": -8.5, "fair": -6.0, "lo": -13.0, "hi": -1.5, "dtd": ["DEN: Nikola Jokic"], "blind": False},
         {"ts": t(16), "mkt": -8.5, "fair": -1.5, "lo": -1.5, "hi": -1.5, "dtd": [], "blind": False},
         {"ts": t(27), "mkt": -4.5, "fair": -1.5, "lo": -1.5, "hi": -1.5, "dtd": [], "blind": False},
         {"ts": t(360), "mkt": -5.0, "fair": -1.5, "lo": -1.5, "hi": -1.5, "dtd": [], "blind": False}]
    game = {"id": "g1", "away": "DEN", "home": "HOU", "tip_utc": t(390), "final": True, "home_score": 110, "away_score": 100}
    ev = {"team": "DEN", "game_date": "2026-11-09", "at": t(15), "changes": ["Nikola Jokic: Questionable → Probable"]}
    j = D.judge(ev, game, h)
    assert j["our_move"] == 4.5 and j["mkt_at"] == -8.5 and j["mkt_15"] == -4.5 and j["mkt_close"] == -5.0
    assert j["seconds_to_read"] == 60
    assert j["market_followed"] == 3.5                     # the market moved 3.5 the way our number did
    assert j["paper"] == {"side": "DEN", "line": 8.5, "gap": 7.0, "clv": 3.5, "result": "L"}


def test_small_moves_and_no_read_are_not_events():
    t = lambda m: (T0 + timedelta(minutes=m)).isoformat()
    h = [{"ts": t(-60), "mkt": -3.0, "fair": -4.0, "lo": -4.0, "hi": -4.0, "dtd": [], "blind": False},
         {"ts": t(16), "mkt": -3.0, "fair": -4.5, "lo": -4.5, "hi": -4.5, "dtd": [], "blind": False}]
    game = {"id": "g1", "away": "A", "home": "H", "tip_utc": t(400)}
    assert D.judge({"team": "A", "at": t(15), "changes": []}, game, h) is None        # half a point: not news
    assert D.judge({"team": "A", "at": t(15), "changes": []}, game, h[:1]) is None    # no read after it
