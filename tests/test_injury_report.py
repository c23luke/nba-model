"""The NBA's official injury report: parsing the PDF layout and overriding ESPN's statuses."""
import io
from datetime import datetime, timezone

import pytest

from engine import injury_report as IR

LINES = [
    "Injury Report: 10/21/26 05:15 PM",
    "Game Date Game Time Matchup Team Player Name Current Status Reason",
    "10/21/2026 07:00 (ET) IND@NOP Indiana Pacers Haliburton, Tyrese Out Injury/Illness - Right Achilles; Rehabilitation",
    "Nembhard, Andrew Questionable Injury/Illness - Left Knee;",
    "Soreness",                                                         # wrapped reason
    "New Orleans Pelicans Williamson, Zion Probable Injury/Illness - Left Hamstring; Strain",
    "Murphy III, Trey Available -",
    "UTA@MEM Utah Jazz NOT YET SUBMITTED",
    "Memphis Grizzlies Morant, Ja Doubtful Injury/Illness - Right Ankle; Sprain",
    "08:00 (ET) LAC@DEN LA Clippers Leonard, Kawhi Out Injury/Illness - Left Knee; Management",
    "Page 1 of 3",
]


def test_parses_blocks_fill_down_and_wrapped_reasons():
    rows, missing = IR.parse_lines(LINES)
    got = [(r["team"], r["player"], r["status"]) for r in rows]
    assert got == [("IND", "Tyrese Haliburton", "Out"), ("IND", "Andrew Nembhard", "Questionable"),
                   ("NOP", "Zion Williamson", "Probable"), ("NOP", "Trey Murphy III", "Available"),
                   ("MEM", "Ja Morant", "Doubtful"), ("LAC", "Kawhi Leonard", "Out")]
    assert missing == ["UTA"]
    assert rows[0]["matchup"] == "IND@NOP" and rows[-1]["matchup"] == "LAC@DEN" and rows[0]["date"] == "10/21/2026"


def test_official_status_overrides_espn():
    rows, missing = IR.parse_lines(LINES)
    rosters = {"NOP": [{"fullName": "Zion Williamson", "injuries": [{"status": "Day-To-Day"}]},
                       {"fullName": "Trey Murphy III", "injuries": []}],
               "IND": [{"fullName": "Andrew Nembhard", "injuries": []}, {"fullName": "Tyrese Haliburton", "injuries": []}],
               "MEM": [{"fullName": "Ja Morant", "injuries": []}]}
    changed = IR.apply(rosters, {"rows": rows, "not_submitted": missing})
    from engine.personnel import _status
    st = {a["fullName"]: _status(a) for t in rosters.values() for a in t}
    assert st == {"Zion Williamson": "active", "Trey Murphy III": "active", "Andrew Nembhard": "day-to-day",
                  "Tyrese Haliburton": "out", "Ja Morant": "day-to-day"}
    assert any("Zion Williamson" in c and "Probable" in c for c in changed)
    assert not any("Trey Murphy" in c for c in changed)            # nothing changed for him


def test_report_urls_step_back_every_15_minutes_in_eastern_time():
    u = IR.slot_urls(datetime(2026, 10, 21, 3, 14, tzinfo=timezone.utc), 2)
    assert [x[1].rsplit("/", 1)[1] for x in u] == ["Injury-Report_2026-10-20_11_00PM.pdf", "Injury-Report_2026-10-20_10_45PM.pdf"]


def test_latest_falls_back_to_the_newest_report_that_exists():
    seen = []
    def fetch(url):
        seen.append(url)
        return None if len(seen) < 3 else b"pdf"
    IR_parse = IR.parse
    try:
        IR.parse = lambda pdf: ([{"team": "IND", "key": "x", "status": "Out"}], [])
        rep = IR.latest(datetime(2026, 10, 21, 3, 14, tzinfo=timezone.utc), fetch=fetch)
    finally:
        IR.parse = IR_parse
    assert rep["url"].endswith("10_30PM.pdf") and len(seen) == 3


def test_reads_a_real_pdf_table_layout():
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(842, 595))
    c.setFont("Helvetica", 8)
    xs = [20, 80, 130, 175, 290, 420, 480]
    y = 560
    c.drawString(20, 575, "Injury Report: 10/21/26 05:15 PM")
    for cells in [["Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason"],
                  ["10/21/2026", "07:00 (ET)", "IND@NOP", "Indiana Pacers", "Haliburton, Tyrese", "Out", "Injury/Illness - Right Achilles"],
                  ["", "", "", "", "Nembhard, Andrew", "Questionable", "Injury/Illness - Left Knee;"],
                  ["", "", "", "", "", "", "Soreness"],
                  ["", "", "", "New Orleans Pelicans", "Williamson, Zion", "Probable", "Injury/Illness - Left Hamstring"],
                  ["", "", "UTA@MEM", "Utah Jazz", "", "", "NOT YET SUBMITTED"]]:
        for x, t in zip(xs, cells):
            if t:
                c.drawString(x, y, t)
        y -= 14
    c.drawString(380, 20, "Page 1 of 1")
    c.save()
    rows, missing = IR.parse(buf.getvalue())
    assert [(r["team"], r["player"], r["status"]) for r in rows] == [
        ("IND", "Tyrese Haliburton", "Out"), ("IND", "Andrew Nembhard", "Questionable"), ("NOP", "Zion Williamson", "Probable")]
    assert missing == ["UTA"]
