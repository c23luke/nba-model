import {
  contractsToWin, type Db, type FeedRow, type OrderRow, type Quote, type Settings, type Venue,
  etDayStart, evAt, Kalshi, kalshiFee, kalshiSigner, pkcs1ToPkcs8, polyFee, runOnce,
} from "./core.ts";

function eq(a: unknown, b: unknown, m = "") {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${m} expected ${JSON.stringify(b)} got ${JSON.stringify(a)}`);
}
function ok(c: unknown, m = "assertion failed") { if (!c) throw new Error(m); }

const NOW = new Date("2026-10-21T16:00:00Z");          // noon ET
const TIP = "2026-10-22T00:00:00Z";

function settings(p: Partial<Settings> = {}): Settings {
  return { live_betting_on: false, kalshi_env: "demo", venues: ["kalshi"], stake_dollars: 5, daily_loss_cap: 25,
    max_open_bets: 6, max_dollars_per_game: 10, min_ev: 0.02, max_feed_age_minutes: 20, run_token: "t",
    last_heartbeat: null, ...p };
}
function kq(p: Partial<Quote> = {}): Quote {
  return { venue: "kalshi", venue_name: "Kalshi", contract: "NO · IND wins by over 3.5", side: "NOP", line: 3.5,
    price: 0.49, cost: 0.51, win: 0.56, ev: 0.098, max_cost: 0.56, ticker: "KXNBASPREAD-26OCT21INDNOP-IND4",
    order_side: "no", ...p };
}
function feedRow(p: Partial<FeedRow> = {}, quotes = [kq()]): FeedRow {
  return { key: "g1-S113-NOP", status: "bet", updated_at: NOW.toISOString(), game_id: "g1", tip_utc: TIP,
    away: "IND", home: "NOP", system: "T13", pick: "NOP +3.5", bet: "spread", side: "NOP", quotes, ...p };
}

class FakeDb implements Db {
  orders_: OrderRow[] = [];
  logs: { level: string; message: string }[] = [];
  feedPatches: Record<string, unknown>[] = [];
  n = 0;
  constructor(public s: Settings, public rows: FeedRow[]) {}
  async settings() { return { ...this.s }; }
  async updateSettings(p: Record<string, unknown>) { Object.assign(this.s, p); }
  async feed() { return this.rows; }
  async orders() { return this.orders_.map((o) => ({ ...o })); }
  async insertOrder(row: OrderRow) {
    const active = ["pending", "filled", "error", "resting"];      // same as the DB's unique indexes (partial excluded: it can be topped up)
    if (row.mode === "live" && this.orders_.some((o) => o.mode === "live" && active.includes(o.status) &&
      (o.bet_key === row.bet_key || (o.venue === row.venue && o.market === row.market)))) return { conflict: true };
    const id = `id${++this.n}`;
    this.orders_.push({ ...row, id, created_at: NOW.toISOString(), seen_count: 1 });
    return { id };
  }
  async updateOrder(id: string, p: Partial<OrderRow>) { Object.assign(this.orders_.find((o) => o.id === id)!, p); }
  async updateFeed(key: string, p: Record<string, unknown>) { this.feedPatches.push({ key, ...p }); }
  async log(level: string, message: string) { this.logs.push({ level, message }); }
}

class FakeVenue implements Venue {
  name = "Kalshi";
  hasKeys = true;
  sent: { o: OrderRow; id: string }[] = [];
  constructor(public askPrice: number | null = 0.49, public fillAll = true, public bal = 100, public pnl = 0,
              public fail = false) {}
  async ask(q: Quote) { return { ask: this.askPrice, market: String(q.ticker) }; }
  fee(p: number, c: number) { return kalshiFee(p, c); }
  async balance() { return this.bal; }
  async pnlToday() { return this.pnl; }
  async order(o: OrderRow, id: string) {
    if (this.fail) throw new Error("boom");
    this.sent.push({ o, id });
    const fill = this.fillAll ? o.count : 0;
    return { order_id: "K1", fill_count: fill, fill_cost: fill * o.limit_price, fees: 0.18, raw: {} };
  }
}

Deno.test("dry run: logs WOULD HAVE PLACED once, sends nothing, refreshes on later runs", async () => {
  const db = new FakeDb(settings(), [feedRow()]);
  const k = new FakeVenue();
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(r.mode, "dry_run");
  eq(k.sent.length, 0, "nothing sent");
  eq(db.orders_.length, 1);
  const o = db.orders_[0];
  eq([o.status, o.order_side, o.limit_price, o.count, o.stake], ["dry_run", "no", 0.49, 10, 4.9]);
  eq(o.est_fee, 0.18);
  ok(db.logs.some((l) => l.message.startsWith("WOULD HAVE PLACED: Kalshi BUY NO ×10 KXNBASPREAD-26OCT21INDNOP-IND4 at 49¢")),
     JSON.stringify(db.logs));
  await runOnce(db, { kalshi: k }, NOW);
  eq(db.orders_.length, 1, "no duplicate dry row");
  eq(db.orders_[0].seen_count, 2);
});

Deno.test("live: limit at the model's price, immediate-or-cancel, result saved on the bet", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }), [feedRow()]);
  const k = new FakeVenue(0.47);           // ask improved: still capped at the model's 49c
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 1);
  eq([k.sent[0].o.limit_price, k.sent[0].o.count, k.sent[0].id], [0.49, 10, "id1"]);
  eq(db.orders_[0].status, "filled");
  eq((db.feedPatches[0] as any).order_status, "filled");
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 1, "never the same bet twice");
});

Deno.test("price moved above the model's price → skip", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }), [feedRow()]);
  const k = new FakeVenue(0.50);
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 0);
  ok(r.skips[0].reason.includes("moved above the model's 49¢"), r.skips[0].reason);
});

Deno.test("same market can't be bet twice, even from a different system", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }),
    [feedRow(), feedRow({ key: "g1-S4-NOP", system: "S4" })]);
  const k = new FakeVenue();
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 1);
});

Deno.test("an error is logged and never retried", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }), [feedRow()]);
  const k = new FakeVenue(0.49, true, 100, 0, true);
  await runOnce(db, { kalshi: k }, NOW);
  eq(db.orders_[0].status, "error");
  ok(db.logs.some((l) => l.level === "error" && l.message.includes("not retried")));
  k.fail = false;
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 0, "no retry after an error");
});

Deno.test("unfilled immediate-or-cancel can try again, at most 3 times", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }), [feedRow()]);
  const k = new FakeVenue(0.49, false);
  for (let i = 0; i < 5; i++) await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 3);
  ok(db.orders_.every((o) => o.status === "unfilled"));
  eq(new Set(k.sent.map((x) => x.id)).size, 3, "each try has its own client_order_id");
});

Deno.test("max dollars per game and max open bets", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, max_dollars_per_game: 4 }), [feedRow()]);
  const k = new FakeVenue();
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 0);
  ok(r.skips[0].reason.includes("max $4.00"), r.skips[0].reason);

  const rows = [1, 2, 3].map((i) => feedRow({ key: `g${i}-S113-X`, game_id: `g${i}` }, [kq({ ticker: `T${i}` })]));
  const db2 = new FakeDb(settings({ live_betting_on: true, max_open_bets: 2 }), rows);
  const k2 = new FakeVenue();
  await runOnce(db2, { kalshi: k2 }, NOW);
  eq(k2.sent.length, 2);
});

Deno.test("daily loss cap switches live betting off before anything is sent", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }), [feedRow()]);
  db.orders_.push({ mode: "live", env: "prod", venue: "kalshi", market: "OLD", order_side: "yes", bet_key: "old",
    game_id: "g0", tip_utc: "2026-10-21T00:00:00Z", pick: "x", system: "T13", contract: "x", line: 1, model_price: .5,
    ask_at_check: .5, limit_price: .5, count: 10, stake: 5, est_fee: .18, ev: .05, status: "filled", fill_count: 10,
    id: "old", created_at: "2026-10-20T20:00:00Z" });
  const k = new FakeVenue(0.49, true, 100, -25.4);
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(db.s.live_betting_on, false);
  ok(String(r.stopped).includes("Daily loss cap"));
  eq(k.sent.length, 0);
});

Deno.test("balance too low → skip", async () => {
  const db = new FakeDb(settings({ live_betting_on: true }), [feedRow()]);
  const k = new FakeVenue(0.49, true, 3);
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 0);
  ok(r.skips[0].reason.includes("balance"), r.skips[0].reason);
});

Deno.test("stale feed rows and switched-off venues are ignored", async () => {
  const db = new FakeDb(settings({ venues: [] }), [feedRow()]);
  const r = await runOnce(db, { kalshi: new FakeVenue() }, NOW);
  ok(r.skips[0].reason.startsWith("no quote"), r.skips[0].reason);
});

Deno.test("Polymarket US never goes live until verified", async () => {
  const pq: Quote = { venue: "polymarket_us", venue_name: "Polymarket US", contract: "NOP to win", side: "NOP", ml: true,
    line: -0.5, american: 150, cost: 0.4, win: 0.5, ev: 0.2, max_cost: 0.5 };
  const db = new FakeDb(settings({ live_betting_on: true, venues: ["polymarket_us"] }), [feedRow({}, [pq])]);
  const pv = new FakeVenue(0.39);
  pv.name = "Polymarket US";
  const r = await runOnce(db, { polymarket_us: pv }, NOW);
  eq(pv.sent.length, 0);
  ok(r.skips[0].reason.includes("dry-run only"), r.skips[0].reason);
});

Deno.test("fees, expected return, ET day", () => {
  eq(kalshiFee(0.49, 10), 0.18);
  eq(kalshiFee(0.5, 100), 1.75);
  eq(polyFee(0.5, 100), 1.74);              // 1.7375 → 1.74
  eq(polyFee(0.5, 2), 0.03);                // 0.03475 → 0.03
  const q = kq();
  ok(Math.abs(evAt(q, 0.56)) < 1e-9, "zero at break-even");
  eq(etDayStart(new Date("2026-10-20T03:00:00Z")).toISOString(), "2026-10-19T04:00:00.000Z");
  eq(etDayStart(new Date("2026-12-20T15:00:00Z")).toISOString(), "2026-12-20T05:00:00.000Z");
});

function pem(label: string, der: ArrayBuffer | Uint8Array) {
  const b = new Uint8Array(der as ArrayBuffer);
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return `-----BEGIN ${label}-----\n${btoa(s).match(/.{1,64}/g)!.join("\n")}\n-----END ${label}-----\n`;
}
const b64d = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

Deno.test("Kalshi signing: Ed25519 key, and RSA keys in both PEM formats", async () => {
  const msg = "1700000000000POST/trade-api/v2/portfolio/orders";
  const ed = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const edSig = await (await kalshiSigner(pem("PRIVATE KEY", await crypto.subtle.exportKey("pkcs8", ed.privateKey))))(msg);
  ok(await crypto.subtle.verify({ name: "Ed25519" }, ed.publicKey, b64d(edSig), new TextEncoder().encode(msg)), "ed25519");

  const rsa = await crypto.subtle.generateKey({ name: "RSA-PSS", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
    hash: "SHA-256" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const p8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", rsa.privateKey));
  const p1 = p8.slice(26);                                         // strip the PKCS#8 wrapper
  eq(Array.from(pkcs1ToPkcs8(p1)), Array.from(p8), "PKCS#1 → PKCS#8 round trip");
  for (const key of [pem("RSA PRIVATE KEY", p1), pem("PRIVATE KEY", p8), pem("RSA PRIVATE KEY", p1).replace(/\n/g, "\\n")]) {
    const sig = await (await kalshiSigner(key))(msg);
    ok(await crypto.subtle.verify({ name: "RSA-PSS", saltLength: 32 }, rsa.publicKey, b64d(sig), new TextEncoder().encode(msg)), "rsa");
  }
});

Deno.test("Kalshi order request: signed headers, path without query, IOC limit body", async () => {
  const ed = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const signer = await kalshiSigner(pem("PRIVATE KEY", await crypto.subtle.exportKey("pkcs8", ed.privateKey)));
  const calls: { url: string; init: RequestInit }[] = [];
  const http = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    if (url.includes("/portfolio/events/orders")) {
      const b = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ order_id: "abc", client_order_id: b.client_order_id, fill_count: "10.00",
        remaining_count: "0.00", average_fill_price: b.side === "ask" ? "0.5200" : "0.4700", average_fee_paid: "0.0180",
        ts_ms: 1 }), { status: 201 });
    }
    if (url.includes("/portfolio/settlements")) {
      return new Response(JSON.stringify({ settlements: [
        { ticker: "MINE", revenue: 0, no_total_cost_dollars: "4.9000", yes_total_cost_dollars: "0", fee_cost: "0.1800" },
        { ticker: "SCANNER", revenue: 1000, no_total_cost_dollars: "5.0000", yes_total_cost_dollars: "0", fee_cost: "0.1" }],
        cursor: "" }));
    }
    return new Response(JSON.stringify({ market: { status: "active", no_ask_dollars: "0.4800", yes_ask_dollars: "0.5300" } }));
  }) as unknown as typeof fetch;
  const k = new Kalshi("https://demo-api.kalshi.co/trade-api/v2", "KEYID", signer, "https://api.elections.kalshi.com/trade-api/v2", http);
  const a = await k.ask(kq());
  eq(a.ask, 0.48);
  ok(calls[0].url.startsWith("https://api.elections.kalshi.com"), "dry-run prices from prod");
  const o = { market: "KXNBASPREAD-26OCT21INDNOP-IND4", order_side: "no", count: 10, limit_price: 0.49 } as OrderRow;
  const r = await k.order(o, "client-1");
  // buy NO at 49c = sell YES at 51c or better; filled at YES 52c = NO cost 48c each
  eq([r.order_id, r.fill_count, r.fill_cost, r.fees], ["abc", 10, 4.8, 0.18]);
  const c = calls[1];
  ok(c.url === "https://demo-api.kalshi.co/trade-api/v2/portfolio/events/orders", c.url);
  const body = JSON.parse(String(c.init.body));
  eq(body, { ticker: o.market, side: "ask", count: "10", price: "0.5100", time_in_force: "immediate_or_cancel",
    self_trade_prevention_type: "taker_at_cross", client_order_id: "client-1" });
  const h = c.init.headers as Record<string, string>;
  eq(h["KALSHI-ACCESS-KEY"], "KEYID");
  const signed = h["KALSHI-ACCESS-TIMESTAMP"] + "POST/trade-api/v2/portfolio/events/orders";
  ok(await crypto.subtle.verify({ name: "Ed25519" }, ed.publicKey, b64d(h["KALSHI-ACCESS-SIGNATURE"]),
    new TextEncoder().encode(signed)), "signature covers timestamp+method+path");
  // buy YES at 49c = bid at 49c
  const ry = await k.order({ ...o, order_side: "yes" } as OrderRow, "client-2");
  const by = JSON.parse(String(calls[calls.length - 1].init.body));
  eq([by.side, by.price], ["bid", "0.4900"]);
  eq(ry.fill_cost, 4.7);
  const pnl = await k.pnlToday(new Set(["MINE"]), NOW.getTime());
  ok(Math.abs(pnl + 5.08) < 1e-9, `only this system's markets count: ${pnl}`);
  const sc = calls[3];
  const sh = sc.init.headers as Record<string, string>;
  ok(await crypto.subtle.verify({ name: "Ed25519" }, ed.publicKey, b64d(sh["KALSHI-ACCESS-SIGNATURE"]),
    new TextEncoder().encode(sh["KALSHI-ACCESS-TIMESTAMP"] + "GET/trade-api/v2/portfolio/settlements")), "query string not signed");
});

