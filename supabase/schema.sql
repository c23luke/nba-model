-- Run once in Supabase → SQL Editor.

create table if not exists games (
  id            text primary key,          -- ESPN game id
  game_date     date not null,             -- US Eastern date
  tip_utc       text,
  away          text not null,
  home          text not null,
  away_score    int,
  home_score    int,
  periods       int,                       -- 4 regulation, 5+ overtime
  final         boolean default false,
  home_spread   numeric,                   -- negative = home favored
  total         numeric,
  line_source   text,
  line_books    int,
  line_updated  text
);

create table if not exists picks (
  key            text primary key,         -- <game>-S<system>-<side>
  game_id        text references games(id),
  game_date      date,
  tip_utc        text,
  away           text,
  home           text,
  system         int,
  bet            text,                     -- spread | total
  side           text,                     -- team code or OVER
  label          text,
  line           numeric,                  -- current line (locks at tip; graded at this)
  first_line     numeric,                  -- line when it first fired
  first_seen     text,
  last_checked   text,
  active         boolean,
  dropped_reason text,
  evidence       jsonb,
  kalshi         jsonb,
  result         text,                     -- W / L / P
  final_score    text,
  graded_at      text
);

create table if not exists board (
  id    int primary key,
  data  jsonb
);

-- The website reads with the public anon key: read-only, and only the board.
alter table games enable row level security;
alter table picks enable row level security;
alter table board enable row level security;
drop policy if exists "public read board" on board;
create policy "public read board" on board for select using (true);
