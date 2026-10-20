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
  5b. Age: each player's number is moved by the age curve MEASURED from the same two
     seasons (average BPM change by age group). Printed at the top of every report.
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
ESPN_ATHLETE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/athletes/{}"
LOTTERY = 14         # an unknown player picked this high will play real minutes → blind spot

# ---- Returning from a major injury (first season back) -----------------------
# Research (NBA players, first season after surgery vs their own pre-injury level):
#   ACL      DeFroda et al., ISAKOS 2021 (n=26): PER -19.3%; 48% of games vs 78.5% pre.
#            Second season back: no significant difference from pre-injury.
#   Achilles Khalil et al., Orthop J Sports Med 2020 (n=27): PER 80% of baseline vs 96% for
#            matched healthy players (16% excess drop); minutes 83% vs 103% (about 0.81x).
# PER -> BPM: measured on 2024-25 (270 players, 1000+ min): BPM = 0.597*PER - 8.86, r=0.90.
PER_TO_BPM = 0.597
INJURY_PER_DROP = {"ACL": 0.193, "Achilles": 0.16}
INJURY_MINUTES = {"ACL": 0.81, "Achilles": 0.81}   # ACL study gave no minutes figure; Achilles' used
# Who is coming back from what (injury as reported at the time), with last healthy PER (2024-25).
RETURNS = {
    "tyrese haliburton": {"injury": "Achilles", "per": 21.8, "when": "June 2025"},
    "damian lillard":    {"injury": "Achilles", "per": 21.3, "when": "April 2025"},
    "kyrie irving":      {"injury": "ACL",      "per": 19.9, "when": "March 2025"},
    "fred vanvleet":     {"injury": "ACL",      "per": 12.8, "when": "September 2025"},
}


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
                                    "mp": int(r["mp"] or 0), "bpm": float(r["bpm"] or 0),
                                    "age": int(r["age"]) if r.get("age") else None}
    return out


AGE_GROUPS = [(19, 21), (22, 23), (24, 25), (26, 27), (28, 29), (30, 31), (32, 33), (34, 45)]


def measure_age_curve(cur: dict, prev: dict, min_mp: int = 500) -> dict[tuple, tuple[float, int]]:
    """Measured, not assumed: average BPM change from 2024-25 to 2025-26 by age in 2024-25,
    weighted by the smaller of the two seasons' minutes. Players with 500+ minutes in both."""
    acc = {g: [0.0, 0.0, 0] for g in AGE_GROUPS}
    for k, c in cur.items():
        q = prev.get(k)
        if not q or c.get("age") is None or c["mp"] < min_mp or q["mp"] < min_mp:
            continue
        age_then = c["age"] - 1
        for lo, hi in AGE_GROUPS:
            if lo <= max(age_then, 19) <= hi:
                w = min(c["mp"], q["mp"])
                acc[(lo, hi)][0] += (c["bpm"] - q["bpm"]) * w
                acc[(lo, hi)][1] += w
                acc[(lo, hi)][2] += 1
    return {g: (a[0] / a[1] if a[1] else 0.0, a[2]) for g, a in acc.items()}


def age_delta(age: int | None, curve: dict) -> float:
    """Expected BPM change into this season for a player who was `age` last season."""
    if age is None:
        return 0.0
    for (lo, hi), (d, _) in curve.items():
        if lo <= max(age, 19) <= hi:
            return d
    return 0.0


AGE_CURVE: dict = {}

DRAFTS = STATIC / "drafts_2024_2025.csv"
PICK_TIERS = [(1, 3), (4, 7), (8, 14), (15, 30), (31, 60)]
ROOKIE_PRIOR: dict = {}


def measure_rookie_prior(path: Path = DRAFTS) -> dict:
    """Measured from the 2024 and 2025 drafts: what each pick range did as rookies.
    bpm   = minutes-weighted rookie BPM of those who played 100+ min
    mpg   = expected minutes per team game (DNPs and G-League stints count as zero)
    share = fraction who played 100+ min."""
    s25, s26 = _read(DATA_PREV), _read(DATA)
    out = {}
    if not path.exists():
        return out
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter=";"))
    for lo, hi in PICK_TIERS:
        tier = [r for r in rows if lo <= int(r["pick"]) <= hi]
        bw = b = mins = games = played = 0
        for r in tier:
            x = (s25 if r["year"] == "2024" else s26).get(norm(r["name"]))
            if x and x["mp"] >= 100:
                played += 1
                bw += x["mp"]; b += x["bpm"] * x["mp"]; mins += x["mp"]; games += x["g"]
        out[(lo, hi)] = {"bpm": b / bw if bw else BASELINE,
                         "mpg": mins / (82 * len(tier)) if tier else 0.0,   # per TEAM game, DNPs included
                         "share": played / len(tier) if tier else 0.0, "n": len(tier)}
    return out


