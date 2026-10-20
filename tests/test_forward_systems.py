"""Rule tests for the 12 forward-test systems (T1-T12)."""
from datetime import date, timedelta

from engine.state import Game, team_state
from engine.systems import evaluate_tests, grade, Pick

D = date(2026, 1, 20)


def g(i, day, away, home, a, h, periods=4):
    return Game(id=f"t{i}", game_date=day, away=away, home=home,
                away_score=a, home_score=h, periods=periods, final=True)


def run(hist, away, home, home_spread=None, total=None, day=D):
    game = Game(id="today", game_date=day, away=away, home=home)
    return evaluate_tests(game, team_state(home, hist, day), team_state(away, hist, day), home_spread, total)


def fired(picks, sid):
    return [(p.side, p.line) for p in picks if p.system == sid]


def test_t1_double_ot_win_or_loss():
    for a, h in ((130, 128), (128, 130)):                    # NYK lost, then won, in 2OT
        hist = [g(1, D - timedelta(1), "BOS", "NYK", a, h, periods=6)]
        assert fired(run(hist, "NYK", "MIA"), 101) == [("MIA", None)]
    hist = [g(1, D - timedelta(1), "BOS", "NYK", 110, 112, periods=5)]   # single OT: no
    assert fired(run(hist, "NYK", "MIA"), 101) == []


def test_t2_third_in_four_vs_rested():
    hist = [g(1, D - timedelta(3), "NYK", "BOS", 100, 90), g(2, D - timedelta(1), "NYK", "PHI", 100, 90),
            g(3, D - timedelta(3), "MIA", "ATL", 100, 90)]
    assert fired(run(hist, "NYK", "MIA", -2.0), 102) == [("MIA", -2.0)]
    hist[2] = g(3, D - timedelta(2), "MIA", "ATL", 100, 90)     # MIA only 1 day off → no
    assert fired(run(hist, "NYK", "MIA", -2.0), 102) == []


def test_t3_altitude_b2b():
    hist = [g(1, D - timedelta(1), "LAL", "PHX", 100, 90)]
    assert fired(run(hist, "LAL", "DEN", -6.5), 103) == [("DEN", -6.5)]
    assert fired(run(hist, "LAL", "DAL", -6.5), 103) == []


def test_t4_cross_country_b2b():
    hist = [g(1, D - timedelta(1), "BOS", "LAL", 100, 90)]       # BOS played in LA last night
    assert fired(run(hist, "BOS", "NYK", -3.0), 104) == [("NYK", -3.0)]
    hist = [g(1, D - timedelta(1), "BOS", "PHI", 100, 90)]       # short hop → no
    assert fired(run(hist, "BOS", "NYK", -3.0), 104) == []


def test_t5_both_b2b_under():
    hist = [g(1, D - timedelta(1), "BOS", "PHI", 100, 90), g(2, D - timedelta(1), "NYK", "MIA", 100, 90)]
    assert fired(run(hist, "BOS", "NYK", -3.0, 221.5), 105) == [("UNDER", 221.5)]
    hist[1] = g(2, D - timedelta(2), "NYK", "MIA", 100, 90)
    assert fired(run(hist, "BOS", "NYK", -3.0, 221.5), 105) == []


def test_t6_and_t7_blowouts():
    hist = [g(1, D - timedelta(2), "BOS", "PHI", 140, 110)]      # BOS won by 30, PHI lost by 30
    p = run(hist, "BOS", "PHI", home_spread=+4.0)                 # BOS favored by 4 on the road
    assert fired(p, 106) == [("PHI", 4.0)]
    assert fired(p, 107) == [("PHI", 4.0)]
    p = run(hist, "BOS", "PHI", home_spread=-1.0)                 # BOS an underdog → no T7
    assert fired(p, 107) == []
    hist = [g(1, D - timedelta(2), "BOS", "PHI", 124, 100)]      # 24-point loss → no T6
    assert fired(run(hist, "BOS", "PHI", +4.0), 106) == []


def test_t8_home_fav_losing_streak():
    hist = [g(i, D - timedelta(2 * i), "PHI", "ATL", 110, 100) for i in range(1, 4)]   # PHI lost 3 at home
    assert fired(run(hist, "MIA", "ATL", -2.5), 108) == [("ATL", -2.5)]
    assert fired(run(hist, "MIA", "ATL", +2.5), 108) == []


def test_t9_home_dog_vs_hot_team():
    hist = [g(i, D - timedelta(2 * i), "OKC", "UTA", 120, 100) for i in range(1, 6)]   # OKC won 5
    assert fired(run(hist, "OKC", "SAS", +7.5), 109) == [("SAS", 7.5)]
    assert fired(run(hist[:4], "OKC", "SAS", +7.5), 109) == []


def test_t10_two_game_set():
    hist = [g(1, D - timedelta(2), "MIA", "NYK", 100, 112)]       # MIA lost at NYK two days ago
    assert fired(run(hist, "MIA", "NYK", -4.0), 110) == [("MIA", 4.0)]
    assert fired(run(hist, "NYK", "MIA", -4.0), 110) == []         # different building → no


def test_t11_and_t12_mismatch():
    hist = [g(1, D - timedelta(1), "WAS", "PHI", 90, 100), g(2, D - timedelta(2), "BOS", "ATL", 100, 90)]
    p = run(hist, "WAS", "BOS", home_spread=-10.5, total=226.0)
    assert fired(p, 111) == [("OVER", 226.0)]
    assert fired(p, 112) == [("BOS", -10.5)]
    p = run(hist, "WAS", "BOS", home_spread=-7.5, total=224.5)
    assert fired(p, 111) == [] and fired(p, 112) == []


def test_under_grading():
    final = Game("x", D, "BOS", "NYK", away_score=105, home_score=110, final=True)   # 215
    assert grade(Pick(105, "x", "total", "UNDER", 220.5), final) == "W"
    assert grade(Pick(105, "x", "total", "UNDER", 214.5), final) == "L"
    assert grade(Pick(105, "x", "total", "UNDER", 215.0), final) == "P"
