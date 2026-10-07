"""POST /telegram: the secret header first, then the one allowed chat, then
the commands that need no model. Everyone else gets no reply at all."""

import httpx2
import pytest
import yaml

from app.runs import claim_run, heartbeat, record_step

SECRET = "webhook-secret"
CHAT = 42
SITE = "https://site.example/health"


@pytest.fixture
def bot(start_server, fake_telegram, monkeypatch, tmp_path):
    config = tmp_path / "mercury.yaml"
    config.write_text(yaml.dump({"telegram": {"chat_id": CHAT}, "portfolio": {"sites": [SITE]}}))
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    return start_server()


def update(text: str, chat_id: int = CHAT) -> dict:
    return {
        "update_id": 1,
        "message": {"message_id": 10, "chat": {"id": chat_id, "type": "private"}, "text": text},
    }


def post(base_url: str, body: dict, secret: str | None = SECRET) -> httpx2.Response:
    headers = {} if secret is None else {"X-Telegram-Bot-Api-Secret-Token": secret}
    return httpx2.post(f"{base_url}/telegram", json=body, headers=headers)


def replies(fake_telegram) -> list[str]:
    return [payload["text"] for payload in fake_telegram.sent()]


def insert_run(conn, task="def test_x(): pass", type_="pytest", status="pending") -> str:
    return str(
        conn.execute(
            "INSERT INTO runs (task, type, status) VALUES (%s, %s, %s) RETURNING id",
            (task, type_, status),
        ).fetchone()[0]
    )


@pytest.mark.parametrize("secret", [None, "wrong"])
def test_a_request_without_the_secret_is_refused(bot, fake_telegram, secret):
    response = post(bot, update("/runs"), secret=secret)

    assert response.status_code == 401
    assert fake_telegram.calls == []


def test_an_unconfigured_secret_refuses_everyone(
    start_server, fake_telegram, monkeypatch, tmp_path
):
    config = tmp_path / "mercury.yaml"
    config.write_text(yaml.dump({"telegram": {"chat_id": CHAT}}))
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    base_url = start_server()

    assert post(base_url, update("/runs"), secret="").status_code == 401
    assert fake_telegram.calls == []


def test_another_chat_gets_no_reply_at_all(bot, fake_telegram, migrated_db):
    response = post(bot, update("/runs", chat_id=99))

    assert response.status_code == 200
    assert fake_telegram.calls == []


def test_an_update_that_is_not_a_text_message_gets_no_reply(bot, fake_telegram):
    response = post(bot, {"update_id": 2, "edited_message": {"chat": {"id": CHAT}}})

    assert response.status_code == 200
    assert fake_telegram.calls == []


def test_runs_lists_the_latest_runs_newest_first(bot, fake_telegram, migrated_db):
    first = insert_run(migrated_db)
    second = insert_run(migrated_db, task=SITE, type_="site_check", status="succeeded")

    post(bot, update("/runs"))

    [reply] = replies(fake_telegram)
    assert reply.index(second[:8]) < reply.index(first[:8])
    assert "site_check" in reply and "succeeded" in reply


def test_runs_with_none_says_so(bot, fake_telegram, migrated_db):
    post(bot, update("/runs"))

    assert replies(fake_telegram) == ["No runs yet."]


def test_status_reports_each_site_and_the_day(bot, fake_telegram, migrated_db):
    migrated_db.execute(
        "INSERT INTO runs (task, type, check_kind, status, finished_at) "
        "VALUES (%s, 'site_check', 'uptime', 'failed', now())",
        (SITE,),
    )
    migrated_db.execute(
        "INSERT INTO schedule_state (name, consecutive_failures, suspended, suspended_at) "
        "VALUES (%s, 3, true, now())",
        (f"site_uptime:{SITE}",),
    )

    post(bot, update("/status"))

    [reply] = replies(fake_telegram)
    assert SITE in reply
    assert "failed" in reply
    assert "suspended" in reply
    assert "0 of 20" in reply