def rookie_prior(pick: int) -> dict | None:
    for (lo, hi), v in ROOKIE_PRIOR.items():
        if lo <= pick <= hi:
            return {**v, "tier": f"{lo}-{hi}"}
    return None


def load_last_season(path: Path = DATA, prev_path: Path = DATA_PREV) -> dict[str, dict]:
    """Each player's own record over the last two seasons, wherever he played.

    role mpg  = all minutes / all games across both seasons (an injured star keeps his healthy role)
    bpm_blend = minutes-weighted, older season counted at half weight, plus the small-sample pull
    """
    cur, prev = _read(path), _read(prev_path)
    AGE_CURVE.clear()
    AGE_CURVE.update(measure_age_curve(cur, prev))
    ROOKIE_PRIOR.clear()
    ROOKIE_PRIOR.update(measure_rookie_prior())
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
            "age": c.get("age") if c else None,
            "age_delta": age_delta(c.get("age") if c else None, AGE_CURVE),
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
    espn_id: str | None = None
    draft: dict | None = None        # {"year", "pick"} for unknown players, looked up on ESPN
    age_now: int | None = None       # ESPN age today
    steps: list[str] = field(default_factory=list)   # how this player's number was built

    prior: dict | None = None         # rookie prior from draft slot (measured)

    @property
    def known(self) -> bool:
        return bool(self.last and self.last["mp"] > 0) or self.prior is not None


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


def rate_team(team: str, athletes: list[dict], last: dict[str, dict],
              drafts: dict[str, dict] | None = None) -> TeamRead:
    tr = TeamRead(team)
    for a in athletes:
        name = a.get("displayName") or a.get("fullName") or ""
        exp = (a.get("experience") or {}).get("years")
        tr.players.append(Player(name, _status(a), exp, last.get(norm(name)),
                                 espn_id=str(a.get("id") or "") or None,
                                 age_now=int(a["age"]) if a.get("age") else None))
    for p in tr.players:
        if p.last is None and drafts and p.espn_id in drafts:
            p.draft = drafts[p.espn_id]
            pr = rookie_prior(p.draft["pick"])
            if pr and pr["mpg"] > 0:
                p.prior = pr
                p.steps.append(f"rookie prior: #{p.draft['pick']} pick {p.draft['year']} → picks {pr['tier']} "
                               f"averaged BPM {pr['bpm']:+.1f} and {pr['mpg']:.0f} min per team game as rookies "
                               f"({pr['share']:.0%} of {pr['n']} played)")

    avail = [p for p in tr.players if p.status != "out" and p.known]
    for p in [p for p in avail if p.prior]:
        p.bpm_used = p.prior["bpm"]
    for p in [p for p in avail if not p.prior]:
        # last two seasons + the measured age curve (young players improve, the oldest decline)
        p.bpm_used = p.last["bpm_blend"] + p.last.get("age_delta", 0.0)
        if p.last.get("missed_last"):
            adjust_return(p)
    # Minutes per game only counts as a real role if he played enough games (over two
    # seasons) to earn it: 15 games at 29 mpg is mostly garbage time, not a rotation spot.
    def wanted(p):
        if p.prior:
            return min(p.prior["mpg"], MIN_CAP)
        return (min(p.last["mpg"], MIN_CAP) * min(1.0, p.last["g"] / ROLE_GAMES)
                * (INJURY_MINUTES[RETURNS[norm(p.name)]["injury"]]
                   if p.last.get("missed_last") and norm(p.name) in RETURNS else 1.0))
    want = {id(p): wanted(p) for p in avail}
    total = sum(want.values())
    scale = 240 / total if total > 240 else 1.0
    for p in avail:
        p.minutes = want[id(p)] * scale
    filled = sum(p.minutes for p in avail)
    tr.unknown_minutes = max(0.0, 240 - filled)        # filled at league average (0)

    tr.rating = sum(p.bpm_used * p.minutes / 48 for p in avail)
    same = sum(p.minutes for p in avail if p.last and p.last["team"] == team)
    tr.continuity = same / 240
    return tr


