"""Why does The Odds API answer 401? Prints its message and the quota headers (never the key).
Run: python -m engine.check_odds_key"""
import os
import urllib.error
import urllib.request

if __name__ == "__main__":
    key = "".join((os.environ.get("ODDS_API_KEY") or "").split())
    print("key present:", bool(key), "length:", len(key))
    url = f"https://api.the-odds-api.com/v4/sports/?apiKey={key}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            print("status", r.status, "| used", r.headers.get("x-requests-used"), "| remaining", r.headers.get("x-requests-remaining"))
    except urllib.error.HTTPError as e:
        print("status", e.code, "| used", e.headers.get("x-requests-used"), "| remaining", e.headers.get("x-requests-remaining"))
        print("message:", e.read().decode()[:300].replace(key, "<key>") if key else e.read().decode()[:300])
