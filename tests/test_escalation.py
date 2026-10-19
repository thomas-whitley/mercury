"""One Telegram message per escalated chore, per Phase 2 of
docs/build-brief-evals.md: its reason, the tail of its test output, its run
page and a prompt to reply with a hint, with the Open it anyway button when it
left a diff. An eval chore and a second escalation of the same chore send
nothing; they reach the report instead."""

import json

from psycopg.types.json import Jsonb

from app.advice import advise
from app.escalation import announce_escalation, chain_root
from app.mercury_config import RepoConfig
from app.repo_chore import NEEDS_THOMAS, OUTSIDE_PATHS, RED, UNUSABLE
from app.telegram import TelegramClient

CHAT = 42
PAGE = "https://mercury.test"
REPOS = (RepoConfig(name="owner/fixture", test_command="true"),)


def client(fake) -> TelegramClient:
    return TelegramClient("123:abc", fake.url)


def escalated_chore(
    conn,
    reason: str,
    *,
    test_output: str = "",
    diff: str = "+x\n",
    source: str = "api",
    source_run_id: str | None = None,
    hint: str | None = None,
    question: str | None = None,
) -> str:
    run_id = str(
        conn.execute(
            "INSERT INTO runs (task, type, provider, repo, status, escalation_reason, source, "
            "source_run_id, hint, finished_at) "
            "VALUES ('Add divide to calc.py', 'repo_chore', 'gemini', 'owner/fixture', "
            "'escalated', %s, %s, %s, %s, now()) RETURNING id",
            (reason, source, source_run_id, hint),
        ).fetchone()[0]
    )
    output = {"status": "escalated", "reason": reason, "diff": diff, "test_output": test_output}
    if question is not None:
        output["question"] = question
    conn.execute(
        "INSERT INTO steps (run_id, seq, kind, output) VALUES (%s, 1, 'done', %s)",
        (run_id, Jsonb(output)),
    )
    return run_id


def test_an_escalated_chore_sends_one_message_with_its_reason_output_and_page(
    migrated_db, fake_telegram
):
    run_id = escalated_chore(migrated_db, RED, test_output="E   assert 8 == 2")

    message_id = announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE)

    [sent] = fake_telegram.sent()
    assert sent["chat_id"] == CHAT
    assert f"escalated ({run_id[:8]}): {RED}" in sent["text"]
    assert "owner/fixture" in sent["text"]
    assert "Add divide to calc.py" in sent["text"]
    assert "assert 8 == 2" in sent["text"]
    assert f"{PAGE}/#/runs/{run_id}" in sent["text"]
    assert "Reply to this message with a hint" in sent["text"]
    assert "/hint" in sent["text"]
    assert "Open it anyway" in json.dumps(sent["reply_markup"])
    stored = migrated_db.execute(
        "SELECT escalation_message_id FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert stored == (message_id,)


def test_only_the_tail_of_a_long_test_output_is_sent(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, RED, test_output="x" * 5000 + "THE END")

    announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE)

    text = fake_telegram.sent()[0]["text"]
    assert "THE END" in text
    assert len(text) < 2000


def test_one_with_no_diff_has_no_open_it_anyway_button(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, UNUSABLE, diff="")

    announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE)

    assert "reply_markup" not in fake_telegram.sent()[0]


def test_an_eval_chore_is_never_announced(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, RED, source="eval")

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE) is None
    assert fake_telegram.sent() == []


def test_a_bank_chore_is_never_announced(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, RED, source="bank")

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE) is None
    assert fake_telegram.sent() == []


def test_a_second_escalation_of_the_same_chore_is_not_announced(migrated_db, fake_telegram):
    first = escalated_chore(migrated_db, RED)
    announce_escalation(migrated_db, client(fake_telegram), CHAT, first, PAGE)
    second = escalated_chore(migrated_db, RED, source_run_id=first, hint="use float division")

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, second, PAGE) is None
    assert len(fake_telegram.sent()) == 1


def test_no_bot_or_no_owner_chat_sends_nothing(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, RED)

    assert announce_escalation(migrated_db, None, CHAT, run_id, PAGE) is None
    assert announce_escalation(migrated_db, client(fake_telegram), None, run_id, PAGE) is None
    assert fake_telegram.sent() == []


