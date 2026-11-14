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
    113: {"name": "Players model", "bet": "spread", "idea": "personnel",
          "rule": "The players model's line is 4+ pts off the market whether day-to-day players play or sit, the team isn't bottom-10, and no blind spots → bet that side"},
}


# My top picks among the test systems — shown as FAV on the board.
# Tracking only: never shown as a bet. Lets every variation be graded (e.g. the personnel
# side on every game, so we can see how it does at each gap size, waiting vs clean, blind or not).
SHADOW_SYSTEMS = {
    301: {"name": "Personnel side, every game", "bet": "spread", "idea": "tracking",
          "rule": "Whichever side the personnel line likes, every game, any gap. Graded so the "
                  "record can be split by gap size, day-to-day status and blind spots."},
    302: {"name": "Fade the team missing 2+ rotation players", "bet": "spread", "idea": "injuries (testing)",
          "rule": "A team is missing 2+ rotation players (20+ mpg), more than its opponent, at least one of them "
                  "played its last game → bet the opponent. 2 seasons vs the close: 249-199 (55.6%), both seasons "
                  "55-56% (engine/measure_cluster.py). Tracking only until it earns real money."},
    303: {"name": "Fade the team missing 2+ FRESH rotation players", "bet": "spread", "idea": "injuries (testing)",
          "rule": "Like X2, but at least 2 of the missing rotation players played the team's last game (fresh news; "
                  "long absences are already priced). 2 seasons vs the close: 142-108 (56.8%; 58.1% / 55.6%), at the "
                  "open 147-103 (engine/measure_cluster.py, Nov 11). Tracking only."},
    304: {"name": "Fade the team missing 2+ rotation players at different positions", "bet": "spread",
          "idea": "injuries (testing)",
          "rule": "Like X2 (1+ fresh), and the missing players are all at different positions (guard / wing / big): "
                  "the team can't just slide the next man in. 2 seasons vs the close: 139-103 (57.4%; 59.5% / 55.0%), "
                  "at the open 142-101 (engine/measure_cluster.py, Nov 11). Tracking only."},
    305: {"name": "Back the team that won its last game by 25+", "bet": "spread", "idea": "overreaction (testing)",
          "rule": "The market expects a letdown after a blowout win; it doesn't come. 2 seasons: 169-134 at the "
                  "open, 159-122 at the close, both seasons (engine/measure_ideas.py, Nov 11). Tracking only."},
    306: {"name": "Fade the team coming off an overtime game (early line)", "bet": "spread", "idea": "fatigue (testing)",
          "rule": "Its last game went to overtime: bet the opponent at the FIRST line. 2 seasons: 117-90 at the open, "
                  "only 105-95 at the close (engine/measure_ideas.py, Nov 11). Tracking only."},
    307: {"name": "Both teams shooting below their shot quality: over", "bet": "total", "idea": "shooting luck (testing)",
          "rule": "Both teams' field-goal points ran 2+ a game below what their shots were worth (shot locations, last "
                  "5 games). 2 seasons: 121-102 at the open, 114-98 at the close (engine/measure_ideas.py). Tracking only."},
    308: {"name": "Follow a 2+ point line move", "bet": "spread", "idea": "market (testing)",
          "rule": "The spread moved 2+ points from the first line we saw: bet the side it moved toward, at the price "
                  "after the move. 2 seasons at the close: 279-223 (55.6%), both seasons (engine/measure_ideas2.py). Tracking only."},
    309: {"name": "Home team with 2+ more days of rest", "bet": "spread", "idea": "rest (testing)",
          "rule": "Home team rested 2+ more days than the visitor -> home. 2 seasons: 66-41 at the open, 63-43 at the "
                  "close (engine/measure_ideas2.py). Tracking only."},
}

# Bets made at the first line and kept there: once one of these fires, it stays a bet even if the
# line moves (moving toward us IS the point — that's CLV) and it's graded at the line it fired at.
LOCK_ON_FIRE = {113}

