"""Bottom-up props model (2026-11-11): the projection arithmetic."""
from engine.prop_model import P, project


def f(**kw):
    base = {"m5": 30.0, "m10": 30.0, "mseason": 30.0, "min_season": 900.0,
            "pts_r10": 0.5, "pts_rs": 0.5, "pts_rpos": 0.5, "reb_r10": 0.2, "reb_rs": 0.2, "reb_rpos": 0.2,
            "ast_r10": 0.1, "ast_rs": 0.1, "ast_rpos": 0.1}
    base.update(kw)
    return base


def test_plain_night_is_minutes_times_rate():
    pr = project(f(), P())
    assert pr["min"] == 30.0 and round(pr["pts"], 6) == 15.0 and round(pr["reb"], 6) == 6.0


def test_history_minutes_jump_and_usage_vacuum_and_team_total():
    p = P(split_trust=0.5, usage_k=1.0, team_total_exp=1.0, shrink_min=0.0)
    pr = project(f(split_gain=8.0, pts_absent_share=0.2, team_total=120.0, team_avg=110.0), p)
    assert pr["min"] == 34.0
    assert round(pr["pts"], 4) == round(34 * 0.5 / 0.8 * 120 / 110, 4)


def test_returning_star_loses_minutes_and_opponent_factor_shrinks_with_few_games():
    pr = project(f(returning=7), P())
    assert pr["min"] == 30 - 6.7
    p = P(opp_w=1.0, opp_shrink=10.0)
    pr = project(f(pts_opp=1.2, opp_games=10), p)
    assert round(pr["pts"], 6) == round(15 * (1 + 0.2 * 10 / 20), 6)
