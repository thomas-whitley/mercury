"""The one gate every repo chore passes, whatever created it.

A chore is created waiting, where no worker claims it, and the owner is asked
on Telegram with the repo and the instruction echoed. Only a button press
starts it (app/approvals.py). The chat, POST /runs and anything that calls
POST /runs come through here, so none of them can start a chore unasked,
except on a repo marked auto_approve in mercury.yaml, which skips the
question for every source but chat.
"""

import psycopg

from app.approvals import ask
from app.mercury_config import RepoConfig
from app.tasks import TASK_TYPES
from app.telegram import TelegramClient

_CREATE = """
INSERT INTO runs (task, type, provider, repo, status, telegram_chat_id, source)
VALUES (%s, 'repo_chore', %s, %s, 'awaiting_approval', %s, %s) RETURNING id
"""
# Its progress replaces the question once it is approved.
_SET_MESSAGE_FROM_APPROVAL = """
UPDATE runs SET telegram_message_id = (SELECT message_id FROM approvals WHERE id = %s)
WHERE id = %s
"""
_CREATE_STARTED = """
INSERT INTO runs (task, type, provider, repo, status, source)
VALUES (%s, 'repo_chore', %s, %s, 'pending', %s) RETURNING id
"""


class ChoreRefused(ValueError):
    """The chore cannot be asked about. The message says why, for the owner."""


def find_repo(repos: tuple[RepoConfig, ...], name: object) -> RepoConfig:
    if not repos:
        raise ChoreRefused("No repos are listed for chores in mercury.yaml.")
    repo = next((repo for repo in repos if repo.name == name), None)
    if repo is None:
        raise ChoreRefused("I can only work on " + ", ".join(r.name for r in repos) + ".")
    if not repo.test_command:
        raise ChoreRefused(
            f"{repo.name} has no test_command in mercury.yaml, so it cannot have a chore."
        )
    return repo


def starts_unasked(repo: RepoConfig, source: str) -> bool:
    """A repo marked auto_approve skips the question, except for a chore asked
    for in chat, where the owner is there to press the button and the chat
    has already told them it is waiting."""
    return repo.auto_approve and source != "telegram"


def start_chore(
    conn: psycopg.Connection, repo: RepoConfig, instruction: str, source: str, provider: str
) -> str:
    """Create the chore pending, where the worker claims it. Only for a repo
    starts_unasked allows. No chat id, so no progress message and no Open it
    anyway button."""
    run_id = conn.execute(
        _CREATE_STARTED, (instruction.strip(), provider, repo.name, source)
    ).fetchone()[0]
    return str(run_id)


def request_chore(
    conn: psycopg.Connection,
    telegram: TelegramClient,
    chat_id: int,
    repo: RepoConfig,
    instruction: str,
    source: str,
    provider: str | None = None,
) -> str:
    """Create the chore waiting and ask about it. Returns the run id.

    One transaction, so a question that could not be sent (TelegramError)
    leaves no run waiting on an answer nobody can give.
    """
    instruction = instruction.strip()
    question = (
        f"Repo chore on {repo.name}:\n{instruction}\n\n"
        f"It runs `{repo.test_command}` and opens a pull request only if that passes."
    )
    with conn.transaction():
        run_id = conn.execute(
            _CREATE,
            (
                instruction,
                provider or TASK_TYPES["repo_chore"].provider,
                repo.name,
                chat_id,
                source,
            ),
        ).fetchone()[0]
        approval_id = ask(conn, telegram, chat_id, "start_run", question, run_id=str(run_id))
        conn.execute(_SET_MESSAGE_FROM_APPROVAL, (approval_id, run_id))
    return str(run_id)
