"""Download a season of Basketball-Reference player BPM and a draft class (run in GitHub Actions).

    python -m engine.fetch_bbref 2024     # 2023-24 advanced stats + 2023 draft
Writes data_static/players_2023_24.csv (name;final_team;age;g;mp;bpm) and data_static/drafts_2023.csv.
"""
from __future__ import annotations

import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "data_static"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace").replace("<!--", "").replace("-->", "")


class Rows(HTMLParser):
    """Collect <tr> rows of one table as {data-stat: text}."""
    def __init__(self, table_id):
        super().__init__()
        self.want, self.inside, self.rows, self.row, self.cell = table_id, False, [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and a.get("id") == self.want:
            self.inside = True
        elif self.inside and tag == "tr":
            self.row = {"_class": a.get("class") or ""}
        elif self.inside and self.row is not None and tag in ("td", "th") and a.get("data-stat"):
            self.cell = a["data-stat"]
            self.row[self.cell] = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.inside:
            self.inside = False
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag in ("td", "th"):
            self.cell = None

    def handle_data(self, data):
        if self.row is not None and self.cell:
            self.row[self.cell] += data


def advanced(season_end: int, offdef: bool = False) -> list[str]:
    p = Rows("advanced")
    p.feed(get(f"https://www.basketball-reference.com/leagues/NBA_{season_end}_advanced.html"))
    by = {}
    for r in p.rows:
        if "thead" in r["_class"]:
            continue
        name = (r.get("name_display") or r.get("player") or "").strip().rstrip("*")
        team = (r.get("team_name_abbr") or r.get("team_id") or "").strip()
        if not name or name == "League Average" or not (r.get("games", r.get("g", "")) or "").strip().isdigit():
            continue
        rec = (team, r.get("age", ""), r.get("games", r.get("g", "")), r.get("mp", ""), r.get("bpm", ""),
               r.get("obpm", ""), r.get("dbpm", ""))
        d = by.setdefault(name, {"tot": None, "last": None})
        if team == "TOT" or team.endswith("TM"):
            d["tot"] = rec
        else:
            d["last"] = rec            # rows run in order, so the last team row = final team
    out = []
    for name, d in by.items():
        base = d["tot"] or d["last"]
        final = (d["last"] or base)[0]
        cols = [name, final, base[1], base[2], base[3], base[4]] + ([base[5], base[6]] if offdef else [])
        out.append(";".join(cols))
    return out


def draft(year: int) -> list[str]:
    p = Rows("stats")
    p.feed(get(f"https://www.basketball-reference.com/draft/NBA_{year}.html"))
    out = []
    for r in p.rows:
        pick = (r.get("pick_overall") or "").strip()
        name = (r.get("player") or "").strip()
        if pick.isdigit() and name:
            out.append(f"{year};{pick};{name};{(r.get('college_name') or '').strip()}")
    return out


def offdef_files(ends):
    for end in ends:
        rows = advanced(end, offdef=True)
        f = STATIC / f"players_od_{end - 1}_{str(end)[2:]}.csv"
        f.write_text("name;final_team;age;g;mp;bpm;obpm;dbpm\n" + "\n".join(rows) + "\n", encoding="utf-8")
        print(f"{f.name}: {len(rows)} players")
        time.sleep(4)


if __name__ == "__main__":
    if sys.argv[1] == "offdef":
        offdef_files([int(x) for x in sys.argv[2:]])
        sys.exit()
    end = int(sys.argv[1])
    rows = advanced(end)
    f = STATIC / f"players_{end - 1}_{str(end)[2:]}.csv"
    f.write_text("name;final_team;age;g;mp;bpm\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"{f.name}: {len(rows)} players")
    time.sleep(4)
    d = draft(end - 1)
    g = STATIC / f"drafts_{end - 1}.csv"
    g.write_text("year;pick;name;college\n" + "\n".join(d) + "\n", encoding="utf-8")
    print(f"{g.name}: {len(d)} picks")
