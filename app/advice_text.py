"""The text an advised rerun or an outage retry adds after a chore's
instruction (app/repo_chore.py). It imports nothing POSIX only, so the eval
runner on Windows builds the same block for a delegate.ps1 rerun (Phase 3 of
docs/build-brief-evals.md)."""

MAX_DIFF_CHARS = 20_000


def advice_block(hint: str | None, output: dict) -> str:
    """What an advised rerun or an outage retry adds after the instruction:
    the owner's hint, and the failed attempt it follows, when there is one."""
    block = f"\n\nThe owner's hint: {hint}" if hint else ""
    diff, test_output = output.get("diff") or "", output.get("test_output") or ""
    if diff.strip() and output.get("status") == "succeeded":
        # An eval chore whose pull request failed a grade it never saw.
        block += (
            "\n\nAn earlier attempt at this chore passed the repository's tests and opened a "
            "pull request, but a check outside those tests found it wrong. "
            f"Its diff, which is not applied:\n{diff[:MAX_DIFF_CHARS]}"
        )
    elif diff.strip():
        block += (
            f"\n\nAn earlier attempt at this chore failed ({output.get('reason', 'escalated')}). "
            f"Its diff, which is not applied:\n{diff[:MAX_DIFF_CHARS]}"
        )
        if test_output.strip():
            block += f"\n\nIts test output ended:\n{test_output}"
    return block
