"""The props desk: tracking only. When a rotation player is freshly ruled out, who really gets his minutes?
2026-11-10 spec change: three kinds (history jump / model jump / fake bump), points + rebounds + assists, overs and
unders. The earlier points-only tests were rewritten for it."""
from datetime import date, datetime, timedelta, timezone

from engine import props_desk as PD
from engine.personnel import Player, TeamRead
from engine.props_splits import splits
from engine.state import Game

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
G = Game(id="g1", game_date=date(2026, 11, 10), away="OKC", home="POR", tip_utc="2026-11-11T03:00Z")


def row(gid, name, mins, pts, reb=0, ast=0, team="POR"):
    return {"team": team, "game_id": gid, "game_date": f"2026-11-{int(gid[1:]) + 1:02d}", "name": name, "min": mins,
            "pts": pts, "orb": 0, "drb": reb, "ast": ast}


def box(bench_without=12, n_without=0):
    """10 games: Starter plays the first 10 - n_without; Bench Guard plays 12 min / 6 pts with him and
    `bench_without` minutes (at the same rate) without him."""
    rows = []
    for i in range(10):
        gid = f"x{i}"
        if i < 10 - n_without:
            rows += [row(gid, "Starter", 32, 20, 5, 4), row(gid, "Bench Guard", 12, 6, 2, 1)]
        else:
            rows += [row(gid, "Starter", 0, 0), row(gid, "Bench Guard", bench_without, bench_without // 2, 4, 3)]
    return rows


def reads(bench_minutes=26.0):
    tr = TeamRead("POR")
    tr.players = [Player("Starter", "out", 5, None), Player("Bench Guard", "active", 3, None, minutes=bench_minutes)]
    return {"POR": tr, "OKC": TeamRead("OKC")}


ROT = {"POR": {"starter": {"name": "Starter", "mpg": 32.0, "last": True}}}


def props(pts=8.5, reb=None, ast=None):
    out = {("bench guard", "pts"): {"line": pts, "over": -110, "under": -110, "books": 6}}
    if reb is not None:
        out[("bench guard", "reb")] = {"line": reb, "over": -110, "under": -110, "books": 6}
    if ast is not None:
        out[("bench guard", "ast")] = {"line": ast, "over": -110, "under": -110, "books": 6}
    return out


def test_splits_show_what_a_teammate_did_with_and_without_a_rotation_player():
    s = splits(box(bench_without=28, n_without=3))
    x = s["POR"]["starter"]["bench guard"]
    assert (x["n_with"], x["n_wo"], x["min_with"], x["min_wo"], x["pts_wo"], x["reb_wo"]) == (7, 3, 12.0, 28.0, 14.0, 4.0)


def test_no_history_yet_uses_the_players_model_minutes():
    b = box()
    c = PD.candidates(G, reads(), ROT, PD.scoring(b), splits(b))
    # calibrated 2026-11-10: his usual night (12 min, 6 pts, 2 reb, 1 ast) + the measured no-history gain (+2.8/+0.5/+0.7)
    assert len(c) == 1 and c[0]["kind"] == "jump_model" and c[0]["proj"] == {"pts": 8.8, "reb": 2.5, "ast": 1.7}


def test_a_real_minutes_jump_in_past_games_projects_from_those_games():
    b = box(bench_without=28, n_without=2)
    c = PD.candidates(G, reads(), ROT, PD.scoring(b), splits(b))
    # usual night over his last 10: 15.2 min (not a bench guy), 7.6 pts, 2.4 reb, 1.4 ast; history gain without the
    # starter +16 min / +8 pts / +2 reb / +2 ast, trusted 60% (measured): 7.6 + 4.8, 2.4 + 1.2, 1.4 + 1.2
    assert c[0]["kind"] == "jump_hist" and c[0]["proj"] == {"pts": 12.4, "reb": 3.6, "ast": 2.6} and c[0]["n_wo"] == 2
    assert c[0]["proj_min"] == 24.8 and c[0]["trust"] == 0.6


def test_hidden_bump_when_history_says_minutes_but_the_players_model_does_not():
    b = box(bench_without=28, n_without=2)
    c = PD.candidates(G, reads(13.0), ROT, PD.scoring(b), splits(b))
    assert c[0]["kind"] == "hidden" and c[0]["proj"]["pts"] == 12.4


def test_fake_bump_when_the_model_expects_minutes_but_history_says_no():
    b = box(bench_without=13, n_without=3)              # he played 13 without the starter, 12 with: no bump
    c = PD.candidates(G, reads(26.0), ROT, PD.scoring(b), splits(b))
    # his usual 6.0 pts + the 2.5 points fake-bump players still gained over 2 seasons (usage) = 8.5
    assert c[0]["kind"] == "fake" and c[0]["proj"] == {"pts": 8.5, "reb": 3.0, "ast": 2.2}
    assert PD.step({}, NOW, [G], reads(26.0), ROT, b, lambda g: props(pts=10.5), {})["bets"] == []    # only 2 over
    st = PD.step({}, NOW, [G], reads(26.0), ROT, b, lambda g: props(pts=11.5), {})
    bet = st["bets"][0]
    assert (bet["side"], bet["stat"], bet["line"], bet["price"], bet["edge"]) == ("under", "pts", 11.5, -110, 3.0)
    # two games of history isn't enough to call a bump fake
    b2 = box(bench_without=13, n_without=2)
    assert PD.candidates(G, reads(26.0), ROT, PD.scoring(b2), splits(b2)) == []


def test_paper_over_then_clv_then_grade_and_a_void_if_he_sits():
    b = box()
    st = PD.step({}, NOW, [G], reads(), ROT, b, lambda g: props(pts=5.5, reb=5.5), {})
    got = {(x["stat"], x["side"]) for x in st["bets"]}
    assert got == {("pts", "over")}                     # 2.5 rebounds projected vs 5.5: no rebound bet
    # 30 minutes later: not re-read (every 90 minutes)...
    calls = []
    PD.step(st, NOW + timedelta(minutes=30), [G], reads(), ROT, b, lambda g: calls.append(1) or props(7.5), {})
    assert calls == []
    # ...but read once in the last 30 minutes before tip: the closing line, CLV +2
    st = PD.step(st, datetime(2026, 11, 11, 2, 40, tzinfo=timezone.utc), [G], reads(), ROT, b, lambda g: props(7.5), {})
    assert st["bets"][0]["clv"] == 2.0
    b2 = b + [row("g1", "Bench Guard", 27, 11)]
    st2 = PD.step(st, NOW + timedelta(hours=8), [], reads(), ROT, b2, lambda g: None, {"g1": {"final": True}})
    assert st2["bets"][0]["result"] == "W"
    s = PD.summary(st2)
    assert (s["bets"], s["w"], s["avg_clv"], s["by_kind"]["jump_model"]["w"], s["units"]) == (1, 1, 2.0, 1, 0.91)
    b3 = b + [row("g1", "Bench Guard", 0, 0)]
    assert PD.step(st, NOW + timedelta(hours=8), [], reads(), ROT, b3, lambda g: None, {"g1": {"final": True}})["bets"][0]["result"] == "VOID"


def test_no_bet_when_the_line_already_moved_or_the_news_is_old():
    b = box()
    assert PD.step({}, NOW, [G], reads(), ROT, b, lambda g: props(pts=6.5), {})["bets"] == []     # 8.8 vs 6.5: only 2.3
    rot = {"POR": {"starter": {"name": "Starter", "mpg": 32.0, "last": False}}}      # out a while: nothing new
    assert PD.candidates(G, reads(), rot, PD.scoring(b), splits(b)) == []


def test_parse_props_takes_the_most_common_line_and_its_prices():
    js = {"bookmakers": [
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 8.5, "price": -115},
            {"name": "Under", "description": "Bench Guard", "point": 8.5, "price": -105}]},
            {"key": "player_assists", "outcomes": [
                {"name": "Over", "description": "Bench Guard", "point": 2.5, "price": 120},
                {"name": "Under", "description": "Bench Guard", "point": 2.5, "price": -150}]}]},
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 9.5, "price": 100}]}]},
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 8.5, "price": -110},
            {"name": "Under", "description": "Bench Guard", "point": 8.5, "price": -110}]}]}]}
    p = PD.parse_props(js)
    assert p[("bench guard", "pts")] == {"line": 8.5, "over": -115, "under": -110, "books": 3}
    assert p[("bench guard", "ast")] == {"line": 2.5, "over": 120, "under": -150, "books": 1}


