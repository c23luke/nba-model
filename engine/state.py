"""Where each team stands going into a game: rest, streaks, record, how its last game went.

Everything here is worked out from final scores only. Counts reset each season
(only games from the current regular season are passed in).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Game:
    id: str
    game_date: date          # US Eastern calendar date of the game
    away: str
    home: str
    away_score: int | None = None
    home_score: int | None = None
    periods: int | None = None   # 4 = regulation, 5 = OT, 6 = 2OT ...
    final: bool = False
    tip_utc: str | None = None

    @property
    def winner(self) -> str | None:
        if not self.final:
            return None
        return self.home if self.home_score > self.away_score else self.away

    @property
    def went_ot(self) -> bool:
        return bool(self.final and self.periods and self.periods > 4)

    def score_line(self) -> str:
        ot = "" if not self.went_ot else (" OT" if self.periods == 5 else f" {self.periods - 4}OT")
        return f"{self.away} {self.away_score} @ {self.home} {self.home_score}{ot}"


@dataclass
class TeamState:
    team: str
    wins: int = 0
    losses: int = 0
    win_streak: int = 0
    lose_streak: int = 0
    last_game: Game | None = None
    days_rest: int | None = None   # None = no game yet this season

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def win_pct(self) -> float | None:
        return self.wins / self.games if self.games else None

    @property
    def last_won(self) -> bool | None:
        return None if self.last_game is None else self.last_game.winner == self.team

    @property
    def last_ot(self) -> bool:
        return bool(self.last_game and self.last_game.went_ot)

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}"

    @property
    def streak(self) -> str:
        if self.win_streak:
            return f"W{self.win_streak}"
        if self.lose_streak:
            return f"L{self.lose_streak}"
        return "-"


def team_state(team: str, finals: list[Game], on_date: date) -> TeamState:
    """State of `team` going into a game on `on_date`, using only games before that day."""
    st = TeamState(team)
    played = sorted(
        (g for g in finals if g.final and g.game_date < on_date and team in (g.home, g.away)),
        key=lambda g: g.game_date,
    )
    for g in played:
        if g.winner == team:
            st.wins += 1
            st.win_streak += 1
            st.lose_streak = 0
        else:
            st.losses += 1
            st.lose_streak += 1
            st.win_streak = 0
    if played:
        st.last_game = played[-1]
        st.days_rest = (on_date - played[-1].game_date).days - 1
    return st
