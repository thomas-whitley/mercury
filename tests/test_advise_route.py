"""POST /runs/{id}/advise: the same advise as MCP and Telegram, over HTTP, so
the eval runner can send a Claude session's hint (Phase 3 of
docs/build-brief-evals.md). It may name the rerun's provider (decision 48)."""

import httpx2
import psycopg
import pytest
import yaml
from psycopg.types.json import Jsonb

TOKEN = "test-bearer-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
REPO = "thomas-whitley/mercury-fixture"


@pytest.fixture
def api(start_server, monkeypatch, tmp_path):
    config = tmp_path / "mercury.yaml"
    config.write_text(
        yaml.dump({"portfolio": {"repos": [{"name": REPO, "test_command": "true"}]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", TOKEN)
    return start_server()


def chore(database_url: str, status: str = "escalated", source: str = "api") -> str:
    with psycopg.connect(database_url, autocommit=True) as conn:
        run_id = str(
            conn.execute(
                "INSERT INTO runs (task, type, provider, repo, status, source, finished_at) "
                "VALUES ('Add divide to calc.py', 'repo_chore', 'gemini', %s, %s, %s, now()) "
                "RETURNING id",
                (REPO, status, source),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO steps (run_id, seq, kind, output) VALUES (%s, 1, 'done', %s)",
            (run_id, Jsonb({"status": status, "diff": "+x\n"})),
        )
    return run_id


def rerun(database_url: str, run_id: str) -> tuple:
    with psycopg.connect(database_url) as conn:
        return conn.execute(
            "SELECT status, hint, source, provider, source_run_id::text FROM runs WHERE id = %s",
            (run_id,),
        ).fetchone()


def test_an_escalated_chore_is_advised_over_http(api, clean_db):
    run_id = chore(clean_db)

    response = httpx2.post(
        f"{api}/runs/{run_id}/advise", json={"hint": "Use float division."}, headers=HEADERS
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert rerun(clean_db, body["id"]) == (
        "pending",
        "Use float division.",
        "api",
        "gemini",
        run_id,
    )


def test_advice_without_the_bearer_is_refused_and_queues_nothing(api, clean_db):
    run_id = chore(clean_db)

    response = httpx2.post(f"{api}/runs/{run_id}/advise", json={"hint": "x"})

    assert response.status_code == 401
    with psycopg.connect(clean_db) as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone() == (1,)


def test_advice_on_a_running_chore_is_a_422_that_says_why(api, clean_db):
    run_id = chore(clean_db, status="running")

    response = httpx2.post(f"{api}/runs/{run_id}/advise", json={"hint": "x"}, headers=HEADERS)

    assert response.status_code == 422
    assert "escalated" in response.json()["detail"]


@pytest.mark.parametrize("provider", ["nope", "haiku"])
def test_an_unknown_or_paid_provider_is_a_422(api, clean_db, provider):
    run_id = chore(clean_db)

    response = httpx2.post(
        f"{api}/runs/{run_id}/advise", json={"hint": "x", "provider": provider}, headers=HEADERS
    )

    assert response.status_code == 422


def test_an_eval_chore_is_rerun_quietly_on_the_column_named(api, clean_db):
    run_id = chore(clean_db, status="succeeded", source="eval")

    response = httpx2.post(
        f"{api}/runs/{run_id}/advise",
        json={"hint": "Name it divide.", "provider": "ollama"},
        headers=HEADERS,
    )

    assert response.status_code == 201
    status, _, source, provider, _ = rerun(clean_db, response.json()["id"])
    assert (status, source, provider) == ("pending", "eval", "ollama")
