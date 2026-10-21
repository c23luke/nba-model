-- Every bet sized to win the same amount (Caden: "to win $20 on each bet"), and limits that fit that size.
alter table public.bet_settings add column if not exists to_win_dollars numeric default 20;
update public.bet_settings
   set to_win_dollars = 20,
       max_dollars_per_game = 50,     -- one $20-to-win bet risks ~$20 at 50c, ~$47 at 70c
       daily_loss_cap = 100,          -- about 5 losing bets in a day, then live betting switches itself off
       updated_at = now()
 where id = 1;
select to_win_dollars, max_dollars_per_game, daily_loss_cap, live_betting_on, kalshi_env from public.bet_settings;

-- Per-bet size written by the model: Low-confidence bets win $10, everything else $20.
alter table public.bet_feed add column if not exists confidence text, add column if not exists to_win numeric;

-- BetOpenly support (applied 2026-10-20): model numbers per feed row, bet/side per order.
alter table public.bet_feed add column if not exists model jsonb;
alter table public.bet_orders add column if not exists bet text, add column if not exists side text;
