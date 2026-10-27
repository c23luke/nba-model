-- every consensus line and exchange price the model sees, each run (to measure how long Kalshi/ProphetX
-- lag behind the books when a line moves — the "stale price" edge)
create table if not exists public.price_log (
  id bigserial primary key, ts timestamptz not null default now(), game_id text not null, game_date date,
  away text, home text, home_spread numeric, total numeric, books int, quotes jsonb);
create index if not exists price_log_game on public.price_log (game_id, ts);
alter table public.price_log enable row level security;
