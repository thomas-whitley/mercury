"""The sandbox is a subprocess with a timeout and no network. Nothing more."""

import os
import pwd
import subprocess
import time

import pytest

from app import sandbox
from app.sandbox import verify

PASSING_TEST = """
from solution import add

def test_add():
    assert add(2, 3) == 5
"""


def test_a_correct_solution_passes():
    result = verify("def add(a, b):\n    return a + b\n", PASSING_TEST)

    assert result.passed is True
    assert result.timed_out is False


def test_a_wrong_solution_fails_and_the_output_explains_why():
    result = verify("def add(a, b):\n    return a * b\n", PASSING_TEST)

    assert result.passed is False
    assert result.timed_out is False
    assert "add" in result.output


def test_a_solution_that_does_not_import_fails_rather_than_raising():
    result = verify("this is not python\n", PASSING_TEST)

    assert result.passed is False
    assert result.timed_out is False


def test_a_solution_that_hangs_is_killed_at_the_timeout():
    started = time.monotonic()
    result = verify(
        "def add(a, b):\n    while True:\n        pass\n", PASSING_TEST, timeout_seconds=2
    )
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.passed is False
    assert elapsed < 20, "the subprocess outlived its timeout"


def test_the_sandbox_cannot_open_a_socket():
    reaching_out = """
import socket

def test_network():
    socket.create_connection(("example.com", 80), timeout=2)
"""
    result = verify("def add(a, b):\n    return a + b\n", reaching_out)

    assert result.passed is False
    assert "network" in result.output.lower()


def test_the_sandbox_cannot_reach_the_raw_socket_module():
    """Patching socket.socket alone is bypassed by importing _socket directly."""
    going_under = """
import _socket

def test_raw_socket():
    _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
"""
    result = verify("def add(a, b):\n    return a + b\n", going_under)

    assert result.passed is False
    assert "network" in result.output.lower()


def test_the_sandbox_does_not_inherit_the_parent_environment(monkeypatch):
    """A key in the worker's environment must not reach generated code."""
    monkeypatch.setenv("MODEL_API_KEY", "a-secret-that-must-not-leak")

    reading_env = """
import os

def test_env():
    assert "MODEL_API_KEY" not in os.environ, "the key reached the sandbox"
"""
    result = verify("def add(a, b):\n    return a + b\n", reading_env)

    assert result.passed is True


# In the image the worker is root. A test file running as the worker's user
# could read the worker's keys from /proc/<pid>/environ, whatever env= says,
# so as root pytest runs as the unprivileged sandbox user, and with no such
# user it does not run.


def test_as_root_the_test_file_runs_as_the_sandbox_user(monkeypatch):
    chowned, run_kwargs = [], {}
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        pwd, "getpwnam", lambda name: pwd.struct_passwd((name, "x", 4321, 4321, "", "/", "/bin/sh"))
    )
    monkeypatch.setattr(
        os, "chown", lambda path, uid, gid, **kwargs: chowned.append((os.path.basename(path), uid))
    )

    def fake_run(args, **kwargs):
        run_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="1 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = verify("def add(a, b):\n    return a + b\n", PASSING_TEST)

    assert result.passed is True
    assert (run_kwargs.get("user"), run_kwargs.get("group")) == (4321, 4321)
    assert run_kwargs.get("extra_groups") == []
    assert ("test_solution.py", 4321) in chowned


def test_as_root_with_no_sandbox_user_the_test_file_does_not_run(monkeypatch):
    def no_such_user(name):
        raise KeyError(name)

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(pwd, "getpwnam", no_such_user)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran as root"))

    with pytest.raises(sandbox.SandboxError, match="sandbox user"):
        verify("def add(a, b):\n    return a + b\n", PASSING_TEST)


def test_as_root_whatever_the_test_file_left_running_is_killed(monkeypatch):
    """A process the test file started, in its own session or not, would
    outlive subprocess.run's own kill. Everything the sandbox user runs goes."""
    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        pwd, "getpwnam", lambda name: pwd.struct_passwd((name, "x", 4321, 4321, "", "/", "/bin/sh"))
    )
    monkeypatch.setattr(os, "chown", lambda *a, **k: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **k: (
            calls.append("pytest")
            or subprocess.CompletedProcess(args, 0, stdout="1 passed", stderr="")
        ),
    )
    monkeypatch.setattr(
        sandbox, "kill_user_processes", lambda uid, gid: calls.append(("kill", uid, gid))
    )

    verify("def add(a, b):\n    return a + b\n", PASSING_TEST)

    assert calls == ["pytest", ("kill", 4321, 4321)]


def _unprivileged_user() -> pwd.struct_passwd | None:
    for name in ("sandbox", "chore", "nobody"):
        try:
            return pwd.getpwnam(name)
        except KeyError:
            continue
    return None


@pytest.mark.skipif(os.geteuid() != 0, reason="switching users needs root, as in the image")
def test_kill_user_processes_stops_a_process_that_left_its_session():
    user = _unprivileged_user()
    if user is None:
        pytest.skip("no unprivileged user to run as")
    escaped = subprocess.Popen(
        ["sleep", "60"],
        user=user.pw_uid,
        group=user.pw_gid,
        extra_groups=[],
        start_new_session=True,
    )
    time.sleep(0.5)

    sandbox.kill_user_processes(user.pw_uid, user.pw_gid)

    assert escaped.wait(timeout=10) == -9
    assert os.getpid() > 0  # the caller, root, is still here
