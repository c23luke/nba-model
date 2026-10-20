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


# Arena locations (lat, lon) — used to work out travel distance between games.
ARENAS = {
    "ATL": (33.757, -84.396), "BOS": (42.366, -71.062), "BKN": (40.683, -73.975),
    "CHA": (35.225, -80.839), "CHI": (41.881, -87.674), "CLE": (41.497, -81.688),
    "DAL": (32.790, -96.810), "DEN": (39.749, -105.008), "DET": (42.341, -83.055),
    "GSW": (37.768, -122.388), "HOU": (29.751, -95.362), "IND": (39.764, -86.156),
    "LAC": (33.945, -118.342), "LAL": (34.043, -118.267), "MEM": (35.138, -90.051),
    "MIA": (25.781, -80.188), "MIL": (43.045, -87.917), "MIN": (44.979, -93.276),
    "NOP": (29.949, -90.082), "NYK": (40.751, -73.994), "OKC": (35.463, -97.515),
    "ORL": (28.539, -81.384), "PHI": (39.901, -75.172), "PHX": (33.446, -112.071),
    "POR": (45.532, -122.667), "SAC": (38.580, -121.500), "SAS": (29.427, -98.438),
    "TOR": (43.643, -79.379), "UTA": (40.768, -111.901), "WAS": (38.898, -77.021),
}


def miles_between(home_a: str, home_b: str) -> float:
    """Great-circle miles between two teams' arenas."""
    from math import radians, sin, cos, asin, sqrt
    (la1, lo1), (la2, lo2) = ARENAS[home_a], ARENAS[home_b]
    dla, dlo = radians(la2 - la1), radians(lo2 - lo1)
    a = sin(dla / 2) ** 2 + cos(radians(la1)) * cos(radians(la2)) * sin(dlo / 2) ** 2
    return 3958.8 * 2 * asin(sqrt(a))