Deno.test("Polymarket US: finds the game's moneyline and which side is ours", async () => {
  const { PolymarketUS } = await import("./core.ts");
  const ev = { startDate: "2026-10-20T23:00:00Z", teams: [{ abbreviation: "phi", displayAbbreviation: "PHI" },
    { abbreviation: "ny", displayAbbreviation: "NY" }],
    markets: [{ slug: "aec-nba-phi-ny-2026-10-20", sportsMarketType: "basketball_team_full_game_winner",
      marketSides: [{ long: true, team: { abbreviation: "phi", displayAbbreviation: "PHI" } },
                    { long: false, team: { abbreviation: "ny", displayAbbreviation: "NY" } }] }] };
  const http = (async (url: string) => new Response(JSON.stringify(url.includes("/bbo")
    ? { marketData: { longQuote: { value: "0.3900" }, shortQuote: { value: "0.62" } } }
    : { events: [ev] }))) as unknown as typeof fetch;
  const p = new PolymarketUS(undefined, undefined, http);
  const row = feedRow({ away: "PHI", home: "NYK", tip_utc: "2026-10-20T23:00:00Z" });
  const q: Quote = { venue: "polymarket_us", contract: "NYK to win", side: "NYK", ml: true, line: -0.5, cost: 0.63,
    win: 0.6, ev: 0.05, max_cost: 0.6 };
  const a = await p.ask(q, row);
  eq([a.market, a.ask, q.order_side], ["aec-nba-phi-ny-2026-10-20", 0.62, "short"]);
  const q2 = { ...q, side: "PHI", contract: "PHI to win" };
  eq((await p.ask(q2, row)).ask, 0.39);
  eq(q2.order_side, "long");
});


