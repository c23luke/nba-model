"""What NBA games look like on Polymarket US (public gateway) and whether Kalshi's demo exchange lists NBA."""
from __future__ import annotations

import json
import urllib.request

GW = "https://gateway.polymarket.us"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nba-model-probe", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def show(title, fn):
    print(f"\n===== {title}")
    try:
        fn()
    except Exception as e:
        print("FAILED:", e)


def leagues():
    js = get(f"{GW}/v2/leagues/nba/events?limit=6")
    print("top keys:", list(js))
    for ev in js.get("events", [])[:3]:
        print("\nEVENT", json.dumps({k: ev.get(k) for k in ("id", "ticker", "slug", "title", "startDate", "gameId",
                                                         "seriesSlug", "eventState", "active", "closed")}))
        print("  teams:", json.dumps(ev.get("teams"))[:800])
        for m in ev.get("markets", [])[:12]:
            print("  MARKET", json.dumps({k: m.get(k) for k in ("slug", "sportsMarketType", "sportsMarketTypeV2",
                                                              "marketType", "line", "bestBidQuote", "bestAskQuote",
                                                              "active", "closed")}))
            print("    sides:", json.dumps(m.get("marketSides"))[:900])
    if js.get("events"):
        m = js["events"][0]["markets"][0]
        print("\nFULL FIRST MARKET:", json.dumps(m)[:3000])
        bbo = get(f"{GW}/v1/markets/{m['slug']}/bbo")
        print("\nBBO:", json.dumps(bbo)[:1500])


def kalshi_demo():
    for base in ("https://demo-api.kalshi.co/trade-api/v2", "https://api.elections.kalshi.com/trade-api/v2"):
        js = get(f"{base}/events?series_ticker=KXNBASPREAD&status=open&limit=5")
        evs = [e["event_ticker"] for e in js.get("events", [])]
        print(base, "KXNBASPREAD open events:", evs)
        if evs:
            mk = get(f"{base}/markets?event_ticker={evs[0]}&limit=3").get("markets", [])
            for m in mk:
                print("   ", m["ticker"], {k: m.get(k) for k in ("yes_ask_dollars", "no_ask_dollars", "yes_bid_dollars",
                                                                 "floor_strike", "status")})


if __name__ == "__main__":
    show("Polymarket US NBA events", leagues)
    show("Kalshi demo vs prod NBA listings", kalshi_demo)
