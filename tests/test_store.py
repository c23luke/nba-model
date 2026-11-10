"""Rows sent to Supabase must match the table columns exactly and share the same keys."""
from engine.store import shape, COLUMNS


def test_shape_drops_unknown_and_fills_missing():
    rows = shape("picks", [{"key": "a", "system": 201, "tag": "E1", "group": "EARLY"},
                           {"key": "b", "result": "W", "dropped_reason": "line moved"}])
    assert all(list(r) == COLUMNS["picks"] for r in rows)
    assert rows[0]["system"] == 201 and rows[1]["result"] == "W" and rows[0]["result"] is None


def test_schema_file_has_every_column():
    sql = open("supabase/schema.sql").read()
    for table, cols in COLUMNS.items():
        block = sql.split(f"create table if not exists {table}")[1].split(");")[0]
        for c in cols:
            assert f"\n  {c} " in block, f"{table}.{c} missing from schema.sql"


def test_picks_are_read_from_supabase_at_most_every_30_minutes_and_keep_what_we_saved():
    # egress (2026-11-10): picks were downloaded in full twice every run
    from engine.store import SupabaseStore
    calls = []

    class Fake(SupabaseStore):
        def _all(self, table):
            calls.append(table)
            return [{"key": "a", "system": 1, "meta": {"x": 1}}]

        def _upsert(self, table, rows, conflict):
            pass

    st = Fake("https://x.supabase.co", "sb_test")
    assert [p["key"] for p in st.load_picks()] == ["a"]
    st.save_picks([{"key": "b", "system": 2, "meta": {}}])
    assert sorted(p["key"] for p in st.load_picks()) == ["a", "b"] and calls == ["picks"]
    st.load_picks()[0]["meta"]["x"] = 99                               # callers can't change the cache
    assert st.load_picks()[0]["meta"] == {"x": 1}
    st._pk_cache = (st._pk_cache[0] - 1801, st._pk_cache[1])
    st.load_picks()
    assert calls == ["picks", "picks"]