def adjust_return(p: Player) -> None:
    """A player who missed all of last season: age him two years on the measured curve, and if
    it was a major injury, apply the first-season-back drop from the research above."""
    base = p.last["bpm_blend"]
    b25 = p.last["bpm25"] if p.last.get("bpm25") is not None else p.last["bpm"]
    p.steps.append(f"last healthy season 2024-25: BPM {b25:+.1f} in {p.last['mp25']} min "
                   f"→ {base:+.2f} after the small-sample pull")
    if p.age_now:
        a1, a2 = p.age_now - 2, p.age_now - 1            # ages during 2024-25 and 2025-26
        d = age_delta(a1, AGE_CURVE) + age_delta(a2, AGE_CURVE)
        p.bpm_used += d
        p.steps.append(f"two years of aging (ages {a1}→{a2 + 1}, measured curve): {d:+.2f}")
    else:
        p.steps.append("age not on file: no aging applied")
    r = RETURNS.get(norm(p.name))
    if r:
        drop = INJURY_PER_DROP[r["injury"]] * r["per"] * PER_TO_BPM
        p.bpm_used -= drop
        p.steps.append(f"first season back from {r['injury']} ({r['when']}): PER {r['per']} x "
                       f"{INJURY_PER_DROP[r['injury']]:.1%} x 0.597 = {-drop:+.2f}; minutes x{INJURY_MINUTES[r['injury']]}")
    else:
        p.steps.append("missed season, no major injury on file: aging only")
    p.steps.append(f"= {p.bpm_used:+.2f}")


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
            f"{p.name}" + (f" ({p.last['mpg']:.0f} mpg, BPM {p.last['bpm']:+.1f})" if p.last
                           else f" (#{p.draft['pick']} pick {p.draft['year']}, rookie)" if p.draft
                           else " (no NBA log)")
            for p in tr.out))
    for p in [p for p in tr.rotation if p.prior]:
        lines.append(f"Rookie (rated on draft slot) — {p.name}, {p.bpm_used:+.1f}, {p.minutes:.0f} mpg: "
                     + "; ".join(p.steps))
    for p in [p for p in tr.rotation if p.last and p.last["missed_last"]]:
        lines.append(f"Back from a missed season — {p.name}, rated {p.bpm_used:+.2f}, "
                     f"{p.minutes:.0f} mpg: " + "; ".join(p.steps))
    if tr.dtd:
        lines.append("Day-to-day: " + ", ".join(p.name for p in tr.dtd))
    if tr.unknown:
        lines.append(f"UNKNOWN (no NBA minutes in either of the last two seasons): {len(tr.unknown)} — "
                     + ", ".join(p.name + (f" (#{p.draft['pick']} pick {p.draft['year']})" if p.draft else "")
                                 for p in tr.unknown))
    if tr.unknown_minutes > 0.5:
        lines.append(f"{tr.unknown_minutes:.0f} of 240 minutes can't be filled by known players "
                     f"(rated league-average){' — LOW CONFIDENCE' if tr.low_confidence else ''}")
    return lines


def add_draft_info(reads: dict[str, TeamRead], fetch=get_json) -> None:
    """For players with no NBA numbers, look up where they were drafted (ESPN)."""
    for tr in reads.values():
        for p in tr.unknown:
            if not p.espn_id:
                continue
            try:
                d = fetch(ESPN_ATHLETE.format(p.espn_id)).get("draft") or {}
                if d.get("selection"):
                    p.draft = {"year": d.get("year"), "pick": int(d["selection"])}
            except Exception:
                pass


def lookup_drafts(rosters: dict[str, list[dict]], last: dict, fetch=get_json) -> dict[str, dict]:
    """Draft slot (ESPN) for every rostered player with no NBA numbers."""
    out = {}
    for athletes in rosters.values():
        for a in athletes:
            name = a.get("displayName") or a.get("fullName") or ""
            if norm(name) in last or not a.get("id"):
                continue
            try:
                d = fetch(ESPN_ATHLETE.format(a["id"])).get("draft") or {}
                if d.get("selection"):
                    out[str(a["id"])] = {"year": d.get("year"), "pick": int(d["selection"])}
            except Exception:
                pass
    return out