# Found by the six-season search (engine/mine.py, 2020-21 to 2025-26, vs the closing line). Each won
# in at least 5 of 6 seasons, and the top of the search beat shuffled-results luck (totals: 11 systems
# with a 58%+ floor vs 1 by luck). Simple, logical versions picked, not the narrowest.
# win_est = halfway between 50% and the six-season rate: a search always flatters its winners.
TEST_SYSTEMS.update({
    121: {"win_est": 0.555, "name": "Late-season mismatch over", "bet": "total", "idea": "late season",
          "rule": "Last 3 weeks of the season, favorite by 10+ → over. 6 seasons: 194-124 (61.0%), every season up"},
    122: {"win_est": 0.56, "name": "Late-season low total over", "bet": "total", "idea": "late season",
          "rule": "Last 3 weeks, total in the lowest quarter of the season's totals → over. 149-91 (62.1%)"},
    123: {"win_est": 0.567, "name": "Post-All-Star mismatch, tired home team over", "bet": "total", "idea": "fatigue",
          "rule": "After the All-Star break, favorite by 10+, home team on its 4th game in 6 nights → over. 149-86 (63.4%)"},
    124: {"win_est": 0.595, "name": "Fade the OT winner on 4 games in 6 nights", "bet": "spread", "idea": "fatigue",
          "rule": "Team won its last game in overtime and is on its 4th game in 6 nights → bet against. 69-31 (69.0%)"},
    # engine/measure_moneyball.py (2026-10-27): last 21 days, teams at .350 or worse after 40+ games
    # covered 164-212 (43.6%) over 6 seasons vs the close; fading them won 4 of 6 seasons.
    # MONEYBALL (Caden's stack, 2026-10-27; engine/measure_moneyball_stack.py, opening line):
    #   2+ systems + players agree 3+: 29-11 (72.5%) — 2024-25 11-4, 2025-26 18-7
    #   the 4-6 slice Caden named: 13-4 (6-2, 7-2). Win estimate shrunk hard for 40 bets: 50% + 22.5 × 40/140.
    130: {"win_est": 0.564, "name": "MONEYBALL: 2+ systems + players model agrees 3+", "bet": "spread", "idea": "stack",
          "rule": "Two or more of our systems on the same side AND the players model likes that side by 3+ points "
                  "(either way day-to-day players go). 2 seasons at the open: 29-11 (72.5%), both seasons 72-73%. "
                  "Sized to win $40 (2 units)."},
    # STACK (Caden 2026-11-11 "lets bet anything stack 5+"; Nov 12 exactly 5 not bet; Nov 14 count each fact once).
    #   4+ separate facts known before the line moves, at the opening line: 136-75 (64.5%; 67.0% / 61.8%). No line-move
    #   fact (Caden Nov 14: bet opening lines, not after the market moves).
    #   3 or fewer separate facts (even with 6+ flags, like MIN Nov 14): not bet. Not yet tested live.
    131: {"win_est": 0.598, "name": "STACK: 4+ separate facts on one side", "bet": "spread", "idea": "stack",
          "rule": "4 or more SEPARATE reasons on the same side, each counted once: the players model 3+ (in every version "
                  "of tonight), card systems, a tired opponent (back-to-back / overtime / rest and the systems built on "
                  "them), injuries (X2-X4), a 25+ blowout win, the other team leaning on unknown players, shooting luck. "
                  "Only facts known before the line moves. 2 seasons at the opening line: 136-75 (64.5%). Every fact "
                  "is listed on the bet. Sized to win $40 (2 units)."},
    # SYS+X4 (Caden 2026-11-11: "its really good ... id still like to bet it"; engine/measure_stack_flags.py, close):
    #   a card system on the side fading a team missing 2+ rotation players at different positions: 42-18 (70.0%),
    #   2024-25 22-10, 2025-26 20-8. Bet WITHOUT needing the players model. Not yet tested live.
    132: {"win_est": 0.575, "name": "SYS+X4: a system + fading a team missing 2+ players at different positions", "bet": "spread",
          "idea": "stack", "rule": "A card system fires on a side AND the other team is missing 2+ rotation players at "
                  "different positions (1+ of them fresh). 2 seasons at the close: 42-18 (70.0%; 22-10 / 20-8). "
                  "No players-model read needed. Sized to win $20."},
    # three pairs Caden added Nov 11 ("add"), 1 unit each, no players-model read needed. 2 seasons at the close
    # (engine/measure_stack_flags.py). Best pairs out of 68 searched: expect a few points lower live.
    133: {"win_est": 0.575, "name": "X4+B2B: fade a team missing 2+ players at different positions, on a back-to-back",
          "bet": "spread", "idea": "stack", "rule": "X4 fires (the other team missing 2+ rotation players at different "
          "positions, 1+ fresh) AND that team is on a back-to-back and we aren't. 42-18 (70.0%; 23-9 / 19-9). $20."},
    134: {"win_est": 0.580, "name": "X2+B2B: fade a team missing 2+ players, on a back-to-back", "bet": "spread",
          "idea": "stack", "rule": "X2 fires (the other team missing 2+ rotation players, 1+ fresh) AND that team is on a "
          "back-to-back and we aren't. 62-31 (66.7%; 33-16 / 29-15). $20."},
    135: {"win_est": 0.578, "name": "MOVE+THIN: line moved 2+ our way against a team leaning on unknown players",
          "bet": "spread", "idea": "stack", "rule": "The spread moved 2+ points toward our side since the first line AND "
          "the other team gets 5+ points more of its minutes from players the model barely knows. 79-44 (64.2%; "
          "36-17 / 43-27). Forms late (needs the move). $20."},
    # five shot-quality pairs (Caden 2026-11-12: "we definitely need to bet these"), 1 unit each, no players-model
    # read needed except RIM+PM. engine/measure_stack2.py, 2 seasons at the close. Best of 111 pairs searched, and the
    # shot-quality cut-offs were set on both seasons: expect them a few points lower live.
    136: {"win_est": 0.575, "name": "RIM+PM: rim matchup + the players model 3+", "bet": "spread", "idea": "stack",
          "rule": "We take a top-30% share of our shots at the rim (last 10) AND they allow a top-30% share at the rim, "
          "AND the players model likes us by 3+. 36-14 (72.0%; 24-8 / 12-6). $20."},
    137: {"win_est": 0.575, "name": "SQ+X3: better by the shots + X3", "bet": "spread", "idea": "stack",
          "rule": "Our shot-quality margin (what our shots were worth minus what we allowed, last 10) beats theirs by "
          "6.8+ AND X3 fires (they're missing 2+ fresh rotation players). 29-12 (70.7%; 14-7 / 15-5). $20."},
    138: {"win_est": 0.575, "name": "UNLUCKY+X4: unlucky by the shots + X4", "bet": "spread", "idea": "stack",
          "rule": "Our real margins ran 7.2+ a game below our shot-quality margins (last 10) AND X4 fires. "
          "30-15 (66.7%; 18-9 / 12-6). $20."},
    139: {"win_est": 0.575, "name": "SQ+THIN: better by the shots + they lean on unknown players", "bet": "spread",
          "idea": "stack", "rule": "Better by the shots (6.8+) AND the other team gets 5+ points more of its minutes from "
          "players the model barely knows. 66-37 (64.1%; 35-15 / 31-22). $20."},
    140: {"win_est": 0.575, "name": "3HOT+MOVE: they've hit 3s way above their value + the line moved our way",
          "bet": "spread", "idea": "stack", "rule": "Their made 3s ran 4.7+ points a game above what their 3s were "
          "worth (last 5) AND the spread moved 1+ toward us. 91-58 (61.1%; 39-24 / 52-34). Forms late. $20."},
    125: {"win_est": 0.532, "name": "Fade the tanker, last 3 weeks", "bet": "spread", "idea": "late season",
          "rule": "Last 3 weeks of the season, opponent is .350 or worse after 40+ games (and we aren't) → bet us. "
                  "6 seasons: 212-164 (56.4%) vs the close"},
})

