"""Every variation gets graded: stacks, system vs personnel, personnel by gap / call, CLV."""
from engine.run import tracking, live_stacks, clv, _records
from engine.systems import SYSTEMS, label, group


def pk(system, game, side, result, active=True, bet="spread", meta=None, line=-3.0):
    return {"key": f"{game}-S{system}-{side}", "system": system, "game_id": game, "bet": bet, "side": side,
            "result": result, "active": active, "meta": meta or {}, "line": line, "label": f"{side} {line}",
            "away": "A", "home": "H", "tip_utc": "2026-10-22T00:00Z", "tag": label(system), "group": group(system)}


def test_clv_direction():
    assert clv("spread", "LAL", 5.0, 3.5) == 1.5        # got +5, closed +3.5
    assert clv("spread", "LAL", -3.0, -4.5) == 1.5      # laid 3, closed 4.5
    assert clv("total", "OVER", 220.0, 223.0) == 3.0
    assert clv("total", "UNDER", 220.0, 223.0) == -3.0


def test_stacks_combos_and_conflicts():
    picks = [pk(202, "g1", "H", "W"), pk(113, "g1", "H", "W"), pk(101, "g1", "H", "W"),
             pk(1, "g2", "A", "L"), pk(106, "g2", "H", "W"),          # conflict: opposite sides
             pk(202, "g3", "H", "L"),
             pk(202, "g4", "H", "W", active=False)]                    # dropped → not official
    t = tracking(picks)
    assert t["by_combo"]["E2+T1+T13"]["w"] == 1
    assert t["by_groups"]["EARLY+FAV+TEST"]["w"] == 1      # T1 is TEST since the 2-season replay
    assert t["by_count"]["3 systems"]["w"] == 1 and t["by_count"]["1 system"]["n"] == 3
    assert t["by_pair"]["E2+T13"]["w"] == 1 and t["by_pair"]["T1+T13"]["w"] == 1 and t["by_pair"]["E2+T1"]["w"] == 1
    assert t["conflicts"] == 1


def test_four_plus_stacks_and_stack_plus_players():
    picks = [pk(301, "g1", "H", "W", meta={"gap": 6.5, "call": "now"})] + \
            [pk(s, "g1", "H", "W") for s in (1, 102, 112, 202)]
    t = tracking(picks)
    assert t["by_count"]["4+ systems"]["w"] == 1
    assert t["stack_vs_personnel"]["4+ systems + players agree 6+"]["w"] == 1
    assert t["each_system_vs_personnel"]["S1 + players agree 6+"]["w"] == 1


def test_system_vs_personnel_and_personnel_buckets():
    picks = [pk(301, "g1", "H", "W", meta={"gap": 3.4, "call": "now"}),
             pk(301, "g2", "A", "L", meta={"gap": 0.6, "call": "none"}),
             pk(301, "g3", "H", "W", meta={"gap": 3.1, "call": "waiting"}),
             pk(202, "g1", "H", "W"), pk(202, "g2", "H", "W")]
    t = tracking(picks)
    assert t["system_vs_personnel"]["EARLY + players agree 3-6"]["w"] == 1      # same side, players model by 3.4
    assert t["system_vs_personnel"]["EARLY + players disagree 0-3"]["w"] == 1   # other side by 0.6
    assert t["each_system_vs_personnel"]["E2 + players agree 3-6"]["w"] == 1
    assert t["personnel_by_gap"]["3–4"]["w"] == 2 and t["personnel_by_gap"]["0–1"]["l"] == 1
    assert t["personnel_by_call"]["waiting"]["w"] == 1


def test_records_split_official_dropped_and_first_line():
    picks = [pk(1, "g1", "H", "W", meta={"result_first": "W", "clv": 1.0}),
             pk(1, "g2", "H", "L", active=False, meta={"result_first": "W", "clv": -0.5})]
    r = _records(SYSTEMS, picks)[1]
    assert (r["w"], r["l"]) == (1, 0)                          # official = still qualified at tip
    assert r["if_first"]["w"] == 2 and r["dropped"]["l"] == 1
    assert r["avg_clv"] == 0.25


def test_live_stacks_ignore_shadow():
    live = [pk(202, "g1", "H", None), pk(113, "g1", "H", None), pk(301, "g1", "H", None),
            pk(202, "g2", "H", None)]
    s = live_stacks(live)
    assert len(s) == 1 and s[0]["systems"] == ["E2", "T13"]
