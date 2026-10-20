"""Rule tests for the 7 early-season systems (E1-E7)."""
from datetime import date, timedelta

from engine.state import Game, team_state
from engine.systems import evaluate_early, label, group

OPEN = date(2026, 10, 20)


def g(i, day, away, home, a, h):
    return Game(id=f"t{i}", game_date=day, away=away, home=home,
                away_score=a, home_score=h, periods=4, final=True)


def run(hist, away, home, home_spread=None, total=None, day=OPEN):
    game = Game(id="today", game_date=day, away=away, home=home)
    return evaluate_early(game, team_state(home, hist, day), team_state(away, hist, day),
                          home_spread, total, (day - OPEN).days)


def fired(picks, sid):
    return [(p.side, p.line) for p in picks if p.system == sid]


def test_labels():
    assert (label(201), group(201)) == ("E1", "EARLY")
    assert (label(112), group(112)) == ("T12", "FAV")
    assert (label(3), group(3)) == ("S3", "OG")


def test_e1_opener_over_only_when_both_unplayed():
    assert fired(run([], "BOS", "DET", +1.5, 222.0), 201) == [("OVER", 222.0)]
    hist = [g(1, OPEN, "BOS", "NYK", 100, 90)]
    assert fired(run(hist, "BOS", "DET", +1.5, 222.0, OPEN + timedelta(2)), 201) == []


def test_e2_early_home_dog():
    assert fired(run([], "BOS", "DET", +1.5), 202) == [("DET", 1.5)]
    assert fired(run([], "BOS", "DET", +7.5), 202) == []                     # more than 7
    assert fired(run([], "BOS", "DET", +3.0, day=OPEN + timedelta(14)), 202) == []   # past 2 weeks


def test_e3_fade_big_favorite():
    assert fired(run([], "WAS", "OKC", -11.5), 203) == [("WAS", 11.5)]
    assert fired(run([], "WAS", "OKC", -9.5), 203) == []


def test_e4_e5_early_blowouts():
    hist = [g(1, OPEN, "BOS", "PHI", 120, 100)]                               # BOS +20, PHI -20
    p = run(hist, "BOS", "PHI", +3.0, day=OPEN + timedelta(2))               # BOS favored by 3
    assert fired(p, 204) == [("PHI", 3.0)]
    assert fired(p, 205) == [("PHI", 3.0)]
    assert fired(run(hist, "BOS", "PHI", +3.0, day=OPEN + timedelta(21)), 204) == []   # window closed


def test_e6_e7_records():
    hist = [g(i, OPEN + timedelta(2 * i), "UTA", "OKC", 90, 110) for i in range(3)]   # UTA 0-3, OKC 3-0
    p = run(hist, "UTA", "OKC", -8.0, day=OPEN + timedelta(7))
    assert fired(p, 206) == [("UTA", 8.0)]
    assert fired(p, 207) == [("UTA", 8.0)]
    p = run(hist[:2], "UTA", "OKC", -8.0, day=OPEN + timedelta(7))           # only 0-2 / 2-0
    assert fired(p, 206) == [] and fired(p, 207) == []


def test_e8_early_over_first_two_weeks_only():
    from datetime import timedelta
    assert fired(run([], "BOS", "DET", +1.5, 222.0, day=OPEN + timedelta(3)), 208) == [("OVER", 222.0)]
    assert fired(run([], "BOS", "DET", +1.5, 222.0, day=OPEN + timedelta(14)), 208) == []
