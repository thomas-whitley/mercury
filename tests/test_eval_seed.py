"""The fixture as the evals expect it: its own tests pass, and every task's
hidden grade fails on it, so each task asks for a real change."""

import shutil
import subprocess
from pathlib import Path

import pytest

from evals.runner import REPO_TESTS, grade_dir, load_tasks

SEED = Path("evals/fixture-seed")
TASKS = load_tasks(Path("evals/chores"))


@pytest.fixture
def seeded(tmp_path) -> Path:
    work = tmp_path / "work"
    shutil.copytree(SEED, work, ignore=shutil.ignore_patterns("__pycache__"))
    return work


def test_the_seed_s_own_tests_pass(seeded):
    result = subprocess.run(REPO_TESTS, cwd=seeded, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_there_are_eleven_tasks_all_on_the_fixture():
    assert len(TASKS) == 11
    assert {t.repo for t in TASKS} == {"thomas-whitley/mercury-fixture"}


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_every_grade_fails_on_the_unchanged_seed(seeded, task):
    passed, output = grade_dir(seeded, task.grade)
    assert not passed, output
