-- every official injury-report status the model sees (to measure how often Questionable/Doubtful players play)
create table if not exists public.injury_log (
  id text primary key, game_date date not null, team text not null, player text not null, player_key text not null,
  status text not null, reason text, first_seen timestamptz not null default now(), last_seen timestamptz not null default now());
alter table public.injury_log enable row level security;
