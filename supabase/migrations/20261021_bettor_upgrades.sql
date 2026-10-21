-- 2026-10-21: resting limit orders, ProphetX token cache, test-only sites.

-- resting = a good-till-canceled order waiting in the book (counts as active: blocks a second order)
alter table public.bet_orders drop constraint if exists bet_orders_status_check;
alter table public.bet_orders add constraint bet_orders_status_check
  check (status in ('dry_run', 'pending', 'filled', 'partial', 'unfilled', 'error', 'resting'));
drop index if exists bet_orders_one_per_market;
drop index if exists bet_orders_one_per_bet;
create unique index bet_orders_one_per_market on public.bet_orders (venue, market)
  where mode = 'live' and status in ('pending', 'filled', 'partial', 'error', 'resting');
create unique index bet_orders_one_per_bet on public.bet_orders (bet_key)
  where mode = 'live' and status in ('pending', 'filled', 'partial', 'error', 'resting');

-- small private key/value store for the order placer (ProphetX login token, so it isn't re-logging in every minute)
create table if not exists public.bet_state (
  key text primary key,
  value jsonb,
  updated_at timestamptz not null default now()
);
alter table public.bet_state enable row level security;     -- no policies: service role only

-- sites that only log "would have placed" (never place), even while live betting is on
alter table public.bet_settings add column if not exists watch_venues text[] not null default '{}';