Deno.test("to-win sizing: same $20 win on every bet, whatever the price", async () => {
  // 49c: 41 contracts win 41 x 0.51 = 20.91, minus the 0.72 fee = 20.19 ≥ 20
  eq(contractsToWin(0.49, 20, kalshiFee), 41);
  ok(40 * 0.51 - kalshiFee(0.49, 40) < 20, "one fewer falls short");
  const c70 = contractsToWin(0.70, 20, kalshiFee);
  ok(c70 * 0.30 - kalshiFee(0.70, c70) >= 20 && (c70 - 1) * 0.30 - kalshiFee(0.70, c70 - 1) < 20);
  const db = new FakeDb(settings({ to_win_dollars: 20, max_dollars_per_game: 50 }), [feedRow()]);
  await runOnce(db, { kalshi: new FakeVenue() }, NOW);
  const o = db.orders_[0];
  eq([o.count, o.stake], [41, 20.09]);
  ok(o.count * (1 - o.limit_price) - o.est_fee >= 20, "wins at least $20 after the fee");
});


Deno.test("a Low-confidence bet is sized to win $10; the settings cap still rules", async () => {
  const db = new FakeDb(settings({ to_win_dollars: 20, max_dollars_per_game: 50 }), [feedRow({ to_win: 10 })]);
  await runOnce(db, { kalshi: new FakeVenue() }, NOW);
  const o = db.orders_[0];
  ok(o.count * (1 - o.limit_price) - o.est_fee >= 10 && o.count < 41, `count ${o.count}`);
  const db2 = new FakeDb(settings({ to_win_dollars: 5, max_dollars_per_game: 50 }), [feedRow({ to_win: 20 })]);
  await runOnce(db2, { kalshi: new FakeVenue() }, NOW);
  ok(db2.orders_[0].count * 0.51 - db2.orders_[0].est_fee < 7, "never bigger than the setting");
});

