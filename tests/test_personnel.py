"""Personnel ratings: matching, minutes, unknowns, injuries — on a tiny fake league."""
from engine import personnel as P


def ath(name, years=3, injury=None):
    return {"displayName": name, "experience": {"years": years},
            "injuries": [{"status": injury}] if injury else []}


def rec(name, team, g, mp, bpm):
    return {"name": name, "team": team, "g": g, "mp": mp, "mpg": mp / g, "bpm": bpm,
            "bpm_blend": (bpm * mp + P.BASELINE * P.PULL) / (mp + P.PULL),
            "mp26": mp, "g26": g, "bpm26": bpm, "mp25": 0, "g25": 0, "bpm25": None,
            "team25": None, "missed_last": False}


LAST = {
    P.norm("Star Guard"): rec("Star Guard", "BOS", 70, 2450, 6.0),
    P.norm("Role Wing Jr."): rec("Role Wing Jr.", "NYK", 70, 1750, 0.0),
    P.norm("Tiny Sample"): rec("Tiny Sample", "BOS", 5, 40, 15.0),
}


def test_name_matching_ignores_accents_and_suffixes():
    assert P.norm("Luka Dončić") == P.norm("Luka Doncic")
    assert P.norm("Role Wing Jr.") == P.norm("Role Wing")


def test_unknowns_are_counted_not_rated():
    tr = P.rate_team("BOS", [ath("Star Guard"), ath("Role Wing"), ath("Fresh Rookie", 0)], LAST)
    assert [p.name for p in tr.unknown] == ["Fresh Rookie"]
    assert abs(tr.unknown_minutes - (240 - 35 - 25)) < 1e-6
    assert tr.low_confidence


def test_small_sample_is_pulled_to_baseline():
    tr = P.rate_team("BOS", [ath("Tiny Sample")], LAST)
    p = tr.players[0]
    assert p.bpm_used < 2.0          # 15.0 in 40 minutes is not believed


def test_out_players_get_no_minutes_and_continuity():
    tr = P.rate_team("BOS", [ath("Star Guard", injury="Out"), ath("Role Wing")], LAST)
    assert tr.players[0].minutes == 0 and tr.players[1].minutes == 25.0
    assert tr.continuity == 0.0                     # only the new player is available
    tr2 = P.rate_team("BOS", [ath("Star Guard"), ath("Role Wing")], LAST)
    assert tr2.rating > tr.rating


def test_minutes_scale_to_240():
    roster = [ath("Star Guard")] * 10                # 10 x 35 mpg = 350 → scaled to 240
    tr = P.rate_team("BOS", roster, LAST)
    assert abs(sum(p.minutes for p in tr.players) - 240) < 1e-6
    assert tr.unknown_minutes == 0


def test_fair_spread_sign():
    good = P.rate_team("BOS", [ath("Star Guard")] * 7, LAST)
    meh = P.rate_team("NYK", [ath("Role Wing")] * 10, LAST)
    assert P.fair_home_spread(good, meh) < -2      # good home team is favored


def test_few_games_shrinks_role():
    last = dict(LAST)
    last[P.norm("Garbage Time")] = rec("Garbage Time", "BOS", 15, 435, -5.0)
    tr = P.rate_team("BOS", [ath("Star Guard"), ath("Garbage Time")], last)
    gt = [p for p in tr.players if p.name == "Garbage Time"][0]
    assert gt.minutes < 10


def test_two_season_loader(tmp_path):
    cur = tmp_path / "c.csv"; prev = tmp_path / "p.csv"
    cur.write_text("name;final_team;age;g;mp;bpm\nInjured Star;IND;25;0;0;0\nTrae Like;WAS;27;15;500;3.0\n")
    prev.write_text("name;final_team;g;mp;bpm\nInjured Star;IND;73;2451;5.8\nTrae Like;ATL;76;2739;0.5\n")
    last = P.load_last_season(cur, prev)
    star = last[P.norm("Injured Star")]
    assert star["missed_last"] and star["team"] == "IND" and abs(star["mpg"] - 2451 / 73) < 1e-9
    assert star["bpm_blend"] > 3.0                       # healthy season carries him
    trae = last[P.norm("Trae Like")]
    assert trae["g"] == 91 and trae["team"] == "WAS"     # role from both seasons, most recent team
    tr = P.rate_team("IND", [ath("Injured Star"), ath("Trae Like")], last)
    assert all(p.minutes > 25 for p in tr.players)       # neither loses his role to games missed


def test_age_curve_is_measured_from_data(tmp_path):
    cur = tmp_path / "c.csv"; prev = tmp_path / "p.csv"
    cur.write_text("name;final_team;age;g;mp;bpm\nYoung A;SAS;21;70;2000;2.0\nOld B;LAL;36;70;2000;-1.0\n")
    prev.write_text("name;final_team;g;mp;bpm\nYoung A;SAS;70;2000;0.0\nOld B;LAL;70;2000;1.0\n")
    last = P.load_last_season(cur, prev)
    assert abs(P.AGE_CURVE[(19, 21)][0] - 2.0) < 1e-9 and P.AGE_CURVE[(19, 21)][1] == 1
    assert abs(P.AGE_CURVE[(34, 45)][0] + 2.0) < 1e-9
    assert last[P.norm("Young A")]["age_delta"] == 2.0     # age 21 last season → young group
