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