// ------------------------------------------------------------------ BetOpenly
import { BetOpenly, BETOPENLY_BASE, gradeAt, outcomeAt, pnlFromGames, type Model } from "./core.ts";

const MODEL: Model = { win0: 0.56, base: 3.5, bet: "spread", side: "NOP", sd: 14.14, lo: -10.5, hi: 7.5, market: 3.5 };
function offer(p: Record<string, unknown> = {}, d: Record<string, unknown> = {}) {
  return { id: "off1", betType: "GAME", betStatus: "PENDING", expiryDate: Date.parse(TIP) / 1000, availableAmount: 50,
    details: [{ league: "NBA", timeframe: "game", eventDateIso: TIP, betType: "spread", team: "New Orleans Pelicans",
      teamAbbv: "NO", lines: 4, odds: -105,
      homeTeam: { displayName: "New Orleans Pelicans", abbreviation: "NO" },
      awayTeam: { displayName: "Indiana Pacers", abbreviation: "IND" }, ...d }], ...p };
}
function fakeBO(book: unknown[], status: Record<string, unknown> = {}, accept: Record<string, unknown> = {}) {
  const calls: { method: string; url: string; headers: Record<string, string>; body?: string }[] = [];
  const http = (async (url: string, init: RequestInit) => {
    calls.push({ method: init.method!, url, headers: init.headers as Record<string, string>, body: init.body as string });
    const path = url.replace(BETOPENLY_BASE, "");
    let js: unknown = {};
    if (path === "/v1/partners/bets/open-bets") js = { data: book };
    else if (path.endsWith("/status")) js = { ...(book.find((b: any) => path.includes(b.id)) as object), ...status };
    else if (path.endsWith("/accept")) js = { acceptedAmount: JSON.parse(init.body as string).amount, amountToWin: 19.05, childBetId: "child9", ...accept };
    else if (path === "/v1/partners/funds") js = { data: { availableFunds: 212.5 } };
    return new Response(JSON.stringify(js), { status: 200 });
  }) as unknown as typeof fetch;
  return { bo: new BetOpenly("k", http, () => NOW.getTime()), calls };
}
const boRow = (p: Partial<FeedRow> = {}) => feedRow({ model: MODEL, to_win: 20, ...p }, []);

