-- Run the order placer every minute. The run token comes from the private settings row, so it never
-- appears in code or in this file, and a caller without it gets 403.
select cron.unschedule('nba-place-bets') where exists (select 1 from cron.job where jobname = 'nba-place-bets');
select cron.schedule('nba-place-bets', '* * * * *', $$
  select net.http_post(
    url := 'https://idudowjldcepblhcdbed.supabase.co/functions/v1/place-bets',
    headers := jsonb_build_object('Content-Type', 'application/json',
                                  'x-run-token', (select run_token::text from public.bet_settings where id = 1)),
    body := '{}'::jsonb,
    timeout_milliseconds := 55000);
$$);
