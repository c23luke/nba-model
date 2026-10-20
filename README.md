# NBA Systems Board

Watches every NBA game for the 4 TrendsCenter systems, checks lines every 15 minutes,
prices each bet on Kalshi, grades results, and shows it all on one page.

| # | System | Bet |
|---|---|---|
| 1 | Opponent won last night in OT, plays again today | Spread, against them |
| 2 | Road favorite, not on a B2B, lost 4+ straight, opponent's losing streak under 4 | Spread, on them |
| 3 | Home favorite over .500, opponent won 4+ straight and is on a B2B | Spread, on home team |
| 4 | Favorite by more than 9, total above 220, favorite won last, dog lost last | Over |

## Layout
- `engine/teams.py`  team codes across ESPN / Odds API / Kalshi
- `engine/state.py`  rest days, streaks, record, last game (from final scores)
- `engine/systems.py` the 4 rules + grading
- `engine/sources.py` ESPN, The Odds API, Kalshi
- `engine/store.py`  Supabase (or local `data/` folder when no keys)
- `engine/run.py`    one full pass
- `web/index.html`   the board (Vercel)
- `.github/workflows/run-model.yml` runs a pass every 15 min, 10am–2am ET
- `supabase/schema.sql` tables

## Setup (once)
1. Supabase → new project → SQL Editor → paste `supabase/schema.sql` → Run.
2. GitHub repo → Settings → Secrets → Actions: add `ODDS_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role key).
3. Actions tab → "Run NBA model" → Run workflow → tick **backfill** once.
4. Copy `web/config.example.js` to `web/config.js`, fill in the URL and the **anon** key.
5. Vercel → import the repo → Root Directory: `web` → Deploy.

## Run locally
    python -m engine.run --backfill        # writes ./data/board.json
    python -m pytest -q                    # 26 tests
