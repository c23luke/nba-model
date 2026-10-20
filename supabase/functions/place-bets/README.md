# place-bets

Places the model's bets on Kalshi (and later Polymarket US) with Caden's own keys. Runs every minute (pg_cron `nba-place-bets`).

- Logic: `core.ts` · entry: `index.ts` · tests: `core_test.ts` (`deno test core_test.ts`)
- Tables: `bet_settings` (one row — the switches), `bet_orders` (every attempt), `bet_log` (what happened), order columns on `bet_feed`
- SQL: `supabase/migrations/20261020_bet_placer.sql`, `supabase/migrations/20261020_bet_placer_cron.sql`
- Secrets (Edge Functions → Secrets): `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`, `KALSHI_DEMO_KEY_ID`, `KALSHI_DEMO_PRIVATE_KEY`, `POLYMARKET_KEY_ID`, `POLYMARKET_SECRET_KEY`
- Deploy: dashboard → Edge Functions → place-bets → paste `index.ts` and `core.ts`; "Verify JWT" OFF (the function checks its own run token)

Default is a dry run: `live_betting_on = false`, `kalshi_env = 'demo'`.
