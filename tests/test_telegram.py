"""The outbound Telegram client, against the fake Bot API."""

import pytest

from app.telegram import TelegramClient, TelegramError
from tests.telegram_fake import FakeTelegram


@pytest.fixture
def fake():
    server = FakeTelegram()
    yield server
    server.close()


def test_send_message_returns_the_new_message_id(fake):
    client = TelegramClient("123:abc", base_url=fake.url)

    first = client.send_message(42, "hello")
    second = client.send_message(42, "again")

    assert (first, second) == (1, 2)
    assert fake.sent() == [{"chat_id": 42, "text": "hello"}, {"chat_id": 42, "text": "again"}]
    assert fake.tokens == ["123:abc", "123:abc"]


def test_send_message_can_ask_for_html_no_link_preview_and_no_sound(fake):
    client = TelegramClient("123:abc", base_url=fake.url)

    client.send_message(
        42,
        "<b>hello</b>",
        parse_mode="HTML",
        disable_link_preview=True,
        disable_notification=True,
    )

    assert fake.sent() == [
        {
            "chat_id": 42,
            "text": "<b>hello</b>",
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "disable_notification": True,
        }
    ]


def test_a_refused_call_carries_telegrams_status(fake):
    client = TelegramClient("123:abc", base_url=fake.url)
    fake.fail_next = {"error_code": 400, "description": "Bad Request: can't parse entities"}

    with pytest.raises(TelegramError) as raised:
        client.send_message(42, "<b>hello", parse_mode="HTML")

    assert raised.value.status == 400


def test_edit_message_text_edits_in_place(fake):
    client = TelegramClient("123:abc", base_url=fake.url)

    client.edit_message_text(42, 7, "step 3 of 5")

    assert fake.sent("editMessageText") == [{"chat_id": 42, "message_id": 7, "text": "step 3 of 5"}]


def test_an_edit_that_changes_nothing_is_not_an_error(fake):
    client = TelegramClient("123:abc", base_url=fake.url)
    fake.fail_next = {
        "error_code": 400,
        "description": "Bad Request: message is not modified: specified new message content "
        "and reply markup are exactly the same",
    }

    client.edit_message_text(42, 7, "same text")


def test_a_refused_call_raises_without_the_token_in_the_message(fake):
    client = TelegramClient("123:secret-token", base_url=fake.url)
    fake.fail_next = {"error_code": 400, "description": "Bad Request: chat not found"}

    with pytest.raises(TelegramError) as raised:
        client.send_message(42, "hello")

    assert "chat not found" in str(raised.value)
    assert "secret-token" not in str(raised.value)


def test_an_unreachable_api_raises_without_the_token_in_the_message():
    client = TelegramClient("123:secret-token", base_url="http://127.0.0.1:1")

    with pytest.raises(TelegramError) as raised:
        client.send_message(42, "hello")

    assert "secret-token" not in str(raised.value)


FOUR = [("A", "a"), ("B", "b"), ("C", "c"), ("D", "d")]
TWO_ROWS = {
    "inline_keyboard": [
        [{"text": "A", "callback_data": "a"}, {"text": "B", "callback_data": "b"}],
        [{"text": "C", "callback_data": "c"}, {"text": "D", "callback_data": "d"}],
    ]
}


def test_send_message_puts_buttons_two_per_row(fake):
    TelegramClient("123:abc", base_url=fake.url).send_message(42, "hi", FOUR, per_row=2)

    assert fake.sent()[0]["reply_markup"] == TWO_ROWS


def test_edit_with_buttons_keeps_the_keyboard(fake):
    TelegramClient("123:abc", base_url=fake.url).edit_message_text(42, 7, "hi", FOUR, per_row=2)

    assert fake.sent("editMessageText")[0]["reply_markup"] == TWO_ROWS


def test_edit_without_buttons_sends_no_reply_markup(fake):
    TelegramClient("123:abc", base_url=fake.url).edit_message_text(42, 7, "hi")

    assert fake.sent("editMessageText") == [{"chat_id": 42, "message_id": 7, "text": "hi"}]


def test_a_truncated_answer_is_a_telegram_error(fake, monkeypatch):
    import http.client
    import urllib.request

    def truncated(*args, **kwargs):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(urllib.request, "urlopen", truncated)

    with pytest.raises(TelegramError, match="IncompleteRead"):
        TelegramClient("123:abc", base_url=fake.url).send_message(42, "hi")