# Conservative expected win rates (halfway to 50% from the two-season replay) for the card/alerts
TEST_SYSTEMS[102]["win_est"] = 0.53       # T2: 55-43 (56.1%)
TEST_SYSTEMS[112]["win_est"] = 0.525      # T12: 86-70 (55.1%)

# FAV = held up when replayed on 2024-25 + 2025-26 (engine/backtest_og.py, graded vs the close):
#   T2 55-43 (56%, both seasons 56%), T12 86-70 (55%, both seasons 55%), T13 (opening-line test).
# T1 3-4, T3 13-14, T10 32-36 did not → moved to TEST (2026-10-20).
FAVORITES = {102, 112, 113, 121, 122, 123, 124, 125, *range(130, 141)}


# Early-season systems: only run in the first 2-3 weeks, while books are still pricing
# teams off last season and preseason guesses. Ids 201-207 show as E1-E7.
EARLY_SYSTEMS = {
    201: {"name": "Season-opener over", "bet": "total", "window": "both teams' first game",
          "rule": "Both teams playing their first game of the season → bet the OVER. Flipped 2026-10-20: "
                  "replayed on 2024-25 + 2025-26, opener unders went 6-22 vs the close (overs 22-6)"},
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
    208: {"name": "Early-season over", "bet": "total", "window": "first 2 weeks",
          "rule": "Every game in the first 2 weeks → over. Last 4 seasons 226-181 (55.5%) vs the close, "
                  "+1.6 to +2.5 pts a game each year; 2020-21 and 2021-22 went the other way (scoring fell)"},
}