def returning_box():
    """Star plays 34 min / 25 pts for 8 games, then misses 4. Sub plays 14 min / 6 pts, then 28 min / 12 pts while he's out."""
    rows = []
    for i in range(12):
        gid = f"x{i}"
        if i < 8:
            rows += [row(gid, "Star", 34, 25, 6, 5), row(gid, "Sub", 14, 6, 2, 1)]
        else:
            rows += [row(gid, "Star", 0, 0), row(gid, "Sub", 28, 12, 4, 2)]
    return rows


def returning_reads(star="active"):
    tr = TeamRead("POR")
    tr.players = [Player("Star", star, 5, None, minutes=34.0), Player("Sub", "active", 3, None, minutes=14.0)]
    return {"POR": tr, "OKC": TeamRead("OKC")}


def test_a_star_back_after_3_plus_games_and_his_fill_ins_are_unders():
    from engine.props_splits import returns
    b = returning_box()
    r = returns(b)["POR"]["star"]
    assert r["missed"] == 4 and r["pre"]["min"] == 34.0 and r["fill"]["sub"]["during_min"] == 28.0
    c = PD.candidates(G, returning_reads(), {}, PD.scoring(b), {}, returns(b))
    star = next(x for x in c if x["kind"] == "returning")
    # out 3-5 games: measured game-1 change -3.6 min, -1.8 pts, -0.4 reb, -0.6 ast
    assert star["proj"] == {"pts": 23.2, "reb": 5.6, "ast": 4.4} and star["proj_min"] == 30.4
    sub = next(x for x in c if x["kind"] == "fill_back")
    # keeps 47% of his extra 14 minutes: 14 + 6.6 = 20.6 min at his last-10 rate (196 min, 84 pts = 0.43/min) -> 8.8 pts
    assert sub["proj_min"] == 20.6 and sub["proj"]["pts"] == 8.8
    st = PD.step({}, NOW, [G], returning_reads(), {}, b,
                 lambda g: {("star", "pts"): {"line": 26.5, "over": -110, "under": -110, "books": 5},
                            ("sub", "pts"): {"line": 12.5, "over": -110, "under": -110, "books": 5}}, {})
    got = {(x["player"], x["side"], x["stat"], x["edge"]) for x in st["bets"]}
    assert got == {("Star", "under", "pts", 3.3), ("Sub", "under", "pts", 3.7)}


def test_no_returning_bets_while_he_is_still_out_or_questionable_for_his_fill_ins():
    from engine.props_splits import returns
    b = returning_box()
    assert PD.candidates(G, returning_reads("out"), {}, PD.scoring(b), {}, returns(b)) == []
    c = PD.candidates(G, returning_reads("day-to-day"), {}, PD.scoring(b), {}, returns(b))
    assert [x["kind"] for x in c] == ["returning"] and c[0]["dtd"] is True
