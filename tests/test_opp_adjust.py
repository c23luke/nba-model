"""Opponent adjustment of player box impact (2026-11-11). Off by default: the live model is unchanged."""
from engine import boxscore as B


def game(gid, a, b, a_pts, b_pts, star_team=None, star_pts=0):
    rows = []
    for t, tp in ((a, a_pts), (b, b_pts)):
        for i in range(5):
            pts = tp / 5
            name = f"{t}{i}"
            if t == star_team and i == 0:
                name, pts = "Star", star_pts
            rows.append({"game_id": gid, "game_date": "2026-11-01", "team": t, "espn_id": name, "name": name,
                         "min": 48, "pts": pts, "fga": 0, "fta": 0, "fg3m": 0, "orb": 0, "drb": 0, "ast": 0, "stl": 0,
                         "blk": 0, "tov": 0, "pf": 0, "team_poss": 100, "game_min": 48})
    return rows


def test_off_by_default_and_numbers_against_good_teams_count_more():
    # GOOD beat BAD by 20; then Star (on MID) faces GOOD, and a twin faces BAD with the same box score
    rows = game("g1", "GOOD", "BAD", 120, 100) + game("g2", "MID", "GOOD", 100, 100, "MID", 30) \
        + game("g3", "MID2", "BAD", 100, 100, "MID2", 30)
    for r in rows:
        if r["game_id"] == "g3" and r["name"] == "Star":
            r["espn_id"] = "Twin"
    assert B.OPP_BETA == 0.0
    plain = B.season_impact(rows)
    assert plain["Star"]["bpm_live"] == plain["Twin"]["bpm_live"]
    adj = B.season_impact(rows, opp_beta=1.0)
    st = B.opponent_strength(rows)
    # the star's 30 replaces a 20, so MID and MID2 score 110: GOOD +20 and -10 -> +5; BAD -20 and -10 -> -15
    assert st["GOOD"] == 5.0 and st["BAD"] == -15.0
    assert round(adj["Star"]["bpm_live"] - plain["Star"]["bpm_live"], 6) == 5.0
    assert round(adj["Twin"]["bpm_live"] - plain["Twin"]["bpm_live"], 6) == -15.0


def test_plus_minus_blend_is_off_by_default_and_credits_a_plus_player():
    rows = game("g1", "A", "B", 100, 100)
    for r in rows:
        r["pm"] = 0
        if r["name"] == "A0":
            r["pm"] = 10                 # +10 while his team was even
    assert B.PM_WEIGHT == 0.0
    plain = B.season_impact(rows)
    adj = B.season_impact(rows, pm_weight=1.0)
    # 100 possessions on court: +10 per 100 relative, shrunk by 100 / (100 + 1000)
    assert round(adj["A0"]["bpm_live"] - plain["A0"]["bpm_live"], 6) == round(10 * 100 / 1100, 6)
    assert adj["A1"]["bpm_live"] == plain["A1"]["bpm_live"]
