"""Personnel read: rate each team from the players it has NOW, using each player's own
numbers from last season wherever he played. A player's history follows the player;
a team's history does not follow the jersey. No prior-season TEAM numbers are used.

Inputs
  data_static/players_2025_26.csv  last season, one row per player: final team, games,
                                   minutes, BPM (Basketball-Reference; traded players = season total)
  ESPN rosters (live)              who is on each team today, years of experience, injury status

Method (every step is shown in the output)
  1. Match each rostered player to his own line from last season.
  2. Players listed OUT get no minutes. Day-to-day players stay in, flagged.
  3. Minutes: split 240 among available players in proportion to last season's
     minutes per game (capped at 38), scaled down for players with under 50 games.
  4. Impact blends the last two seasons (older one at half weight), and small samples
     are pulled toward a bench-level baseline:
        bpm_used = (bpm26*mp26 + bpm25*0.5*mp25 + BASELINE*PULL) / (mp26 + 0.5*mp25 + PULL)
     Role (minutes per game) uses both seasons too, so a star who missed last season
     keeps his healthy role and is flagged "back from a missed season".
  5. Players with no NBA minutes last season are UNKNOWN: listed by name, counted,
     given no number. If the known players can't fill 240 minutes, the gap is shown
     and filled at league average (BPM 0). That fill is stated in the output, never hidden.
  6. Team rating (points per 100 possessions vs an average team) = sum of bpm_used * min/48.
  7. Fair home spread = -(home rating - away rating + HOME_COURT).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .sources import get_json
from .teams import code

BASELINE = -1.5      # typical bench-level BPM a small sample is pulled toward
PULL = 400           # minutes of "baseline" blended in
HOME_COURT = 2.0     # points; assumption, stated on the board
MIN_CAP = 38.0
ROLE_GAMES = 50      # games needed for last season's minutes per game to count in full
UNKNOWN_FLAG_MIN = 30  # unknown minutes above this → low-confidence rating

STATIC = Path(__file__).resolve().parent.parent / "data_static"
DATA = STATIC / "players_2025_26.csv"          # last season
DATA_PREV = STATIC / "players_2024_25.csv"     # season before (100+ minutes only)
PREV_WEIGHT = 0.5                              # the older season counts half
ESPN_TEAMS = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
ESPN_ROSTER = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’\-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _read(path: Path) -> dict[str, dict]:
    out = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            try:
                team = code(r["final_team"])
            except KeyError:
                team = None
            out[norm(r["name"])] = {"name": r["name"], "team": team, "g": int(r["g"] or 0),
                                    "mp": int(r["mp"] or 0), "bpm": float(r["bpm"] or 0)}
    return out


def load_last_season(path: Path = DATA, prev_path: Path = DATA_PREV) -> dict[str, dict]:
    """Each player's own record over the last two seasons, wherever he played.

    role mpg  = all minutes / all games across both seasons (an injured star keeps his healthy role)
    bpm_blend = minutes-weighted, older season counted at half weight, plus the small-sample pull
    """
    cur, prev = _read(path), _read(prev_path)
    out = {}
    for key in set(cur) | set(prev):
        c, q = cur.get(key), prev.get(key)
        mp26, g26 = (c["mp"], c["g"]) if c else (0, 0)
        mp25, g25 = (q["mp"], q["g"]) if q else (0, 0)
        if mp26 + mp25 == 0:
            continue
        w26, w25 = mp26, PREV_WEIGHT * mp25
        b26 = c["bpm"] if c else 0.0
        b25 = q["bpm"] if q else 0.0
        out[key] = {
            "name": (c or q)["name"],
            "team": (c["team"] if c and mp26 else q["team"]),
            "g": g26 + g25, "mp": mp26 + mp25,
            "mpg": (mp26 + mp25) / (g26 + g25) if g26 + g25 else 0.0,
            "bpm": b26 if mp26 else b25,                      # most recent season, for display
            "bpm_blend": (b26 * w26 + b25 * w25 + BASELINE * PULL) / (w26 + w25 + PULL),
            "mp26": mp26, "g26": g26, "bpm26": b26 if c else None,
            "mp25": mp25, "g25": g25, "bpm25": b25 if q else None,
            "team25": q["team"] if q else None,
            "missed_last": mp26 == 0,
        }
    return out


@dataclass
class Player:
    name: str
    status: str                      # "active", "out", "day-to-day"
    experience: int | None
    last: dict | None                # last season line, or None = unknown
    minutes: float = 0.0
    bpm_used: float | None = None

    @property
    def known(self) -> bool:
        return bool(self.last and self.last["mp"] > 0)


@dataclass
class TeamRead:
    team: str
    players: list[Player] = field(default_factory=list)
    rating: float = 0.0
    unknown_minutes: float = 0.0
    continuity: float = 0.0          # share of minutes from players who ended last season here

    @property
    def out(self):      return [p for p in self.players if p.status == "out"]
    @property
    def dtd(self):      return [p for p in self.players if p.status == "day-to-day"]
    @property
    def unknown(self):  return [p for p in self.players if not p.known and p.status != "out"]
    @property
    def rotation(self): return sorted([p for p in self.players if p.minutes > 0], key=lambda p: -p.minutes)
    @property
    def low_confidence(self) -> bool:
        return self.unknown_minutes > UNKNOWN_FLAG_MIN


def _status(athlete: dict) -> str:
    inj = [str(i.get("status", "")).lower() for i in athlete.get("injuries") or []]
    if any(s in ("out", "injured reserve", "suspension") or s.startswith("out") for s in inj):
        return "out"
    if any(s for s in inj):
        return "day-to-day"
    return "active"


def fetch_rosters(fetch=get_json) -> dict[str, list[dict]]:
    teams = fetch(ESPN_TEAMS)["sports"][0]["leagues"][0]["teams"]
    out = {}
    for t in teams:
        tid, abbr = t["team"]["id"], t["team"]["abbreviation"]
        out[code(abbr)] = fetch(ESPN_ROSTER.format(tid)).get("athletes", [])
    return out


def rate_team(team: str, athletes: list[dict], last: dict[str, dict]) -> TeamRead:
    tr = TeamRead(team)
    for a in athletes:
        name = a.get("displayName") or a.get("fullName") or ""
        exp = (a.get("experience") or {}).get("years")
        tr.players.append(Player(name, _status(a), exp, last.get(norm(name))))

    avail = [p for p in tr.players if p.status != "out" and p.known]
    for p in avail:
        p.bpm_used = p.last["bpm_blend"]
    # Minutes per game only counts as a real role if he played enough games (over two
    # seasons) to earn it: 15 games at 29 mpg is mostly garbage time, not a rotation spot.
    want = {id(p): min(p.last["mpg"], MIN_CAP) * min(1.0, p.last["g"] / ROLE_GAMES) for p in avail}
    total = sum(want.values())
    scale = 240 / total if total > 240 else 1.0
    for p in avail:
        p.minutes = want[id(p)] * scale
    filled = sum(p.minutes for p in avail)
    tr.unknown_minutes = max(0.0, 240 - filled)        # filled at league average (0)

    tr.rating = sum(p.bpm_used * p.minutes / 48 for p in avail)
    same = sum(p.minutes for p in avail if p.last["team"] == team)
    tr.continuity = same / 240
    return tr


def fair_home_spread(home: TeamRead, away: TeamRead) -> float:
    return -(home.rating - away.rating + HOME_COURT)


def evidence(tr: TeamRead) -> list[str]:
    """Flags that carry their own evidence."""
    lines = []
    new = [p for p in tr.rotation if p.last and p.last["team"] != tr.team]
    lines.append(f"{tr.team}: {tr.continuity:.0%} of projected minutes from players who finished last season here")
    if new:
        top = sorted(new, key=lambda p: -p.minutes)[:4]
        lines.append("New in the rotation: " + ", ".join(
            f"{p.name} ({p.last['team'] or '?'}, {p.last['mp']} min, BPM {p.last['bpm']:+.1f})" for p in top))
    if tr.out:
        lines.append("OUT: " + ", ".join(
            f"{p.name}" + (f" ({p.last['mpg']:.0f} mpg, BPM {p.last['bpm']:+.1f})" if p.known else " (no NBA log)")
            for p in tr.out))
    back = [p for p in tr.rotation if p.last and p.last["missed_last"]]
    if back:
        lines.append("Back from a missed season (rated on 2024-25): " + ", ".join(
            f"{p.name} ({p.last['mp25']} min, BPM {p.last['bpm25']:+.1f}, projected {p.minutes:.0f} mpg)"
            for p in back))
    if tr.dtd:
        lines.append("Day-to-day: " + ", ".join(p.name for p in tr.dtd))
    if tr.unknown:
        lines.append(f"UNKNOWN (no NBA minutes in either of the last two seasons): {len(tr.unknown)} — "
                     + ", ".join(p.name for p in tr.unknown))
    if tr.unknown_minutes > 0.5:
        lines.append(f"{tr.unknown_minutes:.0f} of 240 minutes can't be filled by known players "
                     f"(rated league-average){' — LOW CONFIDENCE' if tr.low_confidence else ''}")
    return lines


def read_all(fetch=get_json, path: Path = DATA, prev_path: Path = DATA_PREV) -> dict[str, TeamRead]:
    last = load_last_season(path, prev_path)
    return {t: rate_team(t, ath, last) for t, ath in fetch_rosters(fetch).items()}


def report(reads: dict[str, TeamRead], games: list[tuple[str, str, float | None, float | None]]) -> str:
    """games: (away, home, market home spread, total)."""
    out = ["TEAM RATINGS (per 100 vs average, from current personnel)"]
    for t, r in sorted(reads.items(), key=lambda kv: -kv[1].rating):
        out.append(f"  {t}  {r.rating:+6.2f}  continuity {r.continuity:4.0%}  unknown min {r.unknown_minutes:4.0f}"
                   f"  out {len(r.out)}  rotation: " + ", ".join(f"{p.name} {p.minutes:.0f}" for p in r.rotation[:8]))
    out.append("")
    out.append("GAMES (market vs personnel fair line; positive gap = personnel likes the home team more than the market)")
    rows = []
    for away, home, mkt, total in games:
        h, a = reads[home], reads[away]
        fair = fair_home_spread(h, a)
        gap = None if mkt is None else mkt - fair
        rows.append((abs(gap or 0), away, home, mkt, fair, gap, total, h, a))
    for _, away, home, mkt, fair, gap, total, h, a in sorted(rows, key=lambda r: -r[0]):
        out.append(f"{away} @ {home}: market {home} {mkt:+.1f} | personnel fair {home} {fair:+.1f} | "
                   f"gap {gap:+.1f}" if mkt is not None else f"{away} @ {home}: no market line | fair {home} {fair:+.1f}")
        for line in evidence(a) + evidence(h):
            out.append("    " + line)
    return "\n".join(out)


def market_check(pairs: list[tuple[float, float]]) -> str:
    """How closely personnel fair lines track the market across the slate (sanity check)."""
    pairs = [(m, f) for m, f in pairs if m is not None]
    n = len(pairs)
    if n < 3:
        return f"Market check: only {n} games with lines — not enough to check."
    mx = sum(m for m, _ in pairs) / n
    fx = sum(f for _, f in pairs) / n
    cov = sum((m - mx) * (f - fx) for m, f in pairs)
    vm = sum((m - mx) ** 2 for m, _ in pairs)
    vf = sum((f - fx) ** 2 for _, f in pairs)
    r = cov / (vm * vf) ** 0.5 if vm and vf else float("nan")
    slope = cov / vf if vf else float("nan")
    mae = sum(abs(m - f) for m, f in pairs) / n
    return (f"Market check over {n} games: correlation {r:.2f}, market moves {slope:.2f} pts per 1 pt of "
            f"personnel line, average gap {mae:.1f} pts.")


if __name__ == "__main__":
    import os
    from datetime import datetime, timedelta, timezone
    from . import sources

    now = datetime.now(timezone.utc)
    today = now.astimezone(sources.ET).date()
    games, espn_lines = [], {}
    for d in (today, today + timedelta(1)):
        for g, line in sources.espn_day(d):
            if not g.final:
                games.append(g)
                if line:
                    espn_lines[g.id] = line
    odds = {}
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    if key:
        odds, _ = sources.odds_api_lines(key)
    rows = []
    for g in games:
        ln = odds.get((g.game_date, g.away, g.home)) or espn_lines.get(g.id) or {}
        rows.append((g.away, g.home, ln.get("home_spread"), ln.get("total")))
    reads = read_all()
    print(report(reads, rows))
    print()
    print(market_check([(m, fair_home_spread(reads[h], reads[a])) for a, h, m, _ in rows]))
