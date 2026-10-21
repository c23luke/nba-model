# place-bets

Places the model's bets on Kalshi (and later Polymarket US) with Caden's own keys. Runs every minute (pg_cron `nba-place-bets`).

- Logic: `core.ts` · entry: `index.ts` · tests: `core_test.ts` (`deno test core_test.ts`)
- Tables: `bet_settings` (one row — the switches), `bet_orders` (every attempt), `bet_log` (what happened), order columns on `bet_feed`
- SQL: `supabase/migrations/20261020_bet_placer.sql`, `20261020_bet_placer_to_win.sql`, `20261020_bet_placer_cron.sql`
- Secrets (Edge Functions → Secrets): `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`, `KALSHI_DEMO_KEY_ID`, `KALSHI_DEMO_PRIVATE_KEY`, `POLYMARKET_KEY_ID`, `POLYMARKET_SECRET_KEY`
- Deploy: dashboard → Edge Functions → place-bets → paste `one-file-index.ts.txt` as the single `index.ts` (the dashboard editor didn't pick up a second file); "Verify JWT" OFF (the function checks its own run token). Regenerate the one-file version whenever core.ts/index.ts change.

Default is a dry run: `live_betting_on = false`, `kalshi_env = 'demo'`.

Sizing: every bet is sized to win `to_win_dollars` ($20) after the fee, whatever the price (set it to null to use `stake_dollars` instead). Limits: $50 per game, $100 daily loss cap.
