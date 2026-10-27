"""Rule-boundary tests for each system, plus checks on real 2025-26 games."""
from datetime import date, timedelta

from engine.state import Game, team_state
from engine.systems import evaluate, grade, Pick
from tests.load import fixture_games

D = date(2026, 1, 20)


def g(i, day, away, home, a, h, periods=4):
    return Game(id=f"t{i}", game_date=day, away=away, home=home,
                away_score=a, home_score=h, periods=periods, final=True)


def run(history, away, home, home_spread, total, day=D):
    game = Game(id="today", game_date=day, away=away, home=home)
    return evaluate(game, team_state(home, history, day), team_state(away, history, day),
                    home_spread, total)


def systems(picks):
    return sorted(p.system for p in picks)


# ---------------- System 1 ----------------
def test_s1_fires_on_ot_win_last_night():
    hist = [g(1, D - timedelta(1), "BOS", "NYK", 110, 112, periods=5)]   # NYK won in OT yesterday
    picks = run(hist, "NYK", "MIA", home_spread=-2.0, total=None)
    s1 = [p for p in picks if p.system == 1]
    assert len(s1) == 1 and s1[0].side == "MIA" and s1[0].line == -2.0


def test_s1_fires_before_line_is_out():
    hist = [g(1, D - timedelta(1), "BOS", "NYK", 110, 112, periods=6)]
    s1 = [p for p in run(hist, "MIA", "NYK", None, None) if p.system == 1]
    assert len(s1) == 1 and s1[0].side == "MIA" and s1[0].line is None


def test_s1_not_on_ot_loss():
    hist = [g(1, D - timedelta(1), "BOS", "NYK", 114, 112, periods=5)]   # NYK lost in OT
    assert 1 not in systems(run(hist, "NYK", "MIA", -2.0, None))


def test_s1_not_with_a_day_off():
    hist = [g(1, D - timedelta(2), "BOS", "NYK", 110, 112, periods=5)]
    assert 1 not in systems(run(hist, "NYK", "MIA", -2.0, None))


def test_s1_not_on_regulation_win():
    hist = [g(1, D - timedelta(1), "BOS", "NYK", 110, 112, periods=4)]
    assert 1 not in systems(run(hist, "NYK", "MIA", -2.0, None))


# ---------------- System 2 ----------------
def streak_hist(team, results, last_day):
    """results: list of 'W'/'L', oldest first, games every 2 days ending on last_day."""
    hist = []
    n = len(results)
    for k, r in enumerate(results):
        day = last_day - timedelta(2 * (n - 1 - k))
        opp = "UTA" if team != "UTA" else "WAS"
        hist.append(g(100 + k, day, team, opp, 110 if r == "W" else 90, 100))
    return hist


def test_s2_fires_road_fav_lost_4():
    hist = streak_hist("BOS", list("WWLLLL"), D - timedelta(2))
    s2 = [p for p in run(hist, "BOS", "CHA", home_spread=+4.5, total=None) if p.system == 2]
    assert len(s2) == 1 and s2[0].side == "BOS" and s2[0].line == -4.5


def test_s2_needs_more_than_3_losses():
    hist = streak_hist("BOS", list("WWWLLL"), D - timedelta(2))
    assert 2 not in systems(run(hist, "BOS", "CHA", +4.5, None))


def test_s2_not_on_back_to_back():
    hist = streak_hist("BOS", list("WLLLL"), D - timedelta(1))
    assert 2 not in systems(run(hist, "BOS", "CHA", +4.5, None))


def test_s2_not_if_road_team_is_dog():
    hist = streak_hist("BOS", list("LLLLL"), D - timedelta(2))
    assert 2 not in systems(run(hist, "BOS", "CHA", -1.5, None))


def test_s2_not_if_opponent_also_lost_4():
    hist = streak_hist("BOS", list("LLLL"), D - timedelta(2)) + streak_hist("CHA", list("LLLL"), D - timedelta(3))
    assert 2 not in systems(run(hist, "BOS", "CHA", +4.5, None))


def test_s2_never_fires_for_home_team():
    hist = streak_hist("CHA", list("LLLLL"), D - timedelta(2))
    assert 2 not in systems(run(hist, "BOS", "CHA", -4.5, None))


# ---------------- System 3 ----------------
def test_s3_fires():
    hist = streak_hist("CHA", list("WWWL"), D - timedelta(3)) + streak_hist("BOS", list("LWWWW"), D - timedelta(1))
    s3 = [p for p in run(hist, "BOS", "CHA", home_spread=-3.0, total=None) if p.system == 3]
    assert len(s3) == 1 and s3[0].side == "CHA" and s3[0].line == -3.0


def test_s3_needs_streak_of_4():
    hist = streak_hist("CHA", list("WWWL"), D - timedelta(3)) + streak_hist("BOS", list("LWWW"), D - timedelta(1))
    assert 3 not in systems(run(hist, "BOS", "CHA", -3.0, None))


