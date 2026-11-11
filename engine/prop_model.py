"""BOTTOM-UP PLAYER PROPS MODEL (Caden 2026-11-11: "let's build a bottom up origination model ... I trust you").

Projection for one player tonight = MINUTES x RATE PER MINUTE x CONTEXT.

MINUTES
  base       his recent minutes (weighted between his last 5, last 10 and season, in games he played)
  absences   a rotation teammate out tonight who played the last game (fresh): if this season has 2+ games without
             that teammate, his real minutes then (trusted part-way); otherwise the absent minutes shared out in
             proportion to everyone's minutes (trusted part-way)
  returning  a 28+ mpg player back after 3+ straight games out: the measured first-game drop
  blowout    spread 12+: starters a little less (measured -2.4), bench a little more
RATE PER MINUTE (points, rebounds, assists)
  blend of his last 10 games and his season, shrunk toward his position's league rate when the sample is small
  usage vacuum: his share grows when teammates who take that stat are out: rate / (1 - absent share) ^ k
CONTEXT
  team total: the market's implied team total tonight vs his team's average points so far (points; ^ exponent)
  game total: the market's total vs the league average so far (rebounds and assists; ^ exponent)
  opponent by position: what tonight's opponent gives up per minute to his position group (guards / wings /
  bigs) vs the league, over its games so far, shrunk by games played (^ weight)
Every weight is a parameter in P, chosen on 2024-25 by engine.measure_prop_model and tested on 2025-26.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STATS = ("pts", "reb", "ast")


def group(pos: str) -> str:
    p = (pos or "").upper()
    if p in ("C", "F-C", "C-F", "PF"):
        return "big"
    if p in ("PG", "SG", "G"):
        return "guard"
    return "wing"


@dataclass
class P:
    w5: float = 0.4            # minutes: weight on last 5 (rest split last 10 / season below)
    w10: float = 0.4
    split_trust: float = 0.6   # with/without history (measured 0.60 overall, 0.95 bench)
    share_trust: float = 0.3   # naive shared-out minutes (measured: +5.9 expected -> +1.5 real)
    rate_recent: float = 0.5   # rate: weight on last 10 vs season
    shrink_min: float = 150.0  # rate shrinks toward the position rate with weight min / (min + shrink)
    usage_k: float = 0.5       # usage vacuum exponent
    team_total_exp: float = 0.5
    game_total_exp: float = 0.5
    opp_w: float = 0.5         # opponent-by-position factor ^ opp_w
    opp_shrink: float = 10.0   # opponent factor uses n / (n + shrink) of its games
    luck_l: float = 0.0        # shooting luck: take this share of his recent FG points above expected off his rate
    match_w: float = 0.0       # shot diet vs the opponent's zone defense: factor ^ match_w
    blowout: bool = True
    returning: bool = True
    extra: dict = field(default_factory=dict)


RETURN_GAME1 = ((5, -3.6), (10, -6.7), (20, -6.4), (999, -9.1))


def project(f: dict, p: P) -> dict:
    """f: the features for one player tonight (built by engine.measure_prop_model.features).
    Returns {"min": projected minutes, "pts": ..., "reb": ..., "ast": ...}."""
    base = p.w5 * f["m5"] + p.w10 * f["m10"] + (1 - p.w5 - p.w10) * f["mseason"]
    add = 0.0
    if f.get("split_gain") is not None:
        add += p.split_trust * f["split_gain"]
    elif f.get("share_gain"):
        add += p.share_trust * f["share_gain"]
    if p.returning and f.get("returning"):
        add += next(d for lim, d in RETURN_GAME1 if f["returning"] <= lim)
    if p.blowout and f.get("abs_spread") is not None and f["abs_spread"] >= 12:
        add += -2.4 if base >= 30 else 2.0 if base < 15 else 0.0
    mins = max(0.0, min(44.0, base + add))
    out = {"min": mins}
    for s in STATS:
        r10, rs, rpos = f[f"{s}_r10"], f[f"{s}_rs"], f[f"{s}_rpos"]
        rate = p.rate_recent * r10 + (1 - p.rate_recent) * rs
        w = f["min_season"] / (f["min_season"] + p.shrink_min)
        rate = w * rate + (1 - w) * rpos
        if s == "pts" and p.luck_l and f.get("luck_pm") is not None:
            rate -= p.luck_l * f["luck_pm"]
        absent = min(0.6, f.get(f"{s}_absent_share") or 0.0)
        rate /= (1 - absent) ** p.usage_k
        ctx = 1.0
        if s == "pts" and f.get("team_total") and f.get("team_avg"):
            ctx *= (f["team_total"] / f["team_avg"]) ** p.team_total_exp
        elif s != "pts" and f.get("game_total") and f.get("league_total"):
            ctx *= (f["game_total"] / f["league_total"]) ** p.game_total_exp
        o, n = f.get(f"{s}_opp"), f.get("opp_games") or 0
        if o:
            ctx *= (1 + (o - 1) * n / (n + p.opp_shrink)) ** p.opp_w
        if s == "pts" and p.match_w and f.get("shot_match"):
            ctx *= f["shot_match"] ** p.match_w
        out[s] = mins * rate * ctx
    return out


# ------------------------------------------------------------------ shared history (backtest AND live)
from collections import defaultdict as _dd


def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


TUNED = P(w5=0.4, w10=0.2, split_trust=0.3, share_trust=0.0, rate_recent=0.3, shrink_min=50.0, usage_k=0.5,
          team_total_exp=0.0, game_total_exp=0.0, opp_w=0.5, opp_shrink=10.0)   # chosen on 2024-25 (2026-11-11)


ZONES = ("rim", "short", "mid", "corner3", "above3")


def zone(x: float, y: float, three: bool) -> str:
    """ESPN court coordinates (feet; basket at x=25, y~0)."""
    import math
    d = math.hypot(x - 25, y)
    if three:
        return "corner3" if y < 9 else "above3"
    return "rim" if d < 4 else "short" if d < 14 else "mid"


class History:
    """Everything the projection needs from games already played this season. Feed games in date order with
    add(home, away, {team: {name: (min, pts, reb, ast)}}); positions come from pos (name -> ESPN position)."""

    def __init__(self, pos: dict | None = None):
        self.pos = pos if pos is not None else {}
        self.plog = _dd(list)
        self.tgames = _dd(list)
        self.tpts = _dd(list)
        self.allowed = _dd(lambda: _dd(lambda: [0.0, 0.0, 0.0, 0.0]))
        self.allowed_n = _dd(int)
        self.league = _dd(lambda: [0.0, 0.0, 0.0, 0.0])
        self.league_tot = []
        self.shots = _dd(list)                                          # player -> [{zone: [att, pts]}] per game played
        self.zdef = _dd(lambda: {z: [0.0, 0.0] for z in ZONES})        # team -> zone -> [att, pts] allowed
        self.zleague = {z: [0.0, 0.0] for z in ZONES}

    def add_shots(self, home: str, away: str, shots: list) -> None:
        """shots: [(team, name, zone, points)] for tonight (points 0 on a miss). Call BEFORE add() for the game."""
        per = _dd(lambda: {z: [0, 0] for z in ZONES})
        for team, name, z, pts in shots:
            opp = away if team == home else home
            per[name][z][0] += 1; per[name][z][1] += pts
            self.zdef[opp][z][0] += 1; self.zdef[opp][z][1] += pts
            self.zleague[z][0] += 1; self.zleague[z][1] += pts
        for name, d in per.items():
            self.shots[name].append(d)
        self._shot_names = set(per)

    def shot_features(self, name: str, opp: str) -> dict:
        """luck_pm: FG points per minute above what his shots were worth at league rates (last 10 games with shots);
        shot_match: what tonight's opponent allows on HIS shot mix vs the league (shrunk by its attempts)."""
        gs = self.shots.get(name) or []
        if len(gs) < 5:
            return {}
        L = {z: (v[1] / v[0] if v[0] else 0.0) for z, v in self.zleague.items()}
        last = gs[-10:]
        att = {z: sum(g[z][0] for g in last) for z in ZONES}
        pts = sum(g[z][1] for g in last for z in ZONES)
        exp = sum(att[z] * L[z] for z in ZONES)
        mins = sum(x[0] for x in self.plog[name][-len(last):]) or 1
        tot = sum(att.values()) or 1
        D = self.zdef[opp]
        num = den = 0.0
        for z in ZONES:
            if not L[z]:
                continue
            a_ = D[z][0]
            opp_rate = (D[z][1] + 50 * L[z]) / (a_ + 50)                # shrunk toward the league with 50 attempts
            num += att[z] / tot * opp_rate
            den += att[z] / tot * L[z]
        return {"luck_pm": (pts - exp) / mins, "shot_match": num / den if den else None}

    def add(self, home: str, away: str, tonight: dict) -> None:
        for team in (home, away):
            opp = away if team == home else home
            gm = tonight.get(team) or {}
            self.tgames[team].append(gm)
            self.tpts[team].append(sum(v[1] for v in gm.values()))
            for nm, v in gm.items():
                if v[0] > 0:
                    self.plog[nm].append(v)
                    if getattr(self, "_shot_names", None) is not None and nm not in self._shot_names and nm in self.shots:
                        self.shots[nm].append({z: [0, 0] for z in ZONES})     # played, no shots: keep games lined up
                    grp = group(self.pos.get(nm, ""))
                    A = self.allowed[opp][grp]
                    for i in range(4):
                        A[i] += v[i]
                        self.league[grp][i] += v[i]
            self.allowed_n[opp] += 1
        self.league_tot.append(sum(v[1] for t in tonight.values() for v in t.values()))
        self._shot_names = None

    def features(self, team: str, opp: str, playing: set, absent: set, home_spread: float | None,
                 game_total: float | None, is_home: bool) -> list[dict]:
        """Features for every player in `playing` (5+ games of his own). `absent` = players not playing tonight."""
        past = self.tgames[team]
        if len(past) < 5:
            return []
        last10 = past[-10:]
        mins = _dd(list)
        for gm in last10:
            for nm, v in gm.items():
                mins[nm].append(v[0])
        rot = {nm: sum(v) / len(last10) for nm, v in mins.items()
               if len([x for x in v if x > 0]) >= 5 and sum(v) / len(last10) >= 20}
        prev = past[-1]
        fresh = sorted([a for a in rot if a in absent and (prev.get(a) or (0,))[0] > 0], key=lambda a: -rot[a])
        tot = [sum(v[i] for gm in last10 for v in gm.values()) or 1 for i in (1, 2, 3)]
        ab_share = [sum(gm.get(a, (0, 0, 0, 0))[i] for gm in last10 for a in fresh) / tot[i - 1] for i in (1, 2, 3)]
        mpg_now = {nm: _avg([x[0] for x in self.plog[nm][-10:]]) for nm in playing if self.plog[nm]}
        denom = sum(mpg_now.values()) or 1
        absent_min = sum(rot[a] for a in fresh)
        team_total = None
        if home_spread is not None and game_total is not None:
            home_tt = (game_total - home_spread) / 2
            team_total = home_tt if is_home else game_total - home_tt
        spread = None if home_spread is None else (home_spread if is_home else -home_spread)
        lt = _avg(self.league_tot) if len(self.league_tot) >= 20 else None
        out = []
        for nm in playing:
            lg = self.plog[nm]
            if len(lg) < 5:
                continue
            grp = group(self.pos.get(nm, ""))
            l10 = lg[-10:]
            f = {"name": nm, "team": team, "grp": grp,
                 "m5": _avg([x[0] for x in lg[-5:]]), "m10": _avg([x[0] for x in l10]), "mseason": _avg([x[0] for x in lg]),
                 "min_season": sum(x[0] for x in lg), "fresh_out": len(fresh), "fresh_names": fresh,
                 "abs_spread": None if spread is None else abs(spread), "team_total": team_total,
                 "team_avg": _avg(self.tpts[team]) if len(self.tpts[team]) >= 3 else None,
                 "game_total": game_total, "league_total": lt, "opp_games": self.allowed_n[opp]}
            L_ = self.league[grp]
            A_ = self.allowed[opp][grp]
            for i, s in enumerate(STATS, start=1):
                f[f"{s}_r10"] = sum(x[i] for x in l10) / (sum(x[0] for x in l10) or 1)
                f[f"{s}_rs"] = sum(x[i] for x in lg) / (sum(x[0] for x in lg) or 1)
                f[f"{s}_rpos"] = L_[i] / L_[0] if L_[0] else f[f"{s}_rs"]
                f[f"{s}_opp"] = (A_[i] / A_[0]) / (L_[i] / L_[0]) if A_[0] > 100 and L_[0] and L_[i] else None
                f[f"{s}_absent_share"] = ab_share[i - 1]
                f[f"{s}_l10avg"] = _avg([x[i] for x in l10])
                f[f"{s}_savg"] = _avg([x[i] for x in lg])
            f["split_gain"] = None
            for a in fresh:
                w = [gm[nm][0] for gm in past if (gm.get(nm) or (0,))[0] > 0 and (gm.get(a) or (0,))[0] > 0]
                wo = [gm[nm][0] for gm in past if (gm.get(nm) or (0,))[0] > 0 and not (gm.get(a) or (0,))[0] > 0]
                if len(wo) >= 2 and w:
                    f["split_gain"] = _avg(wo) - _avg(w)
                    break
            f["share_gain"] = absent_min * mpg_now.get(nm, 0) / denom if fresh else 0.0
            streak = 0
            for gm in reversed(past):
                if (gm.get(nm) or (0,))[0] > 0:
                    break
                streak += 1
            f["returning"] = streak if streak >= 3 and f["mseason"] >= 28 else None
            f.update(self.shot_features(nm, opp))
            out.append(f)
        return out


