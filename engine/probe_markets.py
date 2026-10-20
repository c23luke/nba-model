"""Print what Polymarket and Kalshi list for NBA games right now (structure check)."""
import json
from .sources import get_json

def show(title, url, n=3000):
    print(f"\n===== {title}\n{url}")
    try:
        js = get_json(url)
        print(json.dumps(js, indent=1)[:n])
    except Exception as e:
        print("ERROR", e)

show("Polymarket events tagged nba", "https://gamma-api.polymarket.com/events?tag_slug=nba&closed=false&limit=5&order=startDate&ascending=true", 6000)
show("Polymarket sports list", "https://gamma-api.polymarket.com/sports", 2500)
show("Kalshi open spread events", "https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXNBASPREAD&status=open&limit=5", 2500)
show("Kalshi open total events", "https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXNBATOTAL&status=open&limit=5", 2500)
show("Kalshi total markets one event", "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXNBATOTAL&status=open&limit=3", 3000)