Deno.test("model math matches the Python card (push on whole numbers)", () => {
  const a = outcomeAt(MODEL, 3.5); ok(Math.abs(a.win - 0.56) < 1e-3 && a.push === 0, JSON.stringify(a));
  const b = outcomeAt(MODEL, 4); ok(Math.abs(b.win - 0.56) < 1e-9 && Math.abs(b.push - 0.039) < 1e-9, JSON.stringify(b));
  const c = outcomeAt(MODEL, 1.5); ok(Math.abs(c.win - 0.486) < 1e-9, `measured: 2 points near a 3.5 line = 7.4% (${c.win})`);
  const o = outcomeAt({ ...MODEL, bet: "total", side: "OVER", base: 225.5, sd: 18.18 }, 224);
  ok(o.win > 0.56, "over gets better as the number drops");
});

Deno.test("BetOpenly: reads offers from our side, skips parlays/expired/other games/wrong side/out of the rule", async () => {
  const book = [
    offer(),                                                             // NOP +4 -105: ours
    offer({ id: "parlay", details: [offer().details[0], offer().details[0]] }),
    offer({ id: "old", expiryDate: NOW.getTime() / 1000 - 60 }),
    offer({ id: "taken", betStatus: "ACCEPTED" }),
    offer({ id: "ind" }, { team: "Indiana Pacers", teamAbbv: "IND", lines: -4 }),   // other side
    offer({ id: "half" }, { timeframe: "1h" }),
    offer({ id: "far" }, { lines: 8.5 }),                                // past the system's max (7.5)
    offer({ id: "ml" }, { betType: "moneyline", lines: null, odds: 150 }), // NOP ML = -0.5, inside window? 4 pts from 3.5
    offer({ id: "nyk" }, { homeTeam: { abbreviation: "NY" }, awayTeam: { abbreviation: "BOS" } }),
  ];
  const { bo } = fakeBO(book);
  const qs = await bo.offers(boRow());
  eq(qs.map((q) => q.offer_id).sort(), ["ml", "off1"]);
  const q = qs.find((q) => q.offer_id === "off1")!;
  eq([q.contract, q.line, q.american, q.side, q.size], ["NOP +4", 4, -105, "NOP", 50]);
});

Deno.test("BetOpenly dry run: WOULD HAVE PLACED, nothing accepted", async () => {
  const { bo, calls } = fakeBO([offer()]);
  const db = new FakeDb(settings({ venues: ["betopenly"], to_win_dollars: 20, max_dollars_per_game: 50 }), [boRow()]);
  await runOnce(db, { betopenly: bo }, NOW);
  const line = db.logs.find((l) => l.message.startsWith("WOULD HAVE PLACED"))?.message ?? "";
  ok(line.startsWith("WOULD HAVE PLACED: BetOpenly ACCEPT offer off1: NOP +4 at -105 for $21."), line);
  ok(line.includes("to win $20."), line);
  eq(calls.filter((c) => c.url.endsWith("/accept")).length, 0, "nothing accepted");
  eq(calls[0].headers["x-api-key"], "k");
  eq(db.orders_[0].market, "bo:IND@NOP:spread:NOP:4");
});

Deno.test("BetOpenly live: re-checks the offer, accepts min(stake, available), saves childBetId", async () => {
  const { bo, calls } = fakeBO([offer({ availableAmount: 12 })]);
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", venues: ["betopenly"], to_win_dollars: 20,
    max_dollars_per_game: 50 }), [boRow()]);
  await runOnce(db, { betopenly: bo }, NOW);
  const acc = calls.find((c) => c.url.endsWith("/accept"))!;
  eq(acc.url, `${BETOPENLY_BASE}/v1/partners/bets/off1/accept`);
  eq(JSON.parse(acc.body!), { amount: 12 });
  const o = db.orders_[0];
  eq([o.order_id, o.fill_cost, o.status], ["child9", 12, "partial"]);
});

Deno.test("BetOpenly: odds changed since we saw it → skip, nothing accepted", async () => {
  const { bo, calls } = fakeBO([offer()], { details: [{ ...offer().details[0], odds: -115 }] });
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", venues: ["betopenly"], to_win_dollars: 20,
    max_dollars_per_game: 50 }), [boRow()]);
  await runOnce(db, { betopenly: bo }, NOW);
  eq(calls.filter((c) => c.url.endsWith("/accept")).length, 0);
  eq(db.orders_.length, 0);
});

Deno.test("BetOpenly balance and grading from final scores", async () => {
  const { bo } = fakeBO([]);
  eq(await bo.balance(), 212.5);
  const g = { id: "g1", home: "NOP", away: "IND", home_score: 110, away_score: 113, final: true };
  const base = { bet: "spread", side: "NOP", line: 4 } as OrderRow;
  eq(gradeAt(base, g), "W");                                  // lost by 3, +4 covers
  eq(gradeAt({ ...base, line: 3 } as OrderRow, g), "P");
  eq(gradeAt({ ...base, bet: "total", side: "OVER", line: 224.5 } as OrderRow, g), "L");
  const db = new FakeDb(settings(), []);
  (db as any).games = async () => [g];
  const pnl = await pnlFromGames(db, [{ ...base, game_id: "g1", tip_utc: TIP, fill_cost: 21, fill_count: 41, fees: 0.2 } as OrderRow],
    etDayStart(NOW).getTime());
  eq(Math.round(pnl * 100) / 100, 19.8);
});

Deno.test("BetOpenly: the skip reason lists what was on the game and why each was passed over", async () => {
  const { bo } = fakeBO([offer({}, { lines: 8.5 }), offer({ id: "x" }, { team: "Indiana Pacers", teamAbbv: "IND", lines: -4 })]);
  const db = new FakeDb(settings({ venues: ["betopenly"], to_win_dollars: 20 }), [boRow()]);
  const r = await runOnce(db, { betopenly: bo }, NOW);
  const why = r.skips[0].reason;
  ok(why.includes("NO spread 8.5 -105 ($50): number outside the system"), why);
  ok(why.includes("IND spread -4 -105 ($50): other side"), why);
});