def test_cancel_closes_an_unfinished_run_and_says_so(bot, fake_telegram, migrated_db):
    run_id = insert_run(migrated_db)

    post(bot, update(f"/cancel {run_id[:8]}"))

    status, finished = migrated_db.execute(
        "SELECT status, finished_at IS NOT NULL FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert (status, finished) == ("cancelled", True)
    [event] = migrated_db.execute(
        "SELECT payload FROM events WHERE run_id = %s", (run_id,)
    ).fetchall()
    assert event[0]["kind"] == "done" and event[0]["output"] == {"status": "cancelled"}
    assert replies(fake_telegram) == [f"Cancelled {run_id[:8]}."]


def test_cancel_stops_a_running_worker_at_its_next_write(bot, fake_telegram, migrated_db):
    run_id = insert_run(migrated_db)
    assert claim_run(migrated_db, run_id, "worker-1")

    post(bot, update(f"/cancel {run_id[:8]}"))

    assert heartbeat(migrated_db, run_id, "worker-1") is False
    assert record_step(migrated_db, run_id, 9, "act", output={}, worker_id="worker-1") is False


@pytest.mark.parametrize(
    "command, expected",
    [
        ("/cancel", "Usage: /cancel <run id or its first 8 characters>"),
        ("/cancel abc", "Usage: /cancel <run id or its first 8 characters>"),
        ("/cancel 00000000", "No unfinished run starts with 00000000."),
    ],
)
def test_cancel_explains_what_it_could_not_do(bot, fake_telegram, migrated_db, command, expected):
    post(bot, update(command))

    assert replies(fake_telegram) == [expected]


def test_cancel_leaves_a_finished_run_alone(bot, fake_telegram, migrated_db):
    run_id = insert_run(migrated_db, status="succeeded")
    migrated_db.execute("UPDATE runs SET finished_at = now() WHERE id = %s", (run_id,))

    post(bot, update(f"/cancel {run_id[:8]}"))

    assert migrated_db.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone() == (
        "succeeded",
    )
    assert replies(fake_telegram) == [f"No unfinished run starts with {run_id[:8]}."]


def test_a_failed_reply_still_answers_telegram_with_200(bot, fake_telegram, migrated_db):
    """A non 200 makes Telegram retry the same update, which would repeat a command."""
    fake_telegram.fail_next = {"error_code": 403, "description": "Forbidden: bot was blocked"}

    response = post(bot, update("/runs"))

    assert response.status_code == 200


def test_each_answer_logs_how_long_after_the_message_was_sent(
    bot, fake_telegram, migrated_db, caplog
):
    """The cold start figure in the README is read off this line on the live
    deploy: Telegram stamps each message with the second it was sent, so the
    first message after idle shows the whole wait."""
    import logging
    import re
    import time

    body = update("/runs")
    body["message"]["date"] = int(time.time()) - 3
    telegram_logger = logging.getLogger("agent_runs.telegram")
    telegram_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("INFO", logger="agent_runs.telegram"):
            post(bot, body)
    finally:
        telegram_logger.removeHandler(caplog.handler)

    match = re.search(r"answered /runs (\d+\.\d) s after it was sent", caplog.text)
    assert match, caplog.text
    assert 3.0 <= float(match.group(1)) < 10.0


# A reply to an escalation message is a hint for that chore (app/advice.py).


@pytest.fixture
def advising_bot(start_server, fake_telegram, monkeypatch, tmp_path):
    config = tmp_path / "mercury.yaml"
    config.write_text(
        yaml.dump(
            {
                "telegram": {"chat_id": CHAT},
                "portfolio": {
                    "sites": [SITE],
                    "repos": [{"name": "owner/fixture", "test_command": "python -m pytest -q"}],
                },
            }
        )
    )
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(config))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    return start_server()


def reply_to(message_id: int, text: str, chat_id: int = CHAT) -> dict:
    body = update(text, chat_id)
    body["message"]["reply_to_message"] = {"message_id": message_id, "text": "earlier"}
    return body


