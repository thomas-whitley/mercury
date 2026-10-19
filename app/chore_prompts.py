"""The prompts a repo chore serves its model (app/repo_chore.py). They live
here, in a module with nothing POSIX only, so the bank's export
(bank/export.py) builds a reference example from the same text the model is
served (decisions 28 and 59 of docs/build-brief-evals.md). The retry prompts,
which only a run produces, stay in app/repo_chore.py."""

from pathlib import Path

MAX_TREE_ENTRIES = 500
MAX_FILES_READ = 10
MAX_FILE_CHARS = 20_000

SYSTEM = """You change a git repository to carry out one instruction from its owner. \
Answer with a single JSON object and nothing else."""


def tree_listing(tree: list[str]) -> str:
    listing = "\n".join(tree[:MAX_TREE_ENTRIES])
    if len(tree) > MAX_TREE_ENTRIES:
        listing += f"\n... and {len(tree) - MAX_TREE_ENTRIES} more"
    return listing


def read_prompt(instruction: str, advice: str, listing: str) -> str:
    return (
        f"Instruction:\n{instruction}{advice}\n\nFiles in the repository:\n{listing}\n\n"
        f'Reply {{"read": ["path", ...]}} naming up to {MAX_FILES_READ} files you need to see.'
    )


ASK = (
    " If the note is a question, or too vague to act on, change no files and reply "
    '{"question": "what you need to know"} instead.'
)


def edit_prompt(
    instruction: str,
    advice: str,
    listing: str,
    shown: dict[str, str],
    *,
    may_ask: bool = False,
) -> str:
    """may_ask is for a chore from a review note, which may answer with a
    question for its owner in place of files."""
    files_block = "\n\n".join(f"=== {path} ===\n{body}" for path, body in shown.items())
    prompt = (
        f"Instruction:\n{instruction}{advice}\n\nFiles in the repository:\n{listing}\n\n"
        f"Contents:\n{files_block or '(none)'}\n\n"
        'Reply {"files": {"path": "the full new contents"}, "summary": "one line"}, '
        "including only files you change or create."
    )
    return prompt + ASK if may_ask else prompt


def shown_files(root: Path, paths: list[str]) -> dict[str, str]:
    """Each file that exists and is text, cut to MAX_FILE_CHARS. The caller
    has already refused any path outside the repository."""
    shown = {}
    for path in paths:
        target = root / path
        if not target.is_file():
            continue
        try:
            shown[path] = target.read_text()[:MAX_FILE_CHARS]
        except UnicodeDecodeError:
            continue
    return shown
