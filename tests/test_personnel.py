"""Personnel ratings: matching, minutes, unknowns, injuries — on a tiny fake league."""
from engine import personnel as P


def ath(name, years=3, injury=None):
    return {"displayName": name, "experience": {"years": years},
            "injuries": [{"status": injury}] if injury else []}


LAST = {
    P.norm("Star Guard"): {"name": "Star Guard", "team": "BOS", "g": 70, "mp": 2450, "mpg": 35.0, "bpm": 6.0},
    P.norm("Role Wing Jr."): {"name": "Role Wing Jr.", "team": "NYK", "g": 70, "mp": 1750, "mpg": 25.0, "bpm": 0.0},
    P.norm("Tiny Sample"): {"name": "Tiny Sample", "team": "BOS", "g": 5, "mp": 40, "mpg": 8.0, "bpm": 15.0},
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