def live_projections(box_rows: list[dict], games: list, reads: dict, pos: dict) -> dict:
    """(game_id, normalised name) -> projection for every player on tonight's reads who isn't ruled out,
    using this season's box scores (engine.boxscore rows) and the TUNED weights."""
    from .personnel import norm
    by_game = _dd(lambda: _dd(dict))
    meta = {}
    for r in box_rows:
        by_game[r["game_id"]][r["team"]][r["name"]] = (r.get("min") or 0, r.get("pts") or 0,
                                                       (r.get("orb") or 0) + (r.get("drb") or 0), r.get("ast") or 0)
        meta[r["game_id"]] = str(r.get("game_date") or "")
    H = History(pos)
    for gid in sorted(by_game, key=lambda g: (meta[g], g)):
        teams = list(by_game[gid])
        if len(teams) == 2:
            H.add(teams[0], teams[1], by_game[gid])
    out = {}
    for g in games:
        for team, opp in ((g.home, g.away), (g.away, g.home)):
            r = reads.get(team)
            if r is None:
                continue
            playing = {p.name for p in r.players if p.status != "out"}
            absent = {p.name for p in r.players if p.status == "out"}
            for f in H.features(team, opp, playing, absent, None, None, team == g.home):
                pr = project(f, TUNED)
                out[(g.id, norm(f["name"]))] = {**{k: round(v, 1) for k, v in pr.items()}, "name": f["name"],
                                                "team": team, "l10": {s: round(f[f"{s}_l10avg"], 1) for s in STATS},
                                                "fresh_out": f["fresh_names"], "returning": f["returning"]}
    return out