MONEYBALL = 130
STACK = 131
SYS_X4 = 132
PAIRS = {133: "X4+B2B", 134: "X2+B2B", 135: "MOVE+THIN",
         # shot-quality pairs (Caden 2026-11-12), engine/measure_stack2.py
         136: "RIM+PM", 137: "SQ+X3", 138: "UNLUCKY+X4", 139: "SQ+THIN", 140: "3HOT+MOVE"}
COMBO_BETS = (MONEYBALL, STACK, SYS_X4, *PAIRS)       # bets built from other picks: never count as "a system"


def label(system: int) -> str:
    if system == MONEYBALL:
        return "MONEYBALL"
    if system == STACK:
        return "STACK"
    if system == SYS_X4:
        return "SYS+X4"
    if system in PAIRS:
        return PAIRS[system]
    if system >= 300:
        return f"X{system - 300}"
    if system >= 200:
        return f"E{system - 200}"
    return f"T{system - 100}" if system >= 100 else f"S{system}"


def group(system: int) -> str:
    """OG = the 4 TrendsCenter systems, FAV = favored test systems, TEST = the rest,
    EARLY = early-season systems."""
    if system >= 300:
        return "SHADOW"
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
    meta: dict = field(default_factory=dict)   # extra numbers kept for tracking (e.g. personnel gap)

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
             home_spread: float | None, total: float | None, tot_avg: float | None | str = "legacy") -> list[Pick]:
    """Run all 4 systems on one game. Spread systems are checked from both sides.
    tot_avg: this season's average closing total over games already played (S4's bar; None = not enough
    games yet, so no S4). "legacy" = the old fixed 220, kept only for old replays."""
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
        # The total bar was a fixed 220, set when 220 was a high total; by 2025-26, 90% of games were
        # above it. Now: above THIS season's average so far. MEASURED (engine/measure_walkforward.py):
        # 2024-26 picked and graded at the open: 95-74 (56.2%), 94-72 at the close (engine/measure_leak). The 106-67 once
        # quoted here chose games by the closing line, which the live model can't know.
        bar = 220.0 if tot_avg == "legacy" else tot_avg
        if (spread is not None and spread < -9.0 and total is not None and bar is not None and total > bar
                and t.last_won is True and o.last_won is False):
            picks.append(Pick(4, game.id, "total", "OVER", total, [
                f"{team} is favored by {abs(spread):g} (more than 9)",
                (f"Total is {total:g} (above 220)" if tot_avg == "legacy"
                 else f"Total is {total:g}, above this season's average of {bar:.1f}"),
                f"{team} won its last game: {t.last_game.score_line()}",
                f"{o.team} lost its last game: {o.last_game.score_line()}",
            ], {"bar": bar}))
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

    # E8 early-season over: every game in the first 2 weeks (checked once per game)
    if season_day < 14:
        picks.append(Pick(208, game.id, "total", "OVER", total, [
            "First 2 weeks of the season: books price totals off last season's scoring",
            "Last 4 seasons: early overs 226-181 (55.5%) vs the close"]))

    # E1 season-opener OVER: both teams' first game (checked once per game)
    if home.games == 0 and away.games == 0:
        picks.append(Pick(201, game.id, "total", "OVER", total, [
            f"First game of the season for both {game.away} and {game.home}",
            "Last two seasons, opener totals went over 22 of 28 times vs the closing number"]))
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


