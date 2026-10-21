// place-bets — Caden's order placer. Runs every minute from pg_cron.
//
// Reads today's card from bet_feed, picks the best quote on a venue that is switched on,
// runs every safety rule, then either logs "would have placed" (dry run, the default)
// or sends a limit order at the price the model saw, immediate-or-cancel.
//
// Keys are Supabase secrets, read with Deno.env.get — never stored in tables or code:
//   KALSHI_KEY_ID, KALSHI_PRIVATE_KEY                 (prod)
//   KALSHI_DEMO_KEY_ID, KALSHI_DEMO_PRIVATE_KEY       (demo-api.kalshi.co)
//   POLYMARKET_KEY_ID, POLYMARKET_SECRET_KEY          (Polymarket US)
//
// Nothing is ever sent unless bet_settings.live_betting_on is true, which only Caden sets.

export const KALSHI_BASE = {
  prod: "https://api.elections.kalshi.com/trade-api/v2",
  demo: "https://demo-api.kalshi.co/trade-api/v2",
};
export const POLY_GATEWAY = "https://gateway.polymarket.us";
// Polymarket US docs don't say whether a BUY_SHORT price is the NO price or the YES price.
// Until a preview order confirms it, Polymarket US can only ever dry-run.
export const POLY_LIVE_VERIFIED = false;
const MAX_UNFILLED_TRIES = 3;
const HEARTBEAT_MINUTES = 15;
const LIVE_STATUSES = ["pending", "filled", "partial", "error"];

// ------------------------------------------------------------------ types
export type Settings = {
  live_betting_on: boolean;
  kalshi_env: "demo" | "prod";
  venues: string[];
  stake_dollars: number;
  to_win_dollars?: number | null;    // when set, every bet is sized to win this much (after fees)
  daily_loss_cap: number;
  max_open_bets: number;
  max_dollars_per_game: number;
  min_ev: number;
  max_feed_age_minutes: number;
  run_token: string;
  last_heartbeat?: string | null;
};

export type Quote = {
  venue: string; venue_name?: string; contract: string; side: string; ml?: boolean; line: number;
  price?: number | null; american?: number | null; cost: number; win: number; ev: number; max_cost: number;
  ticker?: string | null; order_side?: string | null; size?: number | null;
};

export type FeedRow = {
  key: string; status: string; updated_at: string; game_id: string; tip_utc: string; away: string; home: string;
  system: string; pick: string; bet: string; side: string; quotes: Quote[];
};

export type OrderRow = {
  id?: string; created_at?: string; mode: "dry_run" | "live"; env: string; venue: string; market: string;
  order_side: string; bet_key: string; game_id: string; tip_utc: string; pick: string; system: string;
  contract: string; line: number; model_price: number; ask_at_check: number; limit_price: number; count: number;
  stake: number; est_fee: number; ev: number; status: string; reason?: string | null; order_id?: string | null;
  fill_count?: number | null; fill_cost?: number | null; fees?: number | null; response?: unknown;
  seen_count?: number;
};

export interface Db {
  settings(): Promise<Settings>;
  updateSettings(patch: Record<string, unknown>): Promise<void>;
  feed(minUpdatedIso: string, minTipIso: string): Promise<FeedRow[]>;
  orders(sinceIso: string): Promise<OrderRow[]>;
  insertOrder(row: OrderRow): Promise<{ id?: string; conflict?: boolean }>;
  updateOrder(id: string, patch: Partial<OrderRow>): Promise<void>;
  updateFeed(key: string, patch: Record<string, unknown>): Promise<void>;
  log(level: string, message: string, data?: unknown): Promise<void>;
}

export interface Venue {
  name: string;
  hasKeys: boolean;
  /** current ask for buying this side, in dollars (null = nothing to buy) */
  ask(q: Quote, row: FeedRow): Promise<{ ask: number | null; market: string; detail?: unknown }>;
  fee(price: number, count: number): number;
  balance(): Promise<number>;
  /** realized P&L today on the given markets (negative = loss) */
  pnlToday(markets: Set<string>, dayStartMs: number): Promise<number>;
  order(o: OrderRow, clientId: string): Promise<{ order_id: string; fill_count: number; fill_cost: number; fees: number; raw: unknown }>;
}

