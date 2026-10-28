"""The bot's inbound half where nothing on the internet can reach the api,
as on the home PC (local/compose.home.yml).

Telegram cannot push to a webhook there, so this process pulls with
getUpdates and posts each update to the api's own POST /telegram with the
webhook's secret header. Every check and reply stays in app/telegram_webhook.py.
An update the api did not take is fetched again on the next poll, because the
offset only moves past an update the api answered with a 2xx.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from app.config import load_settings
from app.logging_setup import configure_logging
from app.telegram import TelegramClient, TelegramError
from app.telegram_webhook import SECRET_HEADER

logger = logging.getLogger("agent_runs.telegram_poll")

POLL_TIMEOUT_SECONDS = 50
FORWARD_TIMEOUT_SECONDS = 30.0
RETRY_SECONDS = 10


def _forward(update: dict, api_base_url: str, secret: str) -> bool:
    request = urllib.request.Request(
        f"{api_base_url.rstrip('/')}/telegram",
        data=json.dumps(update).encode(),
        method="POST",
        headers={"Content-Type": "application/json", SECRET_HEADER: secret},
    )
    try:
        with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as error:
        logger.error("the api answered update %s with HTTP %s", update.get("update_id"), error.code)
    except OSError as error:
        logger.error(
            "could not reach the api for update %s: %s",
            update.get("update_id"),
            type(error).__name__,
        )
    return False


def poll_once(
    telegram: TelegramClient,
    offset: int | None,
    api_base_url: str,
    secret: str,
    timeout: int = POLL_TIMEOUT_SECONDS,
    retry_seconds: float = RETRY_SECONDS,
) -> int | None:
    """Fetch what is waiting, forward it in order, and return the offset for
    the next poll. Stops at the first update the api did not take, and waits
    before returning, since Telegram hands the same update straight back."""
    for update in telegram.get_updates(offset, timeout):
        if not _forward(update, api_base_url, secret):
            time.sleep(retry_seconds)
            break
        offset = update["update_id"] + 1
    return offset


def main() -> None:  # pragma: no cover - the process entry point
    configure_logging()
    settings = load_settings()
    if not settings.telegram_bot_token or not settings.telegram_webhook_secret:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET are both needed to poll")
    telegram = TelegramClient(settings.telegram_bot_token, settings.telegram_api_url)
    telegram.delete_webhook()
    logger.info("polling Telegram for updates, forwarding to %s", settings.api_base_url)
    offset = None
    while True:
        try:
            offset = poll_once(
                telegram, offset, settings.api_base_url, settings.telegram_webhook_secret
            )
        except TelegramError as error:
            logger.error("getUpdates failed: %s", error)
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":  # pragma: no cover
    main()
