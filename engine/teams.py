"""One code per team, and how every data source spells it.

Canonical code = Kalshi's 3-letter code (ATL, BKN, GSW, NOP, NYK, SAS, UTA, WAS ...).
"""

TEAMS = {
    # code: (full name, [other spellings used by ESPN / The Odds API])
    "ATL": ("Atlanta Hawks", []),
    "BOS": ("Boston Celtics", []),
    "BKN": ("Brooklyn Nets", []),
    "CHA": ("Charlotte Hornets", []),
    "CHI": ("Chicago Bulls", []),
    "CLE": ("Cleveland Cavaliers", []),
    "DAL": ("Dallas Mavericks", []),
    "DEN": ("Denver Nuggets", []),
    "DET": ("Detroit Pistons", []),
    "GSW": ("Golden State Warriors", ["GS"]),
    "HOU": ("Houston Rockets", []),
    "IND": ("Indiana Pacers", []),
    "LAC": ("Los Angeles Clippers", ["LA Clippers"]),
    "LAL": ("Los Angeles Lakers", ["LA Lakers"]),
    "MEM": ("Memphis Grizzlies", []),
    "MIA": ("Miami Heat", []),
    "MIL": ("Milwaukee Bucks", []),
    "MIN": ("Minnesota Timberwolves", []),
    "NOP": ("New Orleans Pelicans", ["NO"]),
    "NYK": ("New York Knicks", ["NY"]),
    "OKC": ("Oklahoma City Thunder", []),
    "ORL": ("Orlando Magic", []),
    "PHI": ("Philadelphia 76ers", []),
    "PHX": ("Phoenix Suns", []),
    "POR": ("Portland Trail Blazers", []),
    "SAC": ("Sacramento Kings", []),
    "SAS": ("San Antonio Spurs", ["SA"]),
    "TOR": ("Toronto Raptors", []),
    "UTA": ("Utah Jazz", ["UTAH"]),
    "WAS": ("Washington Wizards", ["WSH"]),
}

_LOOKUP = {}
for code, (name, alts) in TEAMS.items():
    for key in [code, name, *alts]:
        _LOOKUP[key.upper()] = code


def code(any_spelling: str) -> str:
    """Turn any source's team name/abbreviation into our code. Raises if unknown."""
    key = (any_spelling or "").strip().upper()
    if key not in _LOOKUP:
        raise KeyError(f"Unknown team spelling: {any_spelling!r}")
    return _LOOKUP[key]


def name(team_code: str) -> str:
    return TEAMS[team_code][0]
