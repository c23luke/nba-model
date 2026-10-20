"""Box score parsing, the measured box→BPM formula, and in-season blending."""
from engine import boxscore as B
from engine import personnel as P
from tests.test_personnel import ath, LAST, rec

KEYS = ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
        "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted",
        "rebounds", "assists", "turnovers", "steals", "blocks", "offensiveRebounds",
        "defensiveRebounds", "fouls", "plusMinus"]


def team(abbr, players):
    return {"team": {"abbreviation": abbr}, "statistics": [{"keys": KEYS, "athletes": players}]}


def pl(pid, name, stats, dnp=False):
    return {"athlete": {"id": pid, "displayName": name}, "stats": [] if dnp else stats, "didNotPlay": dnp}


SUMMARY = {"boxscore": {"players": [
    team("NY", [pl("1", "Star Guard", ["40", "35", "12-22", "4-9", "7-8", "6", "8", "2", "2", "1", "1", "5", "2", "+12"]),
                pl("2", "Bench Guy", ["200", "0", "0-0", "0-0", "0-0", "0", "0", "0", "0", "0", "0", "0", "0", "0"], dnp=True)]
               + [pl(str(10 + i), f"Filler {i}", ["50", "10", "4-10", "1-3", "1-2", "4", "2", "1", "1", "0", "1", "3", "2", "+2"]) for i in range(4)]),
    team("CLE", [pl(str(20 + i), f"Cav {i}", ["48", "20", "8-18", "2-6", "2-3", "5", "4", "2", "1", "1", "1", "4", "3", "-3"]) for i in range(5)]),
]}}


def test_parse_summary_skips_dnp_and_adds_possessions():
    rows = B.parse_summary(SUMMARY, "g1", "2026-10-20")
    assert len(rows) == 10 and not any(r["name"] == "Bench Guy" for r in rows)
    star = next(r for r in rows if r["name"] == "Star Guard")
    assert (star["fgm"], star["fga"], star["fg3m"], star["fta"], star["pm"]) == (12, 22, 4, 8, 12)
    # NY: 62 FGA + 0.44 x 16 FTA - 5 ORB + 6 TOV = 70.04
    assert star["game_min"] == 48.0 and star["team_poss"] == 70.0


def test_season_impact_uses_measured_formula():
    imp = B.season_impact(B.parse_summary(SUMMARY, "g1", "2026-10-20"))
    assert imp["1"]["bpm_live"] > imp["10"]["bpm_live"]          # 35-8-6 star beats filler
    assert imp["1"]["games"] == 1 and imp["1"]["mpg"] == 40


def test_live_minutes_blend_into_rating():
    live = {"1": {"name": "Star Guard", "min": 1000, "games": 30, "mpg": 33.3, "bpm_live": 10.0}}
    base = P.rate_team("BOS", [{**ath("Star Guard"), "id": 1}, ath("Role Wing")], LAST)
    upd = P.rate_team("BOS", [{**ath("Star Guard"), "id": 1}, ath("Role Wing")], LAST, live=live)
    b0 = base.players[0].bpm_used
    u = upd.players[0]
    assert abs(u.bpm_used - (b0 * 1000 + 10.0 * 1000) / 2000) < 1e-9     # veteran prior = 1000 min
    assert any("this season" in s for s in u.steps)


def test_undrafted_unknown_becomes_known_through_live_play():
    live = {"9": {"name": "Walk On", "min": 300, "games": 10, "mpg": 30.0, "bpm_live": 2.0}}
    tr = P.rate_team("BOS", [ath("Role Wing"), {**ath("Walk On", 0), "id": 9}], LAST, live=live)
    w = [p for p in tr.players if p.name == "Walk On"][0]
    assert w.known and w.minutes > 15
    assert abs(w.bpm_used - (P.BASELINE * 300 + 2.0 * 300) / 600) < 1e-9


def test_recent_games_weigh_more_for_minutes():
    from engine.boxscore import season_impact
    base = {"espn_id": "9", "name": "Kyrie", "team": "DAL", "team_poss": 100.0, "game_min": 48.0,
            **{s: 2 for s in ["pts", "fga", "fta", "fg3m", "orb", "drb", "ast", "stl", "blk", "tov", "pf"]}}
    rows = [{**base, "game_date": f"2026-10-{d}", "min": m} for d, m in
            [("21", 20), ("23", 20), ("25", 32), ("27", 32), ("29", 32)]]
    v = season_impact(rows)["9"]
    assert v["mpg"] == 27.2
    assert v["w_min"] / v["w_games"] > v["mpg"]          # minutes going up → projection leans up
    assert v["last3"] == [32, 32, 32]
