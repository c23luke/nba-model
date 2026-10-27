"""Did Caden's SQL and Edge Function paste land? bet_settings, price_log, and the bettor's last logs.
Run: python -m engine.check_deploy"""
from .store import get_store


def main():
    st = get_store()
    s = (st._req("GET", "/bet_settings?select=*") or [{}])[0]
    print("bet_settings:", {k: v for k, v in s.items() if "token" not in k and "key" not in k})
    try:
        n = st._req("GET", "/price_log?select=id&order=id.desc&limit=3") or []
        print("price_log newest ids:", [r["id"] for r in n])
    except Exception as e:
        print("price_log:", e)
    logs = st._req("GET", "/bet_log?select=ts,level,message&order=ts.desc&limit=40") or []
    for r in logs:
        print(r["ts"][:19], r["level"], r["message"][:180])


if __name__ == "__main__":
    main()
