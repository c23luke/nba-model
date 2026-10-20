from datetime import date
from engine.state import Game, TeamState
from engine.systems import evaluate_mined


def st(team, last=None):
    s = TeamState(team)
    if last:
        s.last_game = last
        s.wins = 1
    return s


def test_late_season_mismatch_and_low_total_overs():
    g = Game("x", date(2027, 4, 1), "WAS", "BOS")
    picks = evaluate_mined(g, st("BOS"), st("WAS"), -12.5, 214.5,
                           {"last21": True, "post_asb": True, "tot_low_cut": 218.0})
    assert {(p.system, p.side) for p in picks} == {(121, "OVER"), (122, "OVER")}
    assert evaluate_mined(g, st("BOS"), st("WAS"), -6.5, 230.0, {"last21": True, "tot_low_cut": 218.0}) == []


def test_post_all_star_tired_home_mismatch_over():
    g = Game("x", date(2027, 3, 1), "WAS", "BOS")
    p = evaluate_mined(g, st("BOS"), st("WAS"), -11.0, 228.0, {"post_asb": True, "home_4in6": True})
    assert [(x.system, x.side) for x in p] == [(123, "OVER")]


def test_fade_ot_winner_on_4_in_6():
    last = Game("y", date(2027, 1, 9), "MIA", "BOS", 120, 121, 5, True)     # BOS won in OT
    g = Game("x", date(2027, 1, 10), "BOS", "NYK")
    picks = evaluate_mined(g, st("NYK"), st("BOS", last), -3.0, 225.0, {"away_4in6": True})
    assert [(p.system, p.side, p.line) for p in picks] == [(124, "NYK", -3.0)]
