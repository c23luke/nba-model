"""The 4 TrendsCenter systems, rule for rule from the cards.

"team" = the side we bet. Every rule that passes writes a plain-English line of
evidence so the board shows exactly why a bet fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .state import Game, TeamState
from .teams import miles_between

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


# Forward-test systems: tracked and graded live, never shown as bets to take.
# Ids 101-112 show on the board as T1-T12.
TEST_SYSTEMS = {
    101: {"name": "Double-OT hangover", "bet": "spread", "idea": "fatigue",
          "rule": "Opponent played 2OT+ last night (won or lost) → bet against them"},
    102: {"name": "3rd game in 4 nights vs rested team", "bet": "spread", "idea": "fatigue",
          "rule": "Opponent on 3rd game in 4 nights, we have 2+ days rest → bet us"},
    103: {"name": "Back-to-back at altitude", "bet": "spread", "idea": "fatigue",
          "rule": "Opponent on a back-to-back at Denver or Utah → bet DEN/UTA"},
    104: {"name": "Cross-country back-to-back", "bet": "spread", "idea": "fatigue",
          "rule": "Opponent on a back-to-back after 1,500+ miles of travel → bet against them"},
    105: {"name": "Both teams tired: under", "bet": "total", "idea": "fatigue",
          "rule": "Both teams on a back-to-back → bet the under"},
    106: {"name": "Bounce-back after blowout loss", "bet": "spread", "idea": "overreaction",
          "rule": "Team lost by 25+ last game → bet them"},
    107: {"name": "Fade the blowout winner", "bet": "spread", "idea": "overreaction",
          "rule": "Opponent won by 25+ last game and is favored → bet against them"},
    108: {"name": "Home favorite on a losing streak", "bet": "spread", "idea": "overreaction",
          "rule": "Home favorite on 3+ straight losses → bet them"},
    109: {"name": "Home dog vs a hot team", "bet": "spread", "idea": "overreaction",
          "rule": "Home underdog vs a team on 5+ straight wins → bet the home dog"},
    110: {"name": "Game 2 of a two-game set", "bet": "spread", "idea": "overreaction",
          "rule": "Same teams, same building, within 3 days → bet the game-1 loser"},
    111: {"name": "Heavy favorite over, no filters", "bet": "total", "idea": "mismatch",
          "rule": "Favorite by 10+, total 225+ → bet the over (control test for System 4)"},
    112: {"name": "Big rested favorite vs tired dog", "bet": "spread", "idea": "mismatch",
          "rule": "Favorite by 8+ with rest vs dog on a back-to-back → bet the favorite"},
}


# My top picks among the test systems — shown as FAV on the board.
FAVORITES = {101, 102, 103, 110, 112}


# Early-season systems: only run in the first 2-3 weeks, while books are still pricing
# teams off last season and preseason guesses. Ids 201-207 show as E1-E7.
EARLY_SYSTEMS = {
    201: {"name": "Season-opener under", "bet": "total", "window": "both teams' first game",
          "rule": "Both teams playing their first game of the season → bet the under"},
    202: {"name": "Early home underdog", "bet": "spread", "window": "first 2 weeks",
          "rule": "Home underdog of 7 or less in the first 2 weeks → bet the home dog"},
    203: {"name": "Fade early big favorite", "bet": "spread", "window": "first 2 weeks",
          "rule": "Favorite of 10+ in the first 2 weeks → bet the underdog"},
    204: {"name": "Early blowout bounce-back", "bet": "spread", "window": "first 3 weeks",
          "rule": "Lost by 15+ last game, first 3 weeks → bet them"},
    205: {"name": "Fade early blowout winner", "bet": "spread", "window": "first 3 weeks",
          "rule": "Won by 15+ last game and favored, first 3 weeks → bet against them"},
    206: {"name": "Back the winless team", "bet": "spread", "window": "first 3 weeks",
          "rule": "Team is 0-3 or worse, first 3 weeks → bet them"},
    207: {"name": "Fade the unbeaten favorite", "bet": "spread", "window": "first 3 weeks",
          "rule": "Team is 3-0 or better and favored, first 3 weeks → bet against them"},
}


def label(system: int) -> str:
    if system >= 200:
        return f"E{system - 200}"
    return f"T{system - 100}" if system >= 100 else f"S{system}"


def group(system: int) -> str:
    """OG = the 4 TrendsCenter systems, FAV = favored test systems, TEST = the rest,
    EARLY = early-season systems."""
    if system >= 200:
        return "EARLY"
    if system < 100:
        return "OG"
    return "FAV" if system in FAVORITES else "TEST"


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
            if self.line is None:
                return f"{self.side} (no total yet)"
            return f"{self.side} {self.line:g}"
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


def evaluate_tests(game: Game, home: TeamState, away: TeamState,
                   home_spread: float | None, total: float | None) -> list[Pick]:
    """The 12 forward-test systems. Same shape as evaluate()."""
    picks: list[Pick] = []
    sides = [
        (game.home, home, away, True, home_spread),
        (game.away, away, home, False, None if home_spread is None else -home_spread),
    ]
    for team, t, o, is_home, spread in sides:
        og = o.last_game

        # T1 double-OT hangover (no line needed)
        if o.days_rest == 0 and og and (og.periods or 0) >= 6:
            picks.append(Pick(101, game.id, "spread", team, spread, [
                f"{o.team} played {og.periods - 4} overtimes last night: {og.score_line()}",
                f"{o.team} is {_rest(o)}"]))

        # T2 opponent on 3rd game in 4 nights, we're rested 2+ days
        if o.days_rest == 0 and o.games_last3 >= 2 and t.days_rest is not None and t.days_rest >= 2:
            picks.append(Pick(102, game.id, "spread", team, spread, [
                f"{o.team} is playing its 3rd game in 4 nights",
                f"{team} has had {t.days_rest} days off"]))

        # T3 back-to-back at altitude
        if is_home and team in ("DEN", "UTA") and o.days_rest == 0:
            picks.append(Pick(103, game.id, "spread", team, spread, [
                f"{o.team} is on a back-to-back and has to play at altitude in {team}"]))

        # T4 cross-country back-to-back
        if o.days_rest == 0 and og:
            miles = miles_between(og.home, game.home)
            if miles >= 1500:
                picks.append(Pick(104, game.id, "spread", team, spread, [
                    f"{o.team} played at {og.home} last night and travels {miles:,.0f} miles to {game.home}"]))

        # T6 bounce-back after a 25+ point loss (no line needed)
        if t.last_margin is not None and t.last_margin <= -25:
            picks.append(Pick(106, game.id, "spread", team, spread, [
                f"{team} lost by {-t.last_margin} last game: {t.last_game.score_line()}"]))

        # T7 fade the 25+ point winner when they're favored
        if o.last_margin is not None and o.last_margin >= 25 and spread is not None and spread > 0:
            picks.append(Pick(107, game.id, "spread", team, spread, [
                f"{o.team} won by {o.last_margin} last game: {og.score_line()}",
                f"{o.team} is favored by {spread:g} tonight"]))

        # T8 home favorite on 3+ straight losses
        if is_home and spread is not None and spread < 0 and t.lose_streak >= 3:
            picks.append(Pick(108, game.id, "spread", team, spread, [
                f"{team} is home and favored ({spread:+g}) despite losing {t.lose_streak} straight"]))

        # T9 home underdog vs a team on 5+ straight wins
        if is_home and spread is not None and spread > 0 and o.win_streak >= 5:
            picks.append(Pick(109, game.id, "spread", team, spread, [
                f"{team} is a home underdog ({spread:+g})",
                f"{o.team} has won {o.win_streak} straight"]))

        # T10 game 2 of a two-game set: bet the game-1 loser
        tg = t.last_game
        if (tg and t.last_opponent == o.team and tg.home == game.home
                and t.days_rest is not None and t.days_rest <= 2 and t.last_won is False):
            picks.append(Pick(110, game.id, "spread", team, spread, [
                f"Same teams, same building {t.days_rest + 1} day(s) ago: {tg.score_line()}",
                f"{team} lost game 1"]))

        # T11 heavy favorite over without System 4's last-game filters
        if spread is not None and spread <= -10 and total is not None and total >= 225:
            picks.append(Pick(111, game.id, "total", "OVER", total, [
                f"{team} is favored by {abs(spread):g}", f"Total is {total:g}"]))

        # T12 big rested favorite vs a tired underdog
        if (spread is not None and spread <= -8 and t.days_rest is not None and t.days_rest >= 1
                and o.days_rest == 0):
            picks.append(Pick(112, game.id, "spread", team, spread, [
                f"{team} is favored by {abs(spread):g} and has {_rest(t)}",
                f"{o.team} is {_rest(o)}"]))

    # T5 both teams tired → under (checked once per game)
    if home.days_rest == 0 and away.days_rest == 0:
        picks.append(Pick(105, game.id, "total", "UNDER", total, [
            f"{game.away} and {game.home} are both on the second night of a back-to-back"]))
    return picks


def evaluate_early(game: Game, home: TeamState, away: TeamState,
                   home_spread: float | None, total: float | None, season_day: int) -> list[Pick]:
    """The 7 early-season systems. season_day = days since opening night (0 = opening night)."""
    picks: list[Pick] = []
    if season_day > 20:
        return picks
    sides = [
        (game.home, home, away, True, home_spread),
        (game.away, away, home, False, None if home_spread is None else -home_spread),
    ]
    for team, t, o, is_home, spread in sides:
        # E2 early home underdog (7 or less)
        if season_day <= 13 and is_home and spread is not None and 0 < spread <= 7:
            picks.append(Pick(202, game.id, "spread", team, spread, [
                f"{team} is a home underdog ({spread:+g}) in the first 2 weeks",
                "Early lines lean on last season and preseason views"]))

        # E3 fade the early big favorite
        if season_day <= 13 and spread is not None and spread >= 10:
            picks.append(Pick(203, game.id, "spread", team, spread, [
                f"{o.team} is favored by {spread:g} in the first 2 weeks",
                "Rotations and starters' minutes are still settling early"]))

        # E4 early blowout bounce-back (15+)
        if t.last_margin is not None and t.last_margin <= -15:
            picks.append(Pick(204, game.id, "spread", team, spread, [
                f"{team} lost by {-t.last_margin} last game: {t.last_game.score_line()}",
                f"Only {t.games} game(s) into the season"]))

        # E5 fade the early blowout winner when favored
        if o.last_margin is not None and o.last_margin >= 15 and spread is not None and spread > 0:
            picks.append(Pick(205, game.id, "spread", team, spread, [
                f"{o.team} won by {o.last_margin} last game: {o.last_game.score_line()}",
                f"{o.team} is favored by {spread:g}, only {o.games} game(s) in"]))

        # E6 back the winless team (0-3 or worse)
        if t.wins == 0 and t.losses >= 3:
            picks.append(Pick(206, game.id, "spread", team, spread, [
                f"{team} is {t.record} to start the season"]))

        # E7 fade the unbeaten favorite (3-0 or better)
        if o.losses == 0 and o.wins >= 3 and spread is not None and spread > 0:
            picks.append(Pick(207, game.id, "spread", team, spread, [
                f"{o.team} is {o.record} and favored by {spread:g}"]))

    # E1 season-opener under: both teams' first game (checked once per game)
    if home.games == 0 and away.games == 0:
        picks.append(Pick(201, game.id, "total", "UNDER", total, [
            f"First game of the season for both {game.away} and {game.home}"]))
    return picks


def grade(pick: Pick, game: Game) -> str | None:
    """W / L / P for a finished game, graded at the pick's line."""
    if not game.final or pick.line is None:
        return None
    if pick.bet == "total":
        pts = game.home_score + game.away_score
        diff = pts - pick.line if pick.side == "OVER" else pick.line - pts
    else:
        mine, theirs = ((game.home_score, game.away_score) if pick.side == game.home
                        else (game.away_score, game.home_score))
        diff = mine - theirs + pick.line
    return "P" if diff == 0 else ("W" if diff > 0 else "L")