def test_a_telegram_error_leaves_the_run_escalated_with_no_message(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, RED)
    fake_telegram.fail_next = {"error_code": 400, "description": "Bad Request: chat not found"}

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE) is None
    row = migrated_db.execute(
        "SELECT status, escalation_message_id FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert row == ("escalated", None)


def test_the_root_of_a_chain_is_its_first_run(migrated_db):
    first = escalated_chore(migrated_db, RED)
    second = escalated_chore(migrated_db, RED, source_run_id=first, hint="a")
    third = escalated_chore(migrated_db, RED, source_run_id=second, hint="b")

    assert chain_root(migrated_db, third) == first
    assert chain_root(migrated_db, first) == first


def test_an_advised_rerun_of_an_eval_chore_is_never_announced(migrated_db, fake_telegram):
    first = escalated_chore(migrated_db, RED, source="eval")
    rerun = advise(migrated_db, first, "a hint", "mcp", REPOS)
    migrated_db.execute("UPDATE runs SET status = 'escalated' WHERE id = %s", (rerun,))

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, rerun, PAGE) is None
    assert fake_telegram.sent() == []


def test_a_note_escalation_has_no_open_anyway_button(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, OUTSIDE_PATHS, source="review_note", diff="+x\n")

    message_id = announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE)

    [sent] = fake_telegram.sent()
    assert OUTSIDE_PATHS in sent["text"]
    assert "reply_markup" not in sent
    assert migrated_db.execute("SELECT count(*) FROM approvals").fetchone() == (0,)
    stored = migrated_db.execute(
        "SELECT escalation_message_id FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert stored == (message_id,)


def test_each_question_in_a_note_chain_is_announced(migrated_db, fake_telegram):
    first = escalated_chore(
        migrated_db, NEEDS_THOMAS, source="review_note", diff="", question="Which number?"
    )
    announce_escalation(migrated_db, client(fake_telegram), CHAT, first, PAGE)
    second = escalated_chore(
        migrated_db, NEEDS_THOMAS, source="review_note", diff="", question="And which unit?",
        source_run_id=first, hint="the phone number",
    )  # fmt: skip

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, second, PAGE) is not None
    texts = [message["text"] for message in fake_telegram.sent()]
    assert len(texts) == 2
    assert "Which number?" in texts[0]
    assert "And which unit?" in texts[1]


def test_a_note_chain_that_fails_after_a_question_is_still_announced_once(
    migrated_db, fake_telegram
):
    first = escalated_chore(
        migrated_db, NEEDS_THOMAS, source="review_note", diff="", question="Which number?"
    )
    announce_escalation(migrated_db, client(fake_telegram), CHAT, first, PAGE)
    second = escalated_chore(
        migrated_db, RED, source="review_note", source_run_id=first, hint="the phone number"
    )

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, second, PAGE) is None
    assert len(fake_telegram.sent()) == 1


def test_a_note_question_with_a_huge_note_still_fits_in_one_message(migrated_db, fake_telegram):
    from app.review_notes import Note, instruction_for

    ticks = "`" * 250 + "x" + "`" * 249
    note = Note(
        id=1,
        host="h",
        page="/p/",
        anchor_text=ticks,
        quote=ticks,
        body="`" * 1000 + "x" + "`" * 999,
        updated_at="t",
    )
    run_id = escalated_chore(
        migrated_db, NEEDS_THOMAS, source="review_note", diff="", question="Q" * 1000
    )
    migrated_db.execute("UPDATE runs SET task = %s WHERE id = %s", (instruction_for(note), run_id))

    message_id = announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE)

    assert message_id is not None
    [sent] = fake_telegram.sent()
    text = sent["text"]
    assert len(text) <= 4096
    assert "Q" * 1000 in text
    assert f"{PAGE}/#/runs/{run_id}" in text
    assert "Reply to this message with a hint" in text
    # Every fence the cut left open is closed again.
    fences = [line for line in text.splitlines() if line and set(line) == {"`"}]
    assert len(fences) % 2 == 0


def test_a_short_task_is_sent_whole():
    from app.escalation import escalation_text

    text = escalation_text("a" * 36, "o/r", "Do it.", "why", "", PAGE)

    assert "Do it." in text
    assert "cut" not in text
