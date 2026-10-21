// place-bets entry point. All logic lives in core.ts (tested in core_test.ts).
import { createClient } from "npm:@supabase/supabase-js@2.45.4";
import { buildVenues, keyCheck, runOnce, supabaseDb } from "./core.ts";

Deno.serve(async (req) => {
  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } });
  const db = supabaseDb(sb);
  try {
    const s = await db.settings();
    if (req.headers.get("x-run-token") !== String(s.run_token)) return new Response("forbidden", { status: 403 });
    const out = await runOnce(db, await buildVenues(s), new Date(), keyCheck());
    return new Response(JSON.stringify(out), { headers: { "Content-Type": "application/json" } });
  } catch (e) {
    const m = (e instanceof Error ? e.message : String(e)).slice(0, 400);
    await db.log("error", `run crashed: ${m}`).catch(() => {});
    return new Response(JSON.stringify({ error: m }), { status: 500 });
  }
});