// ------------------------------------------------------------------ resting limit orders (Kalshi)
import { kalshiMakerFee, ProphetX, PROPHETX_BASE, restingPrice } from "./core.ts";

class RestVenue extends FakeVenue {
  rested: { o: OrderRow; id: string; exp: number }[] = [];
  cancelled: string[] = [];
  state: Record<string, { status: string; fill_count: number; fill_cost: number; fees: number }> = {};
  async rest(o: OrderRow, id: string, exp: number) {
    this.rested.push({ o, id, exp });
    this.state["R" + this.rested.length] = { status: "resting", fill_count: 0, fill_cost: 0, fees: 0 };
    return { order_id: "R" + this.rested.length, fill_count: 0, fill_cost: 0, fees: 0, raw: {} };
  }
  async getOrder(id: string) { return { ...this.state[id], raw: {} }; }
  async cancel(id: string) { this.cancelled.push(id); this.state[id] = { ...this.state[id], status: "canceled" }; }
}
const limitRow = (p: Partial<FeedRow> = {}) => feedRow({ status: "limit", to_win: 20, ...p }, [kq({ ev: -0.01 })]);

Deno.test("resting price: the most we'd pay and still make the minimum return after the maker fee", () => {
  const p = restingPrice(0.56, 0, 0.02);
  eq(p, 0.54);
  const allIn = p + kalshiMakerFee(p, 100) / 100;
  ok(0.56 / allIn - 1 >= 0.02, `still +2% at ${allIn}`);
});

Deno.test("a LIMIT bet rests one good-till-canceled order on Kalshi that expires before tip", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", to_win_dollars: 20, max_dollars_per_game: 50 }), [limitRow()]);
  const k = new RestVenue();
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.rested.length, 1);
  const r = k.rested[0];
  eq([r.o.limit_price, r.o.order_side, db.orders_[0].status, db.orders_[0].order_id], [0.54, "no", "resting", "R1"]);
  eq(r.exp, Date.parse(TIP) / 1000 - 300);
  ok(r.o.count * (1 - 0.54) - kalshiMakerFee(0.54, r.o.count) >= 20, "sized to win $20 after the maker fee");
  await runOnce(db, { kalshi: k }, NOW);                     // next minute: no second order
  eq(k.rested.length, 1);
});

Deno.test("resting orders: fills are recorded, and it's cancelled once the bet leaves LIMIT", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", to_win_dollars: 20, max_dollars_per_game: 50 }), [limitRow()]);
  const k = new RestVenue();
  await runOnce(db, { kalshi: k }, NOW);
  k.state.R1 = { status: "resting", fill_count: 10, fill_cost: 5.4, fees: 0.05 };
  await runOnce(db, { kalshi: k }, NOW);
  eq([db.orders_[0].status, db.orders_[0].fill_count, db.orders_[0].fill_cost], ["resting", 10, 5.4]);
  db.rows = [feedRow({ status: "pass" })];                  // model no longer wants it at a limit
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.cancelled, ["R1"]);
  eq(db.orders_[0].status, "partial");                       // kept what filled
});

Deno.test("resting orders are cancelled 5 minutes before tip", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", to_win_dollars: 20, max_dollars_per_game: 50 }), [limitRow()]);
  const k = new RestVenue();
  await runOnce(db, { kalshi: k }, NOW);
  await runOnce(db, { kalshi: k }, new Date(Date.parse(TIP) - 3 * 60e3));
  eq(k.cancelled, ["R1"]);
  eq(db.orders_[0].status, "unfilled");
});

// ------------------------------------------------------------------ ProphetX
function fakePX(markets: unknown[], opts: { orderStatus?: Record<string, unknown> } = {}) {
  const calls: { method: string; path: string; body?: any; auth?: string }[] = [];
  const http = (async (url: string, init: RequestInit) => {
    const path = url.replace(PROPHETX_BASE, "");
    const h = init.headers as Record<string, string>;
    calls.push({ method: init.method!, path, body: init.body ? JSON.parse(init.body as string) : undefined, auth: h.authorization });
    const j = (data: unknown, status = 200) => new Response(JSON.stringify({ data }), { status });
    if (path === "/auth/login") return j({ access_token: "A1", refresh_token: "R1", access_expire_time: Math.floor(NOW.getTime() / 1000) + 600, refresh_expire_time: Math.floor(NOW.getTime() / 1000) + 86400 });
    if (path.startsWith("/mm/get_tournaments")) return j({ tournaments: [{ id: 9, name: "WNBA" }, { id: 7, name: "NBA" }] });
    if (path.startsWith("/mm/get_sport_events")) return j({ sport_events: [{ event_id: 55, scheduled: TIP, competitors: [
      { id: 1, name: "Indiana Pacers", abbreviation: "IND", side: "away" }, { id: 2, name: "New Orleans Pelicans", abbreviation: "NO", side: "home" }] }] });
    if (path.startsWith("/v4/mm/get_markets")) return j({ event_id: 55, markets });
    if (path === "/v4/mm/submit_order") return j({ success: true, order: { order_id: "partner_x", status: "inactive", filled_quantity: 0 } });
    if (path.startsWith("/v4/mm/get_order/")) return j({ order_id: "partner_x", open_quantity: 0, filled_quantity: 20.5, matching_status: "fully_matched", status: "open", ...(opts.orderStatus || {}) });
    if (path.startsWith("/v4/mm/get_order_matched_detail")) return j({ matching_details: [{ profit: 20.5, quantity: 20.5, price: 100 }] });
    if (path === "/v4/mm/get_balance") return j({ balance: 250.75 });
    return new Response("{}", { status: 404 });
  }) as unknown as typeof fetch;
  return { http, calls };
}
const pxMarkets = [{ id: 1, type: "spread", status: "active", selections: [
  [{ competitor_id: 2, name: "New Orleans Pelicans", strike: 4, price: 100, value: 300, strike_id: "nop4" },
   { competitor_id: 2, name: "New Orleans Pelicans", strike: 8.5, price: 250, value: 300, strike_id: "nop85" }],
  [{ competitor_id: 1, name: "Indiana Pacers", strike: -4, price: -120, value: 300, strike_id: "ind4" }]] }];