// ------------------------------------------------------------------ money math
/** Kalshi taker fee for a whole order: 7% × C × P × (1−P), rounded up to the cent. */
export function kalshiFee(p: number, count: number): number {
  return Math.ceil(0.07 * count * p * (1 - p) * 100 - 1e-9) / 100;
}

/** Polymarket US taker fee: 0.0695 × C × p × (1−p), banker's rounding to the cent. */
export function polyFee(p: number, count: number): number {
  const cents = 6.95 * count * p * (1 - p);
  const fl = Math.floor(cents), diff = cents - fl;
  const r = Math.abs(diff - 0.5) < 1e-9 ? (fl % 2 === 0 ? fl : fl + 1) : Math.round(cents);
  return r / 100;
}

/** Fewest contracts that win at least `toWin` dollars after the fee, buying at `price`. */
export function contractsToWin(price: number, toWin: number, fee: (p: number, c: number) => number): number {
  let c = Math.max(1, Math.ceil(toWin / (1 - price) - 1e-9));
  while (c * (1 - price) - fee(price, c) < toWin - 1e-9 && c < 100000) c++;
  return c;
}

/** Expected return per $1 at an all-in cost per contract, from the model's win and break-even cost. */
export function evAt(q: Quote, costPerContract: number): number {
  const push = Math.max(0, 1 - q.win / q.max_cost);
  return q.win * (1 / costPerContract - 1) - (1 - q.win - push);
}

/** The price the model saw for this quote (what the limit order is capped at). */
export function modelPrice(q: Quote): number {
  return q.venue === "kalshi" ? Number(q.price) : Number(q.cost);
}

export function etDayStart(now: Date): Date {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const get = (t: string) => Number(parts.find((p) => p.type === t)!.value);
  const etNowAsUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  const offset = etNowAsUtc - Math.floor(now.getTime() / 1000) * 1000;   // ET minus UTC
  return new Date(Date.UTC(get("year"), get("month") - 1, get("day")) - offset);
}

// ------------------------------------------------------------------ the run
export type RunResult = { mode: string; actions: string[]; skips: { pick: string; reason: string }[]; stopped?: string };

