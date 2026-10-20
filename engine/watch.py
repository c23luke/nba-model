"""The watcher: checks every minute, reruns the model the moment anything changes, pings your phone.

Runs ~55 minutes per launch (Supabase starts it every hour, 10am-2am ET):
  every 60 s   ESPN injury report (any status change on any team)
               Kalshi spread / total events (a new game's lines just listed)
  on a change  rerun the model right away
  every 5 min  rerun anyway (lines move without news)
After every run, any NEW bet in an alert group (OG, FAV) is pushed to your phone via ntfy with the
pick, the best Kalshi contract, the most to pay for it, and a link. Each bet alerts once.
Bets are never placed automatically — the alert gets you there, you place it.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone

from . import run as runner
from .sources import get_json
from .store import get_store

INJURIES = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
KALSHI_EVENTS = "https://api.elections.kalshi.com/trade-api/v2/events?series_ticker={}&status=open&limit=200"
CHECK_EVERY = 60
RERUN_EVERY = 300
RUN_FOR = 55 * 60
ALERT_GROUPS = {"OG", "FAV"}
BOARD_URL = "https://nba-model-two.vercel.app/"


def injury_fingerprint() -> tuple[str, list[str]]:
    js = get_json(INJURIES)
    rows = []
    for team in js.get("injuries", []):
        for inj in team.get("injuries", []):
            a = inj.get("athlete") or {}
            rows.append(f"{(a.get('team') or {}).get('abbreviation') or team.get('displayName')}|"
                        f"{a.get('displayName')}|{inj.get('status')}")
    rows.sort()
    return hashlib.sha1("\n".join(rows).encode()).hexdigest(), rows


def kalshi_fingerprint() -> tuple[str, list[str]]:
    tickers = []
    for series in ("KXNBASPREAD", "KXNBATOTAL"):
        js = get_json(KALSHI_EVENTS.format(series))
        tickers += [e["event_ticker"] for e in js.get("events", [])]
    tickers.sort()
    return hashlib.sha1("\n".join(tickers).encode()).hexdigest(), tickers


def kalshi_fee(p: float) -> float:
    return math.ceil(0.07 * p * (1 - p) * 100) / 100


def max_price(win: float) -> float | None:
    """Highest Kalshi ask (dollars) where the bet still has value after the fee, given a win rate."""
    best = None
    for c in range(1, 100):
        p = c / 100
        if p + kalshi_fee(p) <= win:
            best = p
    return best


def win_rate(pick: dict, board: dict) -> float | None:
    if pick["system"] < 100:
        rec = board["systems"].get(pick["system"]) or board["systems"].get(str(pick["system"])) or {}
        return rec.get("card_win_rate")
    for g in board.get("slate", []):
        c = ((g.get("personnel") or {}).get("case") or {})
        if g["game_id"] == pick["game_id"] and c.get("side") == pick["side"]:
            return c.get("win_est")
    return None


def message(pick: dict, board: dict) -> tuple[str, str, str]:
    k = pick.get("kalshi") or {}
    win = win_rate(pick, board)
    cap = max_price(win) if win else None
    title = f"BET: {pick['label']} — {pick['away']} @ {pick['home']}"
    lines = [f"{pick['tag']} ({pick['group']})"]
    if k.get("price") is not None:
        lines.append(f"Kalshi: {k['contract']} at {round(k['price'] * 100)}¢")
    if cap:
        lines.append(f"Pay up to {round(cap * 100)}¢ on Kalshi incl. fee (expected win rate {win:.1%})")
    lines += pick.get("evidence", [])[:2]
    return title, "\n".join(lines), k.get("url") or BOARD_URL


def push(topic: str, title: str, body: str, click: str) -> None:
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), method="POST",
                                 headers={"Title": title.encode("ascii", "ignore").decode(), "Click": click,
                                          "Tags": "basketball", "Priority": "high"})
    urllib.request.urlopen(req, timeout=15).read()


def alert_new(board: dict, store, topic: str | None, log) -> int:
    live = [p for p in board.get("bets", []) + board.get("tests", []) + board.get("totals", [])
            if p.get("group") in ALERT_GROUPS and p.get("line") is not None
            and not (p.get("meta") or {}).get("alerted")]
    sent = []
    for p in live:
        title, body, click = message(p, board)
        if topic:
            try:
                push(topic, title, body, click)
            except Exception as e:
                log(f"alert failed for {p['label']}: {e}")
                continue
        log(f"ALERT {title} | {body.splitlines()[0]}")
        sent.append({**{k: v for k, v in p.items() if k not in ("tag", "group")},
                     "meta": {**(p.get("meta") or {}), "alerted": datetime.now(timezone.utc).isoformat()}})
    if sent:
        store.save_picks(sent)
    return len(sent)


def main():
    store = get_store()
    topic = "".join((os.environ.get("NTFY_TOPIC") or "").split()) or None
    if not topic:
        try:
            topic = store.get_config("ntfy_topic")
        except Exception as e:
            print(f"no alert channel: {e}")
    log = lambda m: print(f"{datetime.now(timezone.utc):%H:%M:%S} {m}", flush=True)
    end = time.time() + RUN_FOR
    last_fp, last_run = None, 0.0
    while time.time() < end:
        why = None
        try:
            fp_i, _ = injury_fingerprint()
        except Exception as e:
            fp_i = last_fp[0] if last_fp else None
            log(f"injury check failed: {e}")
        try:
            fp_k, _ = kalshi_fingerprint()
        except Exception as e:
            fp_k = last_fp[1] if last_fp else None
            log(f"kalshi check failed: {e}")
        fp = (fp_i, fp_k)
        if last_fp is None:
            why = "first run"
        elif fp[0] != last_fp[0]:
            why = "injury report changed"
        elif fp[1] != last_fp[1]:
            why = "new Kalshi lines listed"
        elif time.time() - last_run >= RERUN_EVERY:
            why = "5-minute refresh"
        last_fp = fp
        if why:
            try:
                board = runner.run(store=store)
                n = alert_new(board, store, topic, log)
                log(f"model run ({why}): {len(board['bets'])} main bets, "
                    f"{sum(1 for p in board['tests'] if p['group'] == 'FAV')} FAV, {n} new alerts")
            except Exception as e:
                log(f"model run failed: {e}")
            last_run = time.time()
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()