const pxRow = () => feedRow({ model: { win0: 0.56, base: 3.5, bet: "spread", side: "NOP", sd: 14.14, lo: -10.5, hi: 7.5, market: 3.5 }, to_win: 20 }, []);

Deno.test("ProphetX: logs in once, caches the token, prices our side at its own number", async () => {
  const { http, calls } = fakePX(pxMarkets);
  const db = new FakeDb(settings(), []);
  const st: Record<string, unknown> = {};
  (db as any).getState = async (k: string) => st[k] ?? null;
  (db as any).setState = async (k: string, v: unknown) => { st[k] = v; };
  const px = new ProphetX("a", "s", db, http, () => NOW.getTime(), async () => {});
  const qs = await px.offers(pxRow());
  eq(qs.map((q) => [q.contract, q.american, q.offer_id]), [["NOP +4", 100, "nop4"]]);   // +8.5 is past the system's max
  eq(calls.filter((c) => c.path === "/auth/login").length, 1);
  eq(calls.find((c) => c.path.startsWith("/v4/mm/get_markets"))!.auth, "Bearer A1");
  const px2 = new ProphetX("a", "s", db, http, () => NOW.getTime(), async () => {});
  eq(await px2.balance(), 250.75);
  eq(calls.filter((c) => c.path === "/auth/login").length, 1, "second run reuses the cached token");
});

Deno.test("ProphetX order: fillOrKill at our price, waits for matching, records the fill", async () => {
  const { http, calls } = fakePX(pxMarkets);
  const px = new ProphetX("a", "s", undefined, http, () => NOW.getTime(), async () => {});
  const q = (await px.offers(pxRow()))[0];
  const r = await px.order({ stake: 20.5, count: 41 } as OrderRow, "client-9", q);
  const sub = calls.find((c) => c.path === "/v4/mm/submit_order")!;
  eq(sub.body, { external_id: "client-9", strike_id: "nop4", price: 100, quantity: 20.5, order_strategy: "fillOrKill" });
  eq([r.order_id, r.fill_cost, r.fill_count, r.fees], ["partner_x", 20.5, 41, 0.41]);
});

Deno.test("test-only sites log WOULD HAVE PLACED while live betting is on, and never place", async () => {
  const { http, calls } = fakePX(pxMarkets);
  const px = new ProphetX("a", "s", undefined, http, () => NOW.getTime(), async () => {});
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", venues: ["kalshi"], watch_venues: ["prophetx"],
    to_win_dollars: 20, max_dollars_per_game: 50 }), [pxRow()]);
  await runOnce(db, { kalshi: new FakeVenue(null), prophetx: px }, NOW);
  ok(db.logs.some((l) => l.message.startsWith("WOULD HAVE PLACED: ProphetX (test site) NOP +4 at +100")), JSON.stringify(db.logs));
  eq(calls.filter((c) => c.path === "/v4/mm/submit_order").length, 0);
  eq(db.orders_.filter((o) => o.mode === "live").length, 0);
});


Deno.test("ProphetX: a spread number that's signed backwards vs the market is skipped", async () => {
  const flipped = [{ id: 1, type: "spread", status: "active", selections: [
    [{ competitor_id: 2, name: "New Orleans Pelicans", strike: -3.5, price: 100, value: 300, strike_id: "nopm35" }]] }];
  const { http } = fakePX(flipped);
  const px = new ProphetX("a", "s", undefined, http, () => NOW.getTime(), async () => {});
  const row = pxRow();
  eq((await px.offers(row)).length, 0);
  ok(px.explain(row).includes("looks flipped"), px.explain(row));
});


Deno.test("near ties go to the number that wins more often; a clearly better price still wins", async () => {
  // both priced at the fake 49¢ ask; +3.5 cashes more often, +1.5 is listed with slightly more expected return
  const p15 = kq({ contract: "NOP +1.5", line: 1.5, ev: 0.114, win: 0.58, max_cost: 0.58, ticker: "IND2" });
  const p35 = kq({ contract: "NOP +3.5", line: 3.5, ev: 0.109, win: 0.62, max_cost: 0.62, ticker: "IND4" });
  const db = new FakeDb(settings(), [feedRow({}, [p15, p35])]);
  await runOnce(db, { kalshi: new FakeVenue() }, NOW);
  eq(db.orders_[0].contract, "NOP +3.5");
  const db2 = new FakeDb(settings(), [feedRow({}, [{ ...p15, ev: 0.14 }, p35])]);
  await runOnce(db2, { kalshi: new FakeVenue() }, NOW);
  eq(db2.orders_[0].contract, "NOP +1.5");
});