def test_s3_needs_opponent_on_back_to_back():
    hist = streak_hist("CHA", list("WWWL"), D - timedelta(3)) + streak_hist("BOS", list("WWWW"), D - timedelta(2))
    assert 3 not in systems(run(hist, "BOS", "CHA", -3.0, None))


def test_s3_needs_winning_record_strictly_above_500():
    hist = streak_hist("CHA", list("WWLL"), D - timedelta(3)) + streak_hist("BOS", list("WWWW"), D - timedelta(1))
    assert 3 not in systems(run(hist, "BOS", "CHA", -3.0, None))


def test_s3_needs_home_team_favored():
    hist = streak_hist("CHA", list("WWWL"), D - timedelta(3)) + streak_hist("BOS", list("WWWW"), D - timedelta(1))
    assert 3 not in systems(run(hist, "BOS", "CHA", +1.0, None))
    assert 3 not in systems(run(hist, "BOS", "CHA", 0.0, None))


# ---------------- System 4 ----------------
def s4_hist(fav_last="W", dog_last="L"):
    return streak_hist("OKC", [fav_last], D - timedelta(2)) + streak_hist("WAS", [dog_last], D - timedelta(2))


def test_s4_fires_home_fav():
    s4 = [p for p in run(s4_hist(), "WAS", "OKC", home_spread=-12.5, total=228.5) if p.system == 4]
    assert len(s4) == 1 and s4[0].side == "OVER" and s4[0].line == 228.5


def test_s4_fires_road_fav():
    s4 = [p for p in run(s4_hist(), "OKC", "WAS", home_spread=+12.5, total=228.5) if p.system == 4]
    assert len(s4) == 1


def test_s4_boundaries():
    assert 4 not in systems(run(s4_hist(), "WAS", "OKC", -9.0, 228.5))    # must be MORE than 9
    assert 4 in systems(run(s4_hist(), "WAS", "OKC", -9.5, 228.5))
    assert 4 not in systems(run(s4_hist(), "WAS", "OKC", -12.5, 220.0))   # must be ABOVE 220
    assert 4 in systems(run(s4_hist(), "WAS", "OKC", -12.5, 220.5))


def test_s4_needs_fav_won_and_dog_lost():
    assert 4 not in systems(run(s4_hist("L", "L"), "WAS", "OKC", -12.5, 228.5))
    assert 4 not in systems(run(s4_hist("W", "W"), "WAS", "OKC", -12.5, 228.5))


def test_s4_not_in_first_game_of_season():
    assert 4 not in systems(run([], "WAS", "OKC", -12.5, 228.5))


# ---------------- grading ----------------
def test_grading():
    final = Game("x", D, "BOS", "CHA", away_score=110, home_score=104, periods=4, final=True)
    assert grade(Pick(2, "x", "spread", "BOS", -5.5), final) == "W"
    assert grade(Pick(2, "x", "spread", "BOS", -6.0), final) == "P"
    assert grade(Pick(2, "x", "spread", "BOS", -6.5), final) == "L"
    assert grade(Pick(1, "x", "spread", "CHA", +6.5), final) == "W"
    assert grade(Pick(4, "x", "total", "OVER", 213.5), final) == "W"
    assert grade(Pick(4, "x", "total", "OVER", 214.5), final) == "L"


# ---------------- real 2025-26 games ----------------
def test_real_state_okc_after_double_ot_opener():
    gs = fixture_games()
    okc = team_state("OKC", gs, date(2025, 10, 23))
    assert okc.record == "1-0" and okc.last_ot and okc.last_won and okc.days_rest == 1


def test_real_system1_gsw_oct_24():
    gs = fixture_games()
    game = next(x for x in gs if x.game_date == date(2025, 10, 24) and x.away == "GSW")
    picks = evaluate(game, team_state(game.home, gs, game.game_date),
                     team_state(game.away, gs, game.game_date), None, None)
    assert [(p.system, p.side) for p in picks] == [(1, "POR")]


def test_t25_fades_a_tanker_in_the_last_three_weeks():
    from engine.state import Game, TeamState
    from engine.systems import evaluate_mined
    g = Game("g", __import__("datetime").date(2027, 4, 1), "WAS", "BOS", tip_utc=None)
    good, tank = TeamState("BOS", wins=50, losses=20), TeamState("WAS", wins=15, losses=55)
    picks = evaluate_mined(g, good, tank, -12.0, None, {"last21": True})
    assert [(p.system, p.side, p.line) for p in picks if p.system == 125] == [(125, "BOS", -12.0)]
    assert not [p for p in evaluate_mined(g, good, tank, -12.0, None, {"last21": False}) if p.system == 125]
    both = evaluate_mined(g, TeamState("BOS", wins=20, losses=50), tank, -2.0, None, {"last21": True})
    assert not [p for p in both if p.system == 125]          # two tankers: no bet
