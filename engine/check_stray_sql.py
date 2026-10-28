"""Did the Exchange Scanner's SQL land in this (NBA) project? Lists which of its tables/views exist here.
Run: python -m engine.check_stray_sql"""
from .store import get_store

NAMES = ["settings", "dfs_runs", "dfs_picks", "real_bets", "news_status", "news_polls", "news_events", "news_takes",
         "news_lag", "news_takes_graded", "news_summary", "news_lag_summary", "pub_sources", "pub_runs", "pub_takes",
         "pub_takes_graded", "pub_summary", "wx_fast_state", "wx_fast_takes", "wx_fast_graded", "wx_fast_summary",
         "lip_model_unsettled", "weather_lab", "dfs_top_picks"]


def main():
    st = get_store()
    for n in NAMES:
        try:
            rows = st._req("GET", f"/{n}?select=*&limit=3")
            extra = ""
            if n == "settings":
                extra = " | dfs_window_hours: " + str(st._req("GET", "/settings?key=eq.dfs_window_hours&select=key,value") or "none")
            print(f"EXISTS  {n}: {len(rows or [])} sample rows{extra}")
        except Exception as e:
            print(f"absent  {n}: {str(e)[:120]}")
    print("bet_settings still:", {k: v for k, v in ((st._req('GET', '/bet_settings?select=*') or [{}])[0]).items()
                                  if k in ('live_betting_on', 'min_ev', 'to_win_dollars', 'venues', 'max_open_bets')})


if __name__ == "__main__":
    main()
