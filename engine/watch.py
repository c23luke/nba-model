"""The watcher: checks every minute, reruns the model the moment anything changes, pings your phone.

Runs ~55 minutes per launch (Supabase starts it every hour, 10am-2am ET):
  every 60 s   ESPN injury report (any status change on any team)
               Kalshi spread / total events (a new game's lines just listed)
  on a change  rerun the model right away
  every 5 min  rerun anyway (lines move without news)
After every run, any new BET or LIMIT on today's card (OG and FAV systems) is pushed to your phone via
ntfy: the best venue and price after line shopping, the most to pay on Kalshi, and a link. Each bet alerts
once, plus once more if a LIMIT turns into a BET.
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


from .pricing import kalshi_fee, max_price  # noqa: E402  (shared with the board's daily card)


def win_rate(pick: dict, board: dict) -> float | None:
    from .pricing import win_estimate
    return win_estimate(pick, board.get("slate", []))


def message(c: dict, pick: dict) -> tuple[str, str, str]:
    """Phone alert for one card row: where to bet, at what price, and the most to pay."""
    b = c.get("best")
    if c["verdict"] == "BET" and b:
        title = f"BET: {c['label']} — {c['away']} @ {c['home']} — {b['venue_name']} {b['price_txt']}"
    else:
        title = f"{c['verdict']}: {c['label']} — {c['away']} @ {c['home']}"
    lines = [f"{c['tag']} ({c['group']}) · expected win rate {c['win']:.1%}", c["why"]]
    if c.get("max") is not None:
        lines.append(f"Max price on Kalshi {round(c['max'] * 100)}¢ incl. fee"
                     + (f" ({c['contract']})" if c.get("contract") else ""))
    others = [q for q in c.get("shop", []) if q.get("mine") and q is not b and q != b][:3]
    if others:
        lines.append("Also: " + "; ".join(f"{q['venue_name']} {q['contract']} {q['price_txt']} ({q['ev']:+.1%})"
                                          for q in others))
    lines += pick.get("evidence", [])[:2]
    click = (b or {}).get("url") or c.get("url") or (pick.get("kalshi") or {}).get("url") or BOARD_URL
    return title, "\n".join(lines), click


def push(topic: str, title: str, body: str, click: str) -> None:
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), method="POST",
                                 headers={"Title": title.encode("ascii", "ignore").decode(), "Click": click,
                                          "Tags": "basketball", "Priority": "high"})
    urllib.request.urlopen(req, timeout=15).read()


def alert_new(board: dict, store, topic: str | None, log) -> int:
    """Alert every BET/LIMIT on today's card once, and once more if a LIMIT turns into a BET."""
    picks = {p["key"]: p for p in board.get("bets", []) + board.get("tests", []) + board.get("totals", [])
             + board.get("early", []) if p.get("line") is not None}
    card = board.get("card")
    if card is None:
        from .pricing import build_card
        card = build_card([p for p in picks.values() if p.get("group") in ALERT_GROUPS], board.get("slate", []))
    sent = []
    for c in card:
        p = picks.get(c["key"])
        if p is None or c["verdict"] == "PASS":
            continue
        meta = p.get("meta") or {}
        told = meta.get("alerted_verdict") or ("BET" if meta.get("alerted") else None)
        if told == "BET" or (told and c["verdict"] != "BET"):
            continue
        title, body, click = message(c, p)
        if topic:
            try:
                push(topic, title, body, click)
            except Exception as e:
                log(f"alert failed for {p['label']}: {e}")
                continue
        log(f"ALERT {title} | {body.splitlines()[0]}")
        sent.append({**{k: v for k, v in p.items() if k not in ("tag", "group")},
                     "meta": {**meta, "alerted": datetime.now(timezone.utc).isoformat(),
                              "alerted_verdict": c["verdict"]}})
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