def announced_chore(conn, message_id: int) -> str:
    from tests.test_escalation import escalated_chore

    run_id = escalated_chore(conn, "tests still failing after 3 attempts")
    conn.execute("UPDATE runs SET escalation_message_id = %s WHERE id = %s", (message_id, run_id))
    return run_id


def test_a_reply_to_an_escalation_message_queues_an_advised_rerun(
    advising_bot, fake_telegram, migrated_db
):
    failed = announced_chore(migrated_db, 77)

    post(advising_bot, reply_to(77, "Use float division."))

    row = migrated_db.execute(
        "SELECT id::text, status, source, hint FROM runs WHERE source_run_id = %s", (failed,)
    ).fetchone()
    assert row[1:] == ("pending", "telegram", "Use float division.")
    assert replies(fake_telegram) == [f"Rerunning {failed[:8]} from main with your hint."]
    # The rerun reports on that message, as a chore asked for in chat does, so
    # the owner sees how it ends.
    message = migrated_db.execute(
        "SELECT telegram_chat_id, telegram_message_id FROM runs WHERE id = %s", (row[0],)
    ).fetchone()
    assert message == (CHAT, 1)
    assert migrated_db.execute("SELECT count(*) FROM runs WHERE type = 'chat'").fetchone() == (0,)


def test_a_refused_hint_is_answered_with_why(advising_bot, fake_telegram, migrated_db):
    failed = announced_chore(migrated_db, 77)
    migrated_db.execute("UPDATE runs SET status = 'succeeded' WHERE id = %s", (failed,))

    post(advising_bot, reply_to(77, "Use float division."))

    [answer] = replies(fake_telegram)
    assert "not escalated" in answer
    assert migrated_db.execute("SELECT count(*) FROM runs").fetchone() == (1,)


def test_a_reply_to_any_other_message_is_ordinary_chat(advising_bot, fake_telegram, migrated_db):
    announced_chore(migrated_db, 77)

    post(advising_bot, reply_to(12, "how are my sites?"))

    assert migrated_db.execute("SELECT count(*) FROM runs WHERE type = 'chat'").fetchone() == (1,)
    assert migrated_db.execute("SELECT count(*) FROM runs WHERE hint IS NOT NULL").fetchone() == (
        0,
    )


def test_a_reply_from_another_chat_is_ignored(advising_bot, fake_telegram, migrated_db):
    announced_chore(migrated_db, 77)

    post(advising_bot, reply_to(77, "Use float division.", chat_id=999))

    assert fake_telegram.sent() == []
    assert migrated_db.execute("SELECT count(*) FROM runs").fetchone() == (1,)


def test_slash_hint_advises_the_newest_chore_waiting_for_one(
    advising_bot, fake_telegram, migrated_db
):
    older = announced_chore(migrated_db, 70)
    migrated_db.execute(
        "UPDATE runs SET created_at = now() - interval '1 hour' WHERE id = %s", (older,)
    )
    newest = announced_chore(migrated_db, 77)

    post(advising_bot, update("/hint Use float division."))

    row = migrated_db.execute(
        "SELECT source, hint FROM runs WHERE source_run_id = %s", (newest,)
    ).fetchone()
    assert row == ("telegram", "Use float division.")
    assert replies(fake_telegram) == [f"Rerunning {newest[:8]} from main with your hint."]
    assert migrated_db.execute(
        "SELECT count(*) FROM runs WHERE source_run_id = %s", (older,)
    ).fetchone() == (0,)


def test_slash_hint_with_nothing_waiting_says_so(advising_bot, fake_telegram, migrated_db):
    post(advising_bot, update("/hint Use float division."))

    assert replies(fake_telegram) == ["No chore is waiting for a hint."]


def test_slash_hint_with_no_text_says_how(advising_bot, fake_telegram, migrated_db):
    announced_chore(migrated_db, 77)

    post(advising_bot, update("/hint"))

    assert replies(fake_telegram) == ["Usage: /hint <what to do differently>"]
    assert migrated_db.execute("SELECT count(*) FROM runs").fetchone() == (1,)