def personnel_call(view: dict | None, gap_to_fire: float = 3.0) -> dict:
    """Decide what the personnel line says, across every day-to-day version of tonight.
    now      → the gap is 3+ the same way whether the day-to-day players play or sit
    waiting  → the gap is 3+ only in some versions: hold, the 15-minute runs will catch the news
    none     → no edge in any version (or the model is blind on this game)"""
    if not view or view.get("gap") is None or view.get("blind") or view.get("bad_team"):
        return {"call": "none"}
    gaps = [s["gap"] for s in view.get("scenarios") or [] if s["gap"] is not None] or [view["gap"]]
    pos = [g for g in gaps if g >= gap_to_fire]
    neg = [g for g in gaps if g <= -gap_to_fire]
    if len(pos) == len(gaps) or len(neg) == len(gaps):
        side = "home" if pos else "away"
        if (view.get("thin") or {}).get("side") == side:
            return {"call": "none", "thin": True}     # leans on players the model barely knows (measured 41-54)
        return {"call": "now", "side": side, "worst_gap": min(gaps, key=abs)}
    thin = (view.get("thin") or {}).get("side")
    if pos and not neg:
        return {"call": "none", "thin": True} if thin == "home" else {"call": "waiting", "side": "home", "best_gap": max(pos)}
    if neg and not pos:
        return {"call": "none", "thin": True} if thin == "away" else {"call": "waiting", "side": "away", "best_gap": min(neg)}
    return {"call": "none"}


T13_GAP = 4.0   # MEASURED (engine/measure_moneyball_stack.py, 2 seasons at the open, live players model):
                # gap 3-4 went 131-116 (53.0%: 2024-25 62-65, 2025-26 69-51) — about break-even after the vig;
                # gap 4-6 went 164-120 (57.7%), up both seasons. A 3-4 gap is only bet as part of a MONEYBALL
                # stack (2+ systems agreeing) or an early combo.


def evaluate_personnel(game: Game, home_spread: float | None, view: dict | None,
                       gap_to_fire: float = T13_GAP, season_day: int = 0) -> list[Pick]:
    """T13: bet the side the personnel line likes when the gap is 4+ in every day-to-day version
    of tonight and the model isn't blind on the game."""
    if home_spread is None:
        return []
    c = personnel_call(view, gap_to_fire)
    if c["call"] != "now":
        return []
    side, line = (game.home, home_spread) if c["side"] == "home" else (game.away, -home_spread)
    meta = {"gap": abs(view["gap"]), "worst_gap": abs(c["worst_gap"]), "call": "now"}
    either = (f"Holds whether day-to-day players play or sit (smallest gap {c['worst_gap']:+.1f})"
              if view.get("waiting_on") else "No day-to-day players in either rotation")
    return [Pick(113, game.id, "spread", side, line, [
        f"Personnel fair line: {game.home} {view['fair']:+g} vs market {game.home} {home_spread:+g} (gap {view['gap']:+.1f})",
        f"Ratings from current players: {game.away} {view['away_rating']:+.1f}, {game.home} {view['home_rating']:+.1f} per 100",
        either,
    ], meta)]


def evaluate_personnel_shadow(game: Game, home_spread: float | None, view: dict | None) -> list[Pick]:
    """X1: the side the personnel line likes on every game (tracking only, never a bet)."""
    if home_spread is None or not view or not view.get("gap"):
        return []
    gap = view["gap"]
    home = gap > 0
    side, line = (game.home, home_spread) if home else (game.away, -home_spread)
    gaps = [s["gap"] for s in view.get("scenarios") or [] if s["gap"] is not None] or [gap]
    same = [abs(g) for g in gaps if (g > 0) == home]
    c = personnel_call(view)
    ev = [f"Personnel likes {side} by {abs(gap):.1f} vs the market"]
    th = view.get("thin")
    if th:
        ev.append(f"{th['team']} leans on players the model barely knows ({th['share']:.0%} of its minutes vs "
                  f"{th['other']:.0%}): the players model doesn't bet that side alone (41-54 in two seasons)")
    return [Pick(301, game.id, "spread", side, line, ev, {
        "gap": round(abs(gap), 1),
        "worst_gap": round(min(same), 1) if len(same) == len(gaps) else 0.0,   # 0 = versions disagree on side
        "call": "blind" if view.get("blind") else "bad_team" if view.get("bad_team") else
                "thin" if c.get("thin") else c["call"],
        "dtd": len(view.get("waiting_on") or []),
    })]