// ------------------------------------------------------------------ not enough money on a site
class RefusingVenue extends FakeVenue {
  override async order(_o: OrderRow, _id: string): Promise<any> {
    throw new Error(`Kalshi POST /trade-api/v2/portfolio/events/orders → 400: {"error":{"code":"insufficient_balance"}}`);
  }
}

Deno.test("a site that refuses the order (e.g. insufficient balance) doesn't lock the bet: the next site gets it", async () => {
  const kal = kq({ ev: 0.12 });
  const other = kq({ venue: "betopenly2", venue_name: "Other", ticker: "B1", ev: 0.11, win: 0.56, max_cost: 0.56 });
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", venues: ["kalshi", "betopenly2"] }), [feedRow({}, [kal, other])]);
  const k = new RefusingVenue(), b = new FakeVenue();
  b.name = "Other";
  await runOnce(db, { kalshi: k, betopenly2: b }, NOW);
  eq(db.orders_.map((o) => [o.venue, o.status]), [["kalshi", "unfilled"], ["betopenly2", "filled"]]);
  ok(String(db.orders_[0].reason).startsWith("rejected by Kalshi"), String(db.orders_[0].reason));
  eq(b.sent.length, 1);
});

Deno.test("a timeout or server error still locks the bet (it might have gone through)", async () => {
  class Down extends FakeVenue { override async order(): Promise<any> { throw new Error("Kalshi POST /x → 503: unavailable"); } }
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", venues: ["kalshi", "b"] }),
    [feedRow({}, [kq({ ev: 0.12 }), kq({ venue: "b", ticker: "B1", ev: 0.11 })])]);
  const b = new FakeVenue();
  await runOnce(db, { kalshi: new Down(), b }, NOW);
  eq(db.orders_.map((o) => o.status), ["error"]);
  eq(b.sent.length, 0);
});

Deno.test("money spent earlier in the same run counts against the site's balance (balances can lag)", async () => {
  const rows = [feedRow({ key: "a", game_id: "g1" }), feedRow({ key: "b", game_id: "g2", pick: "X +1" }, [kq({ ticker: "T2" })])];
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", max_dollars_per_game: 50 }), rows);
  const k = new FakeVenue(0.49, true, 8);                  // $8 on Kalshi; each bet costs ~$5.08
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 1);
});

Deno.test("a resting order isn't sent when the site doesn't have the money", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, kalshi_env: "prod", to_win_dollars: 20, max_dollars_per_game: 50 }),
    [feedRow({ status: "limit", to_win: 20 }, [kq({ ev: -0.01 })])]);
  const k = new RestVenue();
  k.bal = 5;
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(k.rested.length, 0);
  ok(r.skips.some((x) => x.reason.includes("Kalshi balance $5.00 is under")), JSON.stringify(r.skips));
});


Deno.test("a partial fill is topped up on the next run until the bet reaches its to-win target", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, to_win_dollars: 20, max_dollars_per_game: 60 }), [feedRow()]);
  const k = new FakeVenue();
  let calls = 0;
  k.order = async (o: OrderRow, id: string) => {             // first order: only 10 of 41 contracts fill
    k.sent.push({ o, id });
    const fill = calls++ === 0 ? 10 : o.count;
    return { order_id: `K${calls}`, fill_count: fill, fill_cost: fill * o.limit_price, fees: 0.1, raw: {} };
  };
  await runOnce(db, { kalshi: k }, NOW);
  eq(db.orders_[0].status, "partial");
  const first = 10 - 10 * 0.49 - 0.1;                            // $5.00 won so far
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 2, "the rest is bought on the next run (same market is allowed for a top-up)");
  const o2 = k.sent[1].o;
  ok(o2.count * (1 - o2.limit_price) - o2.est_fee >= 20 - first - 0.01 && o2.count < 41, `top-up sized to what's missing: ${o2.count}`);
  await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 2, "full now: nothing more");
});

Deno.test("a partial fill within $2 of the target is left alone", async () => {
  const db = new FakeDb(settings({ live_betting_on: true, to_win_dollars: 20, max_dollars_per_game: 60 }), [feedRow()]);
  db.orders_.push({ mode: "live", status: "partial", venue: "kalshi", market: "KXNBASPREAD-26OCT21INDNOP-IND4",
    bet_key: "g1-S113-NOP", game_id: "g1", fill_count: 40, fill_cost: 19.6, fees: 0.7, created_at: NOW.toISOString() } as OrderRow);
  const k = new FakeVenue();
  const r = await runOnce(db, { kalshi: k }, NOW);
  eq(k.sent.length, 0);
  ok(r.skips[0].reason.includes("already partial"), r.skips[0].reason);
});

Deno.test("Kalshi: a rate-limited read waits and retries; an order is never re-sent", async () => {
  let n = 0;
  const http = (async (url: string, init: any) => {
    n++;
    if (init.method === "GET" && n === 1) return new Response('{"error":{"code":"too_many_requests"}}', { status: 429 });
    if (init.method === "POST") return new Response('{"error":{"code":"too_many_requests"}}', { status: 429 });
    return new Response(JSON.stringify({ balance: 8432 }), { status: 200 });
  }) as unknown as typeof fetch;
  const k = new Kalshi("https://x/trade-api/v2", "kid", async () => "sig", "https://x/trade-api/v2", http, 1);
  eq(await k.balance(), 84.32);
  eq(n, 2);
  let threw = false;
  try { await k.order({ order_side: "no", limit_price: 0.5, count: 2, market: "M" } as OrderRow, "c1"); } catch { threw = true; }
  ok(threw && n === 3, "POST tried once only");
});
