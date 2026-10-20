"""The 4 TrendsCenter systems, rule for rule from the cards.

"team" = the side we bet. Every rule that passes writes a plain-English line of
evidence so the board shows exactly why a bet fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .state import Game, TeamState

SYSTEMS = {
    1: {"name": "Fade OT winner on no rest", "bet": "spread",
        "card": "218-143-7 · 60.4% · +15% ROI · 23 yrs", "card_win_rate": 0.6039},
    2: {"name": "Road favorite on 4+ game losing streak", "bet": "spread",
        "card": "120-62-3 · 65.9% · +25.5% ROI · 30 yrs", "card_win_rate": 0.6593},
    3: {"name": "Home favorite vs hot team on no rest", "bet": "spread",
        "card": "215-143-5 · 60.1% · +14.5% ROI · 30 yrs", "card_win_rate": 0.6006},
    4: {"name": "Heavy favorite over", "bet": "total",
        "card": "476-353-15 · 57.4% · +9.5% ROI · 30 yrs", "card_win_rate": 0.5742},
}


@dataclass
class Pick:
    system: int
    game_id: str
    bet: str                 # "spread" or "total"
    side: str                # team code, or "OVER"
    line: float | None       # team's spread (e.g. -4.5) or the total; None = line not out yet
    evidence: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.game_id}-S{self.system}-{self.side}"

    def label(self) -> str:
        if self.bet == "total":
            return f"OVER {self.line:g}" if self.line is not None else "OVER (no total yet)"
        if self.line is None:
            return f"{self.side} (no line yet)"
        return f"{self.side} {self.line:+g}" if self.line != 0 else f"{self.side} PK"


def _rest(st: TeamState) -> str:
    if st.days_rest is None:
        return "first game of the season"
    if st.days_rest == 0:
        return "playing the second night of a back-to-back (0 days rest)"
    return f"{st.days_rest} day{'s' if st.days_rest != 1 else ''} rest"


def evaluate(game: Game, home: TeamState, away: TeamState,
             home_spread: float | None, total: float | None) -> list[Pick]:
    """Run all 4 systems on one game. Spread systems are checked from both sides."""
    picks: list[Pick] = []
    sides = [
        (game.home, home, away, True, home_spread),
        (game.away, away, home, False, None if home_spread is None else -home_spread),
    ]

    for team, t, o, is_home, spread in sides:
        # ---- System 1: fade the OT winner on no rest (no line needed to fire)
        if o.days_rest == 0 and o.last_ot and o.last_won:
            g = o.last_game
            picks.append(Pick(1, game.id, "spread", team, spread, [
                f"{o.team} won last night in overtime: {g.score_line()} ({g.game_date:%b %d})",
                f"{o.team} is {_rest(o)}",
                f"Bet {team} against them",
            ]))

        # ---- System 2: road favorite on a 4+ game losing streak
        if (not is_home and spread is not None and spread < 0
                and (t.days_rest is None or t.days_rest > 0)
                and t.lose_streak > 3 and o.lose_streak < 4):
            picks.append(Pick(2, game.id, "spread", team, spread, [
                f"{team} is on the road and still favored ({spread:+g})",
                f"{team} has lost {t.lose_streak} straight ({t.record})",
                f"{team} is on {_rest(t)}, not a back-to-back",
                f"{o.team}'s losing streak is {o.lose_streak} (needs under 4)",
            ]))

        # ---- System 3: home favorite with a winning record vs a hot team on no rest
        if (is_home and spread is not None and spread < 0
                and t.win_pct is not None and t.win_pct > 0.5
                and o.win_streak >= 4 and o.days_rest == 0):
            picks.append(Pick(3, game.id, "spread", team, spread, [
                f"{team} is home and favored ({spread:+g}) with a winning record ({t.record})",
                f"{o.team} has won {o.win_streak} straight",
                f"{o.team} is {_rest(o)}",
            ]))

        # ---- System 4: heavy favorite over
        if (spread is not None and spread < -9.0 and total is not None and total > 220.0
                and t.last_won is True and o.last_won is False):
            picks.append(Pick(4, game.id, "total", "OVER", total, [
                f"{team} is favored by {abs(spread):g} (more than 9)",
                f"Total is {total:g} (above 220)",
                f"{team} won its last game: {t.last_game.score_line()}",
                f"{o.team} lost its last game: {o.last_game.score_line()}",
            ]))
    return picks


def grade(pick: Pick, game: Game) -> str | None:
    """W / L / P for a finished game, graded at the pick's line."""
    if not game.final or pick.line is None:
        return None
    if pick.bet == "total":
        pts = game.home_score + game.away_score
        diff = pts - pick.line
    else:
        mine, theirs = ((game.home_score, game.away_score) if pick.side == game.home
                        else (game.away_score, game.home_score))
        diff = mine - theirs + pick.line
    return "P" if diff == 0 else ("W" if diff > 0 else "L")