def read_all(fetch=get_json, path: Path = DATA, prev_path: Path = DATA_PREV) -> dict[str, TeamRead]:
    last = load_last_season(path, prev_path)
    rosters = fetch_rosters(fetch)
    drafts = lookup_drafts(rosters, last, fetch)
    return {t: rate_team(t, ath, last, drafts) for t, ath in rosters.items()}


def report(reads: dict[str, TeamRead], games: list[tuple[str, str, float | None, float | None]]) -> str:
    """games: (away, home, market home spread, total)."""
    out = ["ROOKIE PRIOR (measured: 2024 + 2025 drafts, rookie seasons):"]
    out.append("  " + " | ".join(f"picks {lo}-{hi}: BPM {v['bpm']:+.1f}, {v['mpg']:.0f} mpg, {v['share']:.0%} played (n={v['n']})"
                                 for (lo, hi), v in ROOKIE_PRIOR.items()))
    out.append("AGE CURVE (measured from players with 500+ min in both 2024-25 and 2025-26):")
    out.append("  " + " | ".join(f"age {lo}-{hi}: {d:+.2f} (n={n})" for (lo, hi), (d, n) in AGE_CURVE.items()))
    out.append("  Players with no age on file (missed 2025-26) get no age adjustment.")
    out.append("")
    out.append("TEAM RATINGS (per 100 vs average, from current personnel)")
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


# --------------------------------------------------------------- board helpers
BLIND_UNKNOWN_MIN = 20
GAP_TO_FIRE = 3.0


def blind_reasons(tr: TeamRead) -> list[str]:
    """Where this model can't see what the market sees. A gap here is not an edge."""
    top8 = tr.rotation[:8]
    out = []
    for p in tr.unknown:      # drafted high but no prior could be built (should be rare)
        if p.draft and p.draft["pick"] <= LOTTERY:
            out.append(f"{tr.team}: {p.name} (#{p.draft['pick']} pick {p.draft['year']}) has no NBA numbers")
    rookie_min = sum(p.minutes for p in tr.rotation if p.prior)
    if rookie_min > 40:
        out.append(f"{tr.team}: {rookie_min:.0f} minutes rated only on draft slot")
    if tr.unknown_minutes > BLIND_UNKNOWN_MIN:
        out.append(f"{tr.team}: {tr.unknown_minutes:.0f} minutes from players with no NBA numbers")
    for p in top8:
        if p.status == "day-to-day":
            out.append(f"{tr.team}: {p.name} ({p.minutes:.0f} mpg) is day-to-day")
        if p.last and p.last.get("missed_last") and norm(p.name) not in RETURNS and p.minutes >= 20:
            out.append(f"{tr.team}: {p.name} ({p.minutes:.0f} mpg) missed last season, cause not on file")
    return out


def calibrate(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Fit market = a + b * personnel across the slate (needs 6+ games with lines)."""
    pairs = [(m, f) for m, f in pairs if m is not None]
    if len(pairs) < 6:
        return None
    n = len(pairs)
    mx = sum(m for m, _ in pairs) / n
    fx = sum(f for _, f in pairs) / n
    vf = sum((f - fx) ** 2 for _, f in pairs)
    if not vf:
        return None
    b = sum((m - mx) * (f - fx) for m, f in pairs) / vf
    return mx - b * fx, b


def game_view(away: TeamRead, home: TeamRead, market: float | None, cal) -> dict:
    raw = fair_home_spread(home, away)
    fair = raw if cal is None else cal[0] + cal[1] * raw
    gap = None if market is None else market - fair
    blind = blind_reasons(away) + blind_reasons(home)
    return {
        "raw": round(raw, 1), "fair": round(fair * 2) / 2, "gap": None if gap is None else round(gap, 1),
        "calibrated": cal is not None, "blind": blind,
        "away_rating": round(away.rating, 2), "home_rating": round(home.rating, 2),
        "evidence": evidence(away) + evidence(home),
    }
