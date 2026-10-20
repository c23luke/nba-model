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


# ---------------- board integration ----------------
from datetime import date
from engine.state import Game
from engine.systems import evaluate_personnel


def test_calibrate_needs_six_and_fits_line():
    assert P.calibrate([(1.0, 2.0)] * 5) is None
    pairs = [(0.5 * f + 1.0, f) for f in (-10, -6, -2, 0, 3, 8)]
    a, b = P.calibrate(pairs)
    assert abs(a - 1.0) < 1e-9 and abs(b - 0.5) < 1e-9


def test_day_to_day_priced_both_ways_not_blind():
    roster = [ath("Star Guard", injury="Day-To-Day")] + [ath("Role Wing")] * 8
    play = P.rate_team("BOS", roster, LAST)
    play.sit = P.rate_team("BOS", roster, LAST, dtd_sit=True)
    assert not P.blind_reasons(play)
    assert play.sit.rating < play.rating               # losing the star makes them worse
    opp = P.rate_team("NYK", [ath("Role Wing")] * 9, LAST)
    v = P.game_view(opp, play, -3.0, None)
    assert len(v["scenarios"]) == 2 and v["waiting_on"] == ["BOS: Star Guard"]
    assert v["scenarios"][0]["fair"] < v["scenarios"][1]["fair"]   # BOS bigger favorite if he plays


def test_personnel_call_now_waiting_none():
    from engine.systems import personnel_call
    both = {"gap": 4.0, "blind": [], "scenarios": [{"gap": 4.0}, {"gap": 3.2}]}
    assert personnel_call(both)["call"] == "now"
    one = {"gap": 4.0, "blind": [], "scenarios": [{"gap": 4.0}, {"gap": 0.5}]}
    c = personnel_call(one)
    assert c["call"] == "waiting" and c["side"] == "home"
    assert personnel_call({"gap": 1.0, "blind": [], "scenarios": [{"gap": 1.0}]})["call"] == "none"
    assert personnel_call({"gap": 6.0, "blind": ["x"], "scenarios": []})["call"] == "none"


def test_blind_when_back_from_missed_season():
    last = dict(LAST)
    r = rec("Back Star", "BOS", 60, 2100, 4.0); r["missed_last"] = True
    last[P.norm("Back Star")] = r
    tr = P.rate_team("BOS", [ath("Back Star"), ath("Role Wing")], last)
    assert any("missed last season, cause not on file" in x for x in P.blind_reasons(tr))


def test_t13_fires_on_clean_gap_only():
    g = Game("x", date(2026, 10, 22), "CHA", "BKN")
    clean = {"gap": -5.0, "fair": 4.0, "blind": [], "away_rating": 1.2, "home_rating": -4.8}
    picks = evaluate_personnel(g, -1.0, clean)
    assert [(p.system, p.side, p.line) for p in picks] == [(113, "CHA", 1.0)]
    assert evaluate_personnel(g, -1.0, {**clean, "gap": -2.5}) == []
    assert evaluate_personnel(g, -1.0, {**clean, "blind": ["CHA: someone missed last season"]}) == []
    # gap only exists if a day-to-day player sits → waiting, no bet yet
    assert evaluate_personnel(g, -1.0, {**clean, "scenarios": [{"gap": -5.0}, {"gap": -1.0}]}) == []
    home = evaluate_personnel(g, -1.0, {**clean, "gap": +4.0})
    assert [(p.side, p.line) for p in home] == [("BKN", -1.0)]



def test_lottery_rookie_gets_draft_prior():
    P.ROOKIE_PRIOR.clear()
    P.ROOKIE_PRIOR.update({(1, 3): {"bpm": -0.9, "mpg": 27.0, "share": 1.0, "n": 6},
                           (31, 60): {"bpm": -2.6, "mpg": 12.0, "share": 0.7, "n": 57}})
    roster = [ath("Star Guard"), ath("Role Wing"), {**ath("Top Pick", 0), "id": 99}]
    tr = P.rate_team("WAS", roster, LAST, drafts={"99": {"year": 2026, "pick": 1}})
    tp = [p for p in tr.players if p.name == "Top Pick"][0]
    assert tp.prior and tp.bpm_used == -0.9 and abs(tp.minutes - 27.0) < 1e-9
    assert not tr.unknown
    assert any("Rookie (rated on draft slot)" in e for e in P.evidence(tr))
    late = P.rate_team("WAS", [ath("Role Wing"), {**ath("Late Pick", 0), "id": 98}], LAST,
                       drafts={"98": {"year": 2026, "pick": 41}})
    lp = [p for p in late.players if p.name == "Late Pick"][0]
    assert abs(lp.minutes - 12.0) < 1e-9


def test_returning_star_gets_a_number_with_steps():
    last = dict(LAST)
    r = rec("Kyrie Irving", "DAL", 50, 1804, 3.4)
    r.update(missed_last=True, mp25=1804, bpm25=3.4, mp26=0, bpm26=None,
             bpm_blend=(3.4 * 902 + P.BASELINE * P.PULL) / (902 + P.PULL))
    last[P.norm("Kyrie Irving")] = r
    P.AGE_CURVE.clear(); P.AGE_CURVE.update({(19, 21): (1.0, 1), (32, 33): (0.3, 1), (34, 45): (-0.4, 1)})
    tr = P.rate_team("DAL", [{**ath("Kyrie Irving"), "age": 34}, ath("Role Wing")], last)
    k = tr.players[0]
    acl = 0.193 * 19.9 * 0.597
    assert abs(k.bpm_used - (r["bpm_blend"] + 0.3 + 0.3 - acl)) < 1e-9     # ages 32 and 33, then ACL
    assert any("ACL" in s for s in k.steps) and k.minutes < 36 * 0.82
    assert not any("Kyrie" in b for b in P.blind_reasons(tr))              # rated, so not blind



def test_injured_rookie_in_evidence_does_not_crash():
    P.ROOKIE_PRIOR.clear()
    P.ROOKIE_PRIOR.update({(1, 3): {"bpm": -0.9, "mpg": 22.0, "share": 1.0, "n": 6}})
    roster = [ath("Star Guard"), {**ath("Hurt Rookie", 0, injury="Out"), "id": 7}]
    tr = P.rate_team("SAS", roster, LAST, drafts={"7": {"year": 2026, "pick": 2}})
    ev = P.evidence(tr)
    assert any("OUT: Hurt Rookie (#2 pick 2026, rookie)" in e for e in ev)
    assert P.report({"SAS": tr, "BOS": tr}, [("SAS", "BOS", -2.0, 220.0)])   # full report renders



def test_name_fallback_and_old_draftees():
    last = dict(LAST)
    last[P.norm("Ron Holland")] = rec("Ron Holland", "DET", 78, 1551, -2.0)
    assert P.find(last, "Ronald Holland II")["name"] == "Ron Holland"
    assert P.find(last, "Rondo Smith") is None
    P.ROOKIE_PRIOR.clear(); P.ROOKIE_PRIOR.update({(4, 7): {"bpm": -2.3, "mpg": 21.5, "share": 1.0, "n": 8}})
    tr = P.rate_team("CLE", [ath("Role Wing"), {**ath("Euro Vet", 8), "id": 5}], LAST,
                     drafts={"5": {"year": 2015, "pick": 5}})
    ev = [p for p in tr.players if p.name == "Euro Vet"][0]
    assert ev.prior is None and ev in tr.unknown