export async function runOnce(db: Db, venues: Record<string, Venue>, now = new Date()): Promise<RunResult> {
  const s = await db.settings();
  const live = !!s.live_betting_on;
  const mode = live ? "live" : "dry_run";
  const res: RunResult = { mode, actions: [], skips: [] };
  const on = (s.venues || []).filter((v) => venues[v]);

  // Rule 3: daily loss cap (only meaningful once real orders exist)
  const dayStart = etDayStart(now);
  const recent = await db.orders(new Date(now.getTime() - 4 * 86400e3).toISOString());
  if (live) {
    let pnl = 0;
    for (const v of on) {
      const mine = new Set(recent.filter((o) => o.mode === "live" && o.venue === v && (o.fill_count ?? 0) > 0)
        .map((o) => o.market));
      if (!mine.size) continue;
      try {
        pnl += await venues[v].pnlToday(mine, dayStart.getTime());
      } catch (e) {
        res.stopped = `could not check today's P&L on ${v}: ${msg(e)}`;
        await db.log("error", `Stopped this run: ${res.stopped}`);
        return res;
      }
    }
    if (pnl <= -Math.abs(s.daily_loss_cap)) {
      const why = `Daily loss cap hit: today's P&L ${money(pnl)} vs cap ${money(-s.daily_loss_cap)}. Live betting switched OFF.`;
      await db.updateSettings({ live_betting_on: false, disabled_reason: why });
      await db.log("warn", why, { pnl });
      res.stopped = why;
      return res;
    }
  }

  const minUpdated = new Date(now.getTime() - s.max_feed_age_minutes * 60e3).toISOString();
  const minTip = new Date(now.getTime() + 2 * 60e3).toISOString();
  const feed = (await db.feed(minUpdated, minTip)).filter((r) => r.status === "bet");

  // what's already committed (live), or — in a dry run — what the dry run has "placed" today
  const counted = recent.filter((o) =>
    live ? o.mode === "live" && ["pending", "filled", "partial"].includes(o.status)
         : o.mode === "dry_run" && (o.created_at ?? "") >= dayStart.toISOString());
  const openNow = () => counted.filter((o) => (o.tip_utc ?? "") > new Date(now.getTime() - 4 * 3600e3).toISOString());
  const gameDollars = (g: string) => counted.filter((o) => o.game_id === g)
    .reduce((t, o) => t + (o.fill_cost ?? o.stake ?? 0), 0);

  for (const row of feed.sort((a, b) => best(b) - best(a))) {
    const skip = (reason: string) => res.skips.push({ pick: `${row.pick} (${row.system}) ${row.away}@${row.home}`, reason });

    // Rule 5: never the same bet twice (live). A bet that errored is never retried automatically.
    const liveForBet = recent.filter((o) => o.mode === "live" && o.bet_key === row.key && LIVE_STATUSES.includes(o.status));
    if (live && liveForBet.length) { skip(`already ${liveForBet[0].status} (${liveForBet[0].venue})`); continue; }

    const quotes = (row.quotes || []).filter((q) => on.includes(q.venue) && q.ev >= s.min_ev &&
      (q.venue !== "kalshi" || (q.ticker && q.order_side)) && (q.venue !== "polymarket_us" || q.ml))
      .sort((a, b) => b.ev - a.ev);
    if (!quotes.length) { skip(`no quote on ${on.join("/") || "any switched-on venue"} with expected return ≥ ${pct(s.min_ev)}`); continue; }

    let done = false;
    const why: string[] = [];
    for (const q of quotes) {
      const v = venues[q.venue];
      const seen = modelPrice(q);
      let chk;
      try {
        chk = await v.ask(q, row);
      } catch (e) {
        why.push(`${v.name}: price check failed (${msg(e)})`);
        continue;
      }
      const market = chk.market;
      // Rule 5: never the same market twice
      const marketTaken = recent.find((o) => o.mode === "live" && o.venue === q.venue && o.market === market &&
        LIVE_STATUSES.includes(o.status));
      if (live && marketTaken) { why.push(`${v.name} ${market}: already ${marketTaken.status}`); continue; }
      const unfilled = recent.filter((o) => o.mode === "live" && o.venue === q.venue && o.market === market && o.status === "unfilled");
      if (live && unfilled.length >= MAX_UNFILLED_TRIES) { why.push(`${v.name} ${market}: ${unfilled.length} unfilled tries already`); continue; }

      // a dry run that already logged this bet just refreshes it (no duplicate "would have placed")
      const prior = live ? undefined
        : recent.find((o) => o.mode === "dry_run" && o.venue === q.venue && o.market === market && o.bet_key === row.key);
      if (prior?.id && chk.ask != null) {
        await db.updateOrder(prior.id, { ask_at_check: chk.ask, seen_count: (prior.seen_count ?? 1) + 1 });
        done = true;
        break;
      }

      // Rule 6: re-check the ask; never pay more than the model saw
      const ask = chk.ask;
      if (ask == null || ask <= 0 || ask >= 0.99) { why.push(`${v.name} ${q.contract}: nothing to buy right now`); continue; }
      if (ask > seen + 1e-9) { why.push(`${v.name} ${q.contract}: ask ${cents(ask)} moved above the model's ${cents(seen)}`); continue; }

      // Rule 2: same size every bet — to win a fixed amount (default), or a fixed stake
      const limit = round4(seen);
      const count = s.to_win_dollars && s.to_win_dollars > 0
        ? contractsToWin(limit, s.to_win_dollars, (p, c) => v.fee(p, c))
        : Math.floor(s.stake_dollars / limit + 1e-9);
      if (count < 1) { why.push(`stake ${money(s.stake_dollars)} buys less than one contract at ${cents(limit)}`); continue; }
      const stake = round2(count * limit);
      const fee = v.fee(limit, count);
      const evNow = evAt(q, (stake + fee) / count);
      if (evNow < s.min_ev) { why.push(`${v.name} ${q.contract}: only ${pct(evNow)} after fees`); continue; }

      // Rule 4: open bets and dollars per game
      if (openNow().length >= s.max_open_bets) { why.push(`max open bets (${s.max_open_bets}) reached`); break; }
      if (gameDollars(row.game_id) + stake > s.max_dollars_per_game + 1e-9) {
        why.push(`would put ${money(gameDollars(row.game_id) + stake)} on this game (max ${money(s.max_dollars_per_game)})`); break;
      }

      const order: OrderRow = {
        mode, env: q.venue === "kalshi" ? s.kalshi_env : "prod", venue: q.venue, market, order_side: orderSide(q),
        bet_key: row.key, game_id: row.game_id, tip_utc: row.tip_utc, pick: row.pick, system: row.system,
        contract: q.contract, line: q.line, model_price: seen, ask_at_check: ask, limit_price: limit, count,
        stake, est_fee: fee, ev: round4(evNow), status: live ? "pending" : "dry_run",
      };
      const text = `${q.venue_name ?? v.name} BUY ${order.order_side.toUpperCase()} ×${count} ${market} at ${cents(limit)} ` +
        `(stake ${money(stake)} + fee ${money(fee)}) — ${row.pick} via ${q.contract}, ${row.system}, ` +
        `${row.away} @ ${row.home}, expected return ${pct(evNow)}`;

      if (!live) {
        const ins = await db.insertOrder({ ...order, reason: "dry run: nothing sent" });
        await db.log("info", `WOULD HAVE PLACED: ${text}`, { ...order, id: ins.id });
        res.actions.push(`would have placed: ${text}`);
        counted.push({ ...order, created_at: now.toISOString() });
        done = true;
        break;
      }

      // live: Polymarket US stays dry until its NO-side price is verified
      if (q.venue === "polymarket_us" && !POLY_LIVE_VERIFIED) {
        why.push("Polymarket US is dry-run only until a preview order confirms how NO prices work");
        continue;
      }
      if (!v.hasKeys) { why.push(`${v.name}: no API keys in Supabase secrets`); continue; }
      try {
        const bal = await v.balance();
        if (bal < stake + fee) { why.push(`${v.name} balance ${money(bal)} is under ${money(stake + fee)}`); continue; }
      } catch (e) {
        why.push(`${v.name}: balance check failed (${msg(e)})`);
        continue;
      }
      // claim the market first — the unique index makes a second run's claim fail, so no double bet
      const ins = await db.insertOrder(order);
      if (ins.conflict || !ins.id) { why.push(`${v.name} ${market}: another run already claimed it`); continue; }
      try {
        const r = await v.order(order, ins.id);
        const status = r.fill_count >= count ? "filled" : r.fill_count > 0 ? "partial" : "unfilled";
        await db.updateOrder(ins.id, { status, order_id: r.order_id, fill_count: r.fill_count, fill_cost: r.fill_cost,
          fees: r.fees, response: r.raw, reason: status === "unfilled" ? "immediate-or-cancel: nothing filled at the limit" : null });
        await db.updateFeed(row.key, { order_status: status, order_venue: q.venue, order_id: r.order_id,
          order_fill_count: r.fill_count, order_fill_cost: r.fill_cost, order_placed_at: now.toISOString() });
        await db.log(status === "unfilled" ? "warn" : "info", `${status.toUpperCase()}: ${text}`,
          { order_id: r.order_id, fill_count: r.fill_count, fill_cost: r.fill_cost, fees: r.fees });
        res.actions.push(`${status}: ${text}`);
        if (r.fill_count > 0) counted.push({ ...order, status, fill_cost: r.fill_cost });
        done = status !== "unfilled";
      } catch (e) {
        // Rule 7: log it and never retry blindly — the row stays 'error' and blocks this market
        await db.updateOrder(ins.id, { status: "error", reason: msg(e) });
        await db.updateFeed(row.key, { order_status: "error", order_venue: q.venue });
        await db.log("error", `ORDER FAILED (not retried): ${text}: ${msg(e)}`);
        res.actions.push(`error: ${text}: ${msg(e)}`);
        done = true;
      }
      break;
    }
    if (!done) skip(why.join("; ") || "no quote passed the checks");
  }

  const last = s.last_heartbeat ? Date.parse(s.last_heartbeat) : 0;
  if (res.actions.length || now.getTime() - last >= HEARTBEAT_MINUTES * 60e3) {
    await db.log("info", `run (${mode}${live ? ", " + s.kalshi_env : ""}): ${feed.length} bets on the card, ` +
      `${res.actions.length} action(s), ${res.skips.length} skipped`, { skips: res.skips });
    await db.updateSettings({ last_heartbeat: now.toISOString() });
  }
  return res;
}

