"""A second provider takes over a run when the first fails. The first failed
call switches the run to the fallback for every call after it, so the retry
the loop already does is what reaches the fallback, and a step takes no longer
than it did with one provider. The run's provider column then names the
provider that answered.
"""

import pytest

from app.loop import _complete_with_retry
from app.mercury_config import TaskSettings
from app.model import FallbackModel, ModelReply, StubModel
from app.runs import claim_run
from app.tasks import TASK_TYPES, configure_task_types
from app.worker import _with_fallback, process_run, rungs_after
from tests.test_worker import settings_with


class _Failing:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, prompt: str) -> ModelReply:
        self.calls += 1
        raise RuntimeError("503 This model is currently experiencing high demand")


def test_a_working_primary_answers_and_the_fallback_is_never_called():
    fallback = _Failing()
    model = FallbackModel(StubModel(replies=["first"]), fallback, on_switch=pytest.fail)

    assert model.complete("s", "p").text == "first"
    assert fallback.calls == 0


def test_a_failed_primary_raises_once_and_switches_every_later_call_to_the_fallback():
    primary = _Failing()
    switched: list[bool] = []
    model = FallbackModel(
        primary, StubModel(replies=["second"]), on_switch=lambda: switched.append(True)
    )

    with pytest.raises(RuntimeError, match="high demand"):
        model.complete("s", "p")
    assert model.complete("s", "p").text == "second"
    assert model.complete("s", "p").text == "second"

    assert (primary.calls, switched) == (1, [True])


def test_the_existing_retry_reaches_the_fallback_on_its_second_try():
    primary = _Failing()
    model = FallbackModel(primary, StubModel(replies=["second"]), on_switch=lambda: None)

    reply = _complete_with_retry(model, "s", "p", attempts=4, backoff_seconds=0)

    assert reply.text == "second"
    assert primary.calls == 1


def _builder(failing: str):
    """A model_builder whose model for one provider always fails."""

    def build(settings, provider_name):
        if provider_name == failing:
            return _Failing()
        return StubModel(replies=['{"action": "ask", "question": "Which URL?"}'])

    return build


def _chat_run(conn) -> str:
    run_id = conn.execute(
        "INSERT INTO runs (task, type, provider, telegram_chat_id, telegram_message_id) "
        "VALUES ('check my site', 'chat', 'ollama', 42, 7) RETURNING id::text"
    ).fetchone()[0]
    claim_run(conn, run_id, "worker-test")
    return run_id


def test_a_chat_run_whose_provider_fails_is_answered_by_the_fallback(migrated_db, fake_telegram):
    run_id = _chat_run(migrated_db)
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )

    process_run(migrated_db, run_id, settings, model_builder=_builder("ollama"))

    status, provider = migrated_db.execute(
        "SELECT status, provider FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    assert (status, provider) == ("succeeded", "gemini")
    assert fake_telegram.sent("editMessageText")[-1]["text"] == "Which URL?"


def test_a_run_answered_by_its_own_provider_keeps_it(migrated_db, fake_telegram):
    run_id = _chat_run(migrated_db)
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )

    process_run(migrated_db, run_id, settings, model_builder=_builder("gemini"))

    provider = migrated_db.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert provider == ("ollama",)


def test_a_fallback_with_no_key_leaves_the_run_on_its_own_provider(migrated_db, fake_telegram):
    run_id = _chat_run(migrated_db)
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )

    def build(settings, provider_name):
        if provider_name == "gemini":
            raise RuntimeError("no model credentials: set MODEL_API_KEY")
        return StubModel(replies=['{"action": "ask", "question": "Which URL?"}'])

    process_run(migrated_db, run_id, settings, model_builder=build)

    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert status == ("succeeded",)


def _recording(seen: list[str]):
    def build(settings, provider_name):
        seen.append(provider_name)
        return StubModel(replies=['{"action": "ask", "question": "Which URL?"}'])

    return build


def _chat_run_on(conn, provider: str) -> str:
    run_id = conn.execute(
        "INSERT INTO runs (task, type, provider, telegram_chat_id, telegram_message_id) "
        "VALUES ('check my site', 'chat', %s, 42, 7) RETURNING id::text",
        (provider,),
    ).fetchone()[0]
    claim_run(conn, run_id, "worker-test")
    return run_id


def test_a_run_is_built_on_the_provider_its_row_names(migrated_db, fake_telegram):
    run_id = _chat_run_on(migrated_db, "haiku")
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )
    seen: list[str] = []

    process_run(migrated_db, run_id, settings, model_builder=_recording(seen))

    # chat's whole ladder, ollama then gemini, stands behind a provider the row
    # named that is not on it.
    assert seen == ["haiku", "ollama", "gemini"]


def test_a_run_already_on_its_types_fallback_gets_no_fallback_behind_it(migrated_db, fake_telegram):
    run_id = _chat_run_on(migrated_db, "gemini")
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )
    seen: list[str] = []

    process_run(migrated_db, run_id, settings, model_builder=_recording(seen))

    assert seen == ["gemini"]


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("gemini", ("ollama", "haiku")),
        ("ollama", ("haiku",)),
        # A reclaimed run already on the last rung has nothing behind it.
        ("haiku", ()),
        # A provider the caller named that is not on the ladder gets the whole ladder.
        ("groq", ("gemini", "ollama", "haiku")),
    ],
)
def test_the_rungs_after_a_provider(provider, expected):
    assert rungs_after(("gemini", "ollama", "haiku"), provider) == expected


def _pytest_run_on(conn, provider: str) -> str:
    return str(
        conn.execute(
            "INSERT INTO runs (task, type, provider) VALUES ('t', 'pytest', %s) RETURNING id",
            (provider,),
        ).fetchone()[0]
    )


def test_two_failures_walk_the_run_down_two_rungs_and_the_row_follows(
    migrated_db, restore_task_types
):
    configure_task_types({"pytest": TaskSettings(ladder=("gemini", "ollama", "haiku"))})
    run_id = _pytest_run_on(migrated_db, "gemini")
    models = {"gemini": _Failing(), "ollama": _Failing(), "haiku": StubModel(replies=["ok"])}
    model = _with_fallback(
        migrated_db,
        run_id,
        models["gemini"],
        TASK_TYPES["pytest"],
        settings_with(),
        lambda settings, name: models[name],
        "gemini",
    )

    for _ in range(2):
        with pytest.raises(RuntimeError):
            model.complete("s", "p")
    assert model.complete("s", "p").text == "ok"
    provider = migrated_db.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert provider == ("haiku",)


def test_a_rung_with_no_credentials_is_skipped(migrated_db, restore_task_types):
    configure_task_types({"pytest": TaskSettings(ladder=("gemini", "ollama", "haiku"))})
    run_id = _pytest_run_on(migrated_db, "gemini")

    def build(settings, name):
        if name == "ollama":
            raise RuntimeError("no model credentials: set OLLAMA_API_KEY")
        return StubModel(replies=[name])

    model = _with_fallback(
        migrated_db, run_id, _Failing(), TASK_TYPES["pytest"], settings_with(), build, "gemini"
    )
    with pytest.raises(RuntimeError):
        model.complete("s", "p")
    assert model.complete("s", "p").text == "haiku"
    provider = migrated_db.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert provider == ("haiku",)
