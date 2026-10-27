-- Let a partly-filled bet be topped up: 'partial' no longer blocks a second order on the same bet or
-- market. 'pending' still does, so two runs can't place the same top-up twice; the bettor caps the
-- top-up at what's still missing from the bet's to-win target.
drop index if exists public.bet_orders_one_per_market;
create unique index bet_orders_one_per_market on public.bet_orders (venue, market)
  where mode = 'live' and status in ('pending', 'filled', 'error', 'resting');
drop index if exists public.bet_orders_one_per_bet;
create unique index bet_orders_one_per_bet on public.bet_orders (bet_key)
  where mode = 'live' and status in ('pending', 'filled', 'error', 'resting');
