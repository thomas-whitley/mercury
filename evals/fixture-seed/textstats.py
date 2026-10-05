"""Text statistics for Mercury's evals. word_count has a known bug the evals ask a model to fix."""


def word_count(text: str) -> int:
    return len(text.split(" "))
