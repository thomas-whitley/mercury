"""The text an advised rerun or an outage retry adds after a chore's
instruction (app/repo_chore.py). It imports nothing POSIX only, so the eval
runner on Windows builds the same block for a delegate.ps1 rerun (Phase 3 of
docs/build-brief-evals.md)."""

import re

MAX_DIFF_CHARS = 20_000
# A note chore may answer with a question in place of files. The question is
# model output, so it is cut to this length wherever it is shown again.
MAX_QUESTION_CHARS = 1_000


def fenced_lines(label: str, text: str) -> list[str]:
    """label is fixed text. The quoted text follows inside a fence longer than
    any run of backticks in it, so it cannot close the fence."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [label, fence, text, fence]


def advice_block(hint: str | None, output: dict) -> str:
    """What an advised rerun or an outage retry adds after the instruction:
    the question the earlier run asked, when it asked one, the owner's hint,
    and the failed attempt it follows, when there is one."""
    block = ""
    question = output.get("question")
    if isinstance(question, str) and question.strip() and hint:
        block += "\n\n" + "\n".join(
            fenced_lines(
                "An earlier attempt at this chore asked the owner this question, and the owner "
                "answered it with the hint below:",
                question.strip()[:MAX_QUESTION_CHARS],
            )
        )
    block += f"\n\nThe owner's hint: {hint}" if hint else ""
    diff, test_output = output.get("diff") or "", output.get("test_output") or ""
    if diff.strip() and output.get("status") == "succeeded":
        # An eval or bank chore whose pull request failed a grade it never saw.
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