def evaluate_mined(game: Game, home: TeamState, away: TeamState, home_spread: float | None,
                   total: float | None, ctx: dict) -> list[Pick]:
    """T21-T24 from the six-season search. ctx: last21, post_asb, tot_low_cut, home_4in6, away_4in6."""
    picks: list[Pick] = []
    mismatch = home_spread is not None and abs(home_spread) >= 10
    if total is not None:
        if ctx.get("last21") and mismatch:
            picks.append(Pick(121, game.id, "total", "OVER", total, [
                "Last 3 weeks of the regular season", f"Favorite by {abs(home_spread):g} (10+)",
                "6 seasons: 194-124 (61.0%) vs the close"]))
        if ctx.get("last21") and ctx.get("tot_low_cut") is not None and total <= ctx["tot_low_cut"]:
            picks.append(Pick(122, game.id, "total", "OVER", total, [
                "Last 3 weeks of the regular season",
                f"Total {total:g} is in the lowest quarter of this season's totals (≤ {ctx['tot_low_cut']:g})",
                "6 seasons: 149-91 (62.1%) vs the close"]))
        if ctx.get("post_asb") and mismatch and ctx.get("home_4in6"):
            picks.append(Pick(123, game.id, "total", "OVER", total, [
                "After the All-Star break", f"Favorite by {abs(home_spread):g} (10+)",
                f"{game.home} is playing its 4th game in 6 nights", "6 seasons: 149-86 (63.4%) vs the close"]))
    for team, t, o, spread, o4 in ((game.home, home, away, home_spread, ctx.get("away_4in6")),
                                   (game.away, away, home, None if home_spread is None else -home_spread,
                                    ctx.get("home_4in6"))):
        if ctx.get("last21") and o.games >= 40 and o.win_pct is not None and o.win_pct <= 0.35 \
                and not (t.games >= 40 and t.win_pct is not None and t.win_pct <= 0.35):
            picks.append(Pick(125, game.id, "spread", team, spread, [
                "Last 3 weeks of the regular season", f"{o.team} is {o.wins}-{o.losses} ({o.win_pct:.3f}): tanking range",
                "6 seasons: teams at .350 or worse covered 164-212 in the last 3 weeks"]))
        if o4 and o.last_won and o.last_ot:
            picks.append(Pick(124, game.id, "spread", team, spread, [
                f"{o.team} won last game in overtime: {o.last_game.score_line()}",
                f"{o.team} is playing its 4th game in 6 nights", "6 seasons: 69-31 (69.0%) vs the close"]))
    return picks


def evaluate_moneyball(game: Game, picks: list[Pick], view: dict | None) -> list[Pick]:
    """MONEYBALL: 2+ distinct systems (any group, not the players model itself) on the same side of the
    spread, and the players model agreeing with that side by 3+ in every day-to-day version."""
    if not view or view.get("gap") is None or view.get("blind"):
        return []
    gaps = [s["gap"] for s in view.get("scenarios") or [] if s.get("gap") is not None] or [view["gap"]]
    out = []
    for side, sign in ((game.home, 1), (game.away, -1)):
        ps = [p for p in picks if p.bet == "spread" and p.side == side and p.line is not None
              and p.system < 300 and p.system not in (113, *COMBO_BETS)]
        systems = sorted({p.system for p in ps})
        worst = min(sign * g for g in gaps)
        if len(systems) >= 2 and worst >= 3:
            line = ps[0].line
            out.append(Pick(MONEYBALL, game.id, "spread", side, line, [
                "Systems on this side: " + ", ".join(label(s) for s in systems),
                f"Players model likes {side} by {worst:.1f}+ (whether day-to-day players play or sit)",
                "2 seasons at the open: 2+ systems + players model 3+ went 29-11 (72.5%)"],
                {"systems": [label(s) for s in systems], "gap": round(worst, 1)}))
    return out
