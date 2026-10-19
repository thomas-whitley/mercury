import psycopg

from app.migrations import apply_migrations

CORE_TABLES = {"runs", "steps", "events", "chunks"}


def table_names(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return {row[0] for row in rows}


def test_migrations_create_the_core_tables(clean_db):
    apply_migrations(clean_db)

    assert CORE_TABLES <= table_names(clean_db)


def test_applying_migrations_twice_is_a_no_op(clean_db):
    applied_first = apply_migrations(clean_db)
    applied_again = apply_migrations(clean_db)

    assert applied_first, "the first run should apply at least one migration"
    assert applied_again == []
    assert CORE_TABLES <= table_names(clean_db)


def test_017_adds_review_notes_and_the_review_note_source(clean_db):
    apply_migrations(clean_db)

    assert "review_notes" in table_names(clean_db)
    with psycopg.connect(clean_db, autocommit=True) as conn:
        run_id = conn.execute(
            "INSERT INTO runs (task, type, provider, source) "
            "VALUES ('t', 'repo_chore', 'gemini', 'review_note') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO review_notes (note_id, host, page, note_updated_at, state, run_id) "
            "VALUES (1, 'h', '/p/', 'now', 'chore', %s)",
            (run_id,),
        )
        conn.execute("DELETE FROM runs WHERE id = %s", (run_id,))
        assert conn.execute("SELECT run_id FROM review_notes").fetchone() == (None,)