function best(r: FeedRow) {
  return Math.max(-1, ...(r.quotes || []).map((q) => q.ev ?? -1));
}
function orderSide(q: Quote) {
  if (q.venue === "kalshi") return String(q.order_side);
  return q.order_side ? String(q.order_side) : "long";
}
const round2 = (x: number) => Math.round(x * 100) / 100;
const round4 = (x: number) => Math.round(x * 10000) / 10000;
const cents = (x: number) => `${Math.round(x * 100)}¢`;
const money = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toFixed(2)}`;
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e)).slice(0, 400);

// ------------------------------------------------------------------ Kalshi
function b64ToBytes(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}
function bytesToB64(b: ArrayBuffer): string {
  let s = "";
  for (const x of new Uint8Array(b)) s += String.fromCharCode(x);
  return btoa(s);
}
function derLen(n: number): number[] {
  if (n < 0x80) return [n];
  const out: number[] = [];
  while (n > 0) { out.unshift(n & 0xff); n >>= 8; }
  return [0x80 | out.length, ...out];
}
/** RSA "BEGIN RSA PRIVATE KEY" (PKCS#1) → PKCS#8, which Web Crypto can import. */
export function pkcs1ToPkcs8(pkcs1: Uint8Array): Uint8Array {
  const algId = [0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00];
  const octet = [0x04, ...derLen(pkcs1.length), ...pkcs1];
  const body = [0x02, 0x01, 0x00, ...algId, ...octet];
  return new Uint8Array([0x30, ...derLen(body.length), ...body]);
}

export type Signer = (message: string) => Promise<string>;

/** Ed25519 (Kalshi's default) or RSA-PSS SHA-256 with a 32-byte salt — detected from the key itself. */
export async function kalshiSigner(pem: string): Promise<Signer> {
  const text = pem.replace(/\\n/g, "\n").trim();
  const der = b64ToBytes(text.replace(/-----[^-]+-----/g, "").replace(/\s+/g, ""));
  const enc = new TextEncoder();
  if (text.includes("BEGIN RSA PRIVATE KEY")) return rsa(pkcs1ToPkcs8(der));
  try {
    const key = await crypto.subtle.importKey("pkcs8", der as BufferSource, { name: "Ed25519" }, false, ["sign"]);
    return async (m) => bytesToB64(await crypto.subtle.sign({ name: "Ed25519" }, key, enc.encode(m)));
  } catch {
    return rsa(der);
  }
  async function rsa(pkcs8: Uint8Array): Promise<Signer> {
    const key = await crypto.subtle.importKey("pkcs8", pkcs8 as BufferSource, { name: "RSA-PSS", hash: "SHA-256" }, false, ["sign"]);
    return async (m) => bytesToB64(await crypto.subtle.sign({ name: "RSA-PSS", saltLength: 32 }, key, enc.encode(m)));
  }
}

export class Kalshi implements Venue {
  name = "Kalshi";
  constructor(private base: string, private keyId: string | undefined, private signer: Signer | undefined,
              private dataBase = base, private http: typeof fetch = fetch) {}
  get hasKeys() { return !!(this.keyId && this.signer); }

  private async call(method: string, path: string, body?: unknown, auth = true, base = this.base) {
    const url = base + path;
    const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "application/json" };
    if (auth) {
      if (!this.keyId || !this.signer) throw new Error("no Kalshi API keys in Supabase secrets");
      const ts = String(Date.now());
      headers["KALSHI-ACCESS-KEY"] = this.keyId;
      headers["KALSHI-ACCESS-TIMESTAMP"] = ts;
      headers["KALSHI-ACCESS-SIGNATURE"] = await this.signer(ts + method + new URL(url).pathname);
    }
    const r = await this.http(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const txt = await r.text();
    if (!r.ok) throw new Error(`Kalshi ${method} ${new URL(url).pathname} → ${r.status}: ${txt.slice(0, 300)}`);
    return txt ? JSON.parse(txt) : {};
  }

  async ask(q: Quote) {
    // dry runs read real (prod) prices; live reads the exchange the order goes to
    const js = await this.call("GET", `/markets/${q.ticker}`, undefined, false, this.dataBase);
    const m = js.market || {};
    const raw = q.order_side === "no" ? m.no_ask_dollars : m.yes_ask_dollars;
    const ask = raw == null ? null : Number(raw);
    return { ask: m.status && !["active", "open"].includes(m.status) ? null : ask, market: String(q.ticker), detail: m };
  }
  fee(p: number, c: number) { return kalshiFee(p, c); }
  async balance() {
    const js = await this.call("GET", "/portfolio/balance");
    return js.balance_dollars != null ? Number(js.balance_dollars) : Number(js.balance) / 100;
  }
  async pnlToday(markets: Set<string>, dayStartMs: number) {
    let cursor = "", pnl = 0;
    for (let page = 0; page < 20; page++) {
      const js = await this.call("GET",
        `/portfolio/settlements?limit=1000&min_ts=${Math.floor(dayStartMs / 1000)}${cursor ? "&cursor=" + cursor : ""}`);
      for (const st of js.settlements || []) {
        if (!markets.has(st.ticker)) continue;
        pnl += Number(st.revenue || 0) / 100 - Number(st.yes_total_cost_dollars || 0) -
          Number(st.no_total_cost_dollars || 0) - Number(st.fee_cost || 0);
      }
      cursor = js.cursor || "";
      if (!cursor) break;
    }
    return pnl;
  }
  async order(o: OrderRow, clientId: string) {
    const body: Record<string, unknown> = {
      ticker: o.market, side: o.order_side, action: "buy", count: o.count, type: "limit",
      time_in_force: "immediate_or_cancel", client_order_id: clientId,
    };
    body[o.order_side === "no" ? "no_price_dollars" : "yes_price_dollars"] = o.limit_price.toFixed(4);
    const js = await this.call("POST", "/portfolio/orders", body);
    const ord = js.order || {};
    const fill = Number(ord.fill_count ?? ord.fill_count_fp ?? 0);
    const cost = ord.taker_fill_cost_dollars != null ? Number(ord.taker_fill_cost_dollars)
      : Number(ord.taker_fill_cost ?? 0) / 100;
    const fees = ord.taker_fees_dollars != null ? Number(ord.taker_fees_dollars) : Number(ord.taker_fees ?? 0) / 100;
    if (!ord.order_id) throw new Error(`Kalshi returned no order id: ${JSON.stringify(js).slice(0, 300)}`);
    return { order_id: String(ord.order_id), fill_count: fill, fill_cost: cost, fees, raw: ord };
  }
}

// ------------------------------------------------------------------ Polymarket US (dry run until verified)
const POLY_ALIASES: Record<string, string> = {
  NY: "NYK", SA: "SAS", GS: "GSW", NO: "NOP", UTAH: "UTA", WSH: "WAS", PHO: "PHX", BRK: "BKN", CHO: "CHA",
};
export const polyCode = (abbr: string) => POLY_ALIASES[abbr.toUpperCase()] ?? abbr.toUpperCase();

export class PolymarketUS implements Venue {
  name = "Polymarket US";
  private events: any[] | null = null;
  constructor(private keyId?: string, private secret?: string, private http: typeof fetch = fetch) {}
  get hasKeys() { return !!(this.keyId && this.secret); }

  private async gw(path: string) {
    const r = await this.http(POLY_GATEWAY + path, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`Polymarket ${path} → ${r.status}`);
    return r.json();
  }
  /** the game's moneyline market, and whether our team is its long (YES) side */
  async findMarket(row: FeedRow, team: string) {
    this.events ??= (await this.gw("/v2/leagues/nba/events?limit=200")).events || [];
    for (const ev of this.events!) {
      const codes = (ev.teams || []).map((t: any) => polyCode(t.displayAbbreviation || t.abbreviation || ""));
      if (!(codes.includes(row.away) && codes.includes(row.home))) continue;
      if (Math.abs(Date.parse(ev.startDate) - Date.parse(row.tip_utc)) > 6 * 3600e3) continue;
      for (const m of ev.markets || []) {
        if (m.sportsMarketType !== "basketball_team_full_game_winner") continue;
        for (const sd of m.marketSides || []) {
          const c = polyCode(sd.team?.displayAbbreviation || sd.team?.abbreviation || "");
          if (c === team) return { slug: String(m.slug), long: !!sd.long };
        }
      }
    }
    return null;
  }
  async ask(q: Quote, row: FeedRow) {
    const mk = await this.findMarket(row, q.side);
    if (!mk) return { ask: null, market: `nba ${row.away}@${row.home} moneyline (not listed)` };
    q.order_side = mk.long ? "long" : "short";
    const bbo = (await this.gw(`/v1/markets/${mk.slug}/bbo`)).marketData || {};
    const quote = mk.long ? bbo.longQuote : bbo.shortQuote;
    return { ask: quote?.value != null ? Number(quote.value) : null, market: mk.slug, detail: bbo };
  }
  fee(p: number, c: number) { return polyFee(p, c); }
  async balance(): Promise<number> { throw new Error("Polymarket US live orders are not enabled yet"); }
  async pnlToday(): Promise<number> { throw new Error("Polymarket US live orders are not enabled yet"); }
  async order(): Promise<never> { throw new Error("Polymarket US live orders are not enabled yet"); }
}

// ------------------------------------------------------------------ Supabase wiring
// deno-lint-ignore no-explicit-any
export function supabaseDb(sb: any): Db {
  const must = (r: { error: unknown; data?: unknown }) => {
    if (r.error) throw new Error(JSON.stringify(r.error));
    return r.data;
  };
  return {
    async settings() { return must(await sb.from("bet_settings").select("*").eq("id", 1).single()) as Settings; },
    async updateSettings(p) { must(await sb.from("bet_settings").update({ ...p, updated_at: new Date().toISOString() }).eq("id", 1)); },
    async feed(minUpdated, minTip) {
      return must(await sb.from("bet_feed").select("*").eq("status", "bet").gte("updated_at", minUpdated)
        .gte("tip_utc", minTip)) as FeedRow[];
    },
    async orders(since) { return must(await sb.from("bet_orders").select("*").gte("created_at", since)) as OrderRow[]; },
    async insertOrder(row) {
      const r = await sb.from("bet_orders").insert(row).select("id").single();
      if (r.error?.code === "23505") return { conflict: true };
      return { id: (must(r) as { id: string }).id };
    },
    async updateOrder(id, p) { must(await sb.from("bet_orders").update({ ...p, updated_at: new Date().toISOString() }).eq("id", id)); },
    async updateFeed(key, p) { must(await sb.from("bet_feed").update(p).eq("key", key)); },
    async log(level, message, data) { await sb.from("bet_log").insert({ level, message, data: data ?? null }); },
  };
}

export async function buildVenues(s: Settings): Promise<Record<string, Venue>> {
  const env = s.kalshi_env === "prod" ? "prod" : "demo";
  const keyId = Deno.env.get(env === "prod" ? "KALSHI_KEY_ID" : "KALSHI_DEMO_KEY_ID");
  const pem = Deno.env.get(env === "prod" ? "KALSHI_PRIVATE_KEY" : "KALSHI_DEMO_PRIVATE_KEY");
  const signer = keyId && pem ? await kalshiSigner(pem) : undefined;
  const dataBase = s.live_betting_on ? KALSHI_BASE[env] : KALSHI_BASE.prod;
  return {
    kalshi: new Kalshi(KALSHI_BASE[env], keyId, signer, dataBase),
    polymarket_us: new PolymarketUS(Deno.env.get("POLYMARKET_KEY_ID"), Deno.env.get("POLYMARKET_SECRET_KEY")),
  };
}
