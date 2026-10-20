-- Order placer: settings (OFF by default), every order attempt, a run log, and order results on bet_feed.
-- All three new tables are private: RLS on, no policies, so only the service role (the function) can touch them.

create table if not exists public.bet_settings (
  id int primary key default 1 check (id = 1),
  live_betting_on boolean not null default false,          -- Caden flips this. The loss cap can flip it back off.
  kalshi_env text not null default 'demo' check (kalshi_env in ('demo', 'prod')),
  venues text[] not null default '{kalshi}',               -- kalshi, polymarket_us
  stake_dollars numeric not null default 5,
  daily_loss_cap numeric not null default 25,
  max_open_bets int not null default 6,
  max_dollars_per_game numeric not null default 10,
  min_ev numeric not null default 0.02,                    -- expected return needed after fees (0.02 = 2%)
  max_feed_age_minutes int not null default 20,            -- ignore the feed if the model hasn't run lately
  run_token uuid not null default gen_random_uuid(),       -- only the cron job knows it
  disabled_reason text,
  last_heartbeat timestamptz,
  updated_at timestamptz not null default now()
);
insert into public.bet_settings (id) values (1) on conflict (id) do nothing;
alter table public.bet_settings enable row level security;

create table if not exists public.bet_orders (
  id uuid primary key default gen_random_uuid(),           -- also the Kalshi client_order_id
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  mode text not null check (mode in ('dry_run', 'live')),
  env text, venue text not null, market text not null, order_side text not null,
  bet_key text not null, game_id text, tip_utc timestamptz, pick text, system text, contract text, line numeric,
  model_price numeric, ask_at_check numeric, limit_price numeric, count int, stake numeric, est_fee numeric, ev numeric,
  status text not null check (status in ('dry_run', 'pending', 'filled', 'partial', 'unfilled', 'error')),
  reason text, order_id text, fill_count numeric, fill_cost numeric, fees numeric, response jsonb,
  seen_count int not null default 1
);
-- never the same market twice, never the same bet twice (an errored order also blocks: no blind retries)
create unique index if not exists bet_orders_one_per_market on public.bet_orders (venue, market)
  where mode = 'live' and status in ('pending', 'filled', 'partial', 'error');
create unique index if not exists bet_orders_one_per_bet on public.bet_orders (bet_key)
  where mode = 'live' and status in ('pending', 'filled', 'partial', 'error');
create unique index if not exists bet_orders_one_dry_per_market on public.bet_orders (venue, market, bet_key)
  where mode = 'dry_run';
create index if not exists bet_orders_created on public.bet_orders (created_at);
alter table public.bet_orders enable row level security;

create table if not exists public.bet_log (
  id bigserial primary key,
  ts timestamptz not null default now(),
  level text not null,
  message text not null,
  data jsonb
);
create index if not exists bet_log_ts on public.bet_log (ts desc);
alter table public.bet_log enable row level security;

alter table public.bet_feed
  add column if not exists order_status text,
  add column if not exists order_venue text,
  add column if not exists order_id text,
  add column if not exists order_fill_count numeric,
  add column if not exists order_fill_cost numeric,
  add column if not exists order_placed_at timestamptz;

select 'bet placer tables ready' as ok;
