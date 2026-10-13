"""The public demo image's supervisor, infra/demo/space/run.py (P28 track PD; REQ-FND-04), imported by path.

Covers what the image relies on without starting it: the nightly reset at 03:00 Africa/Nairobi (00:00 UTC, no
daylight saving), the wipe staying inside the data directory, the public address chosen per host, the refusal of a bad
PORT or PUBLIC_DEMO_CONTENT, the order the children are stopped in, and the single-instance guard (start and
``reset``). AT-PD-7 itself (the built image, booted, signed in and reset) is a manual run recorded on the card.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
RUN_PY = REPO / "infra" / "demo" / "space" / "run.py"
LINUX_PROC = Path("/proc/self/cmdline").exists()


@pytest.fixture(scope="module")
def run() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_space_run", RUN_PY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def home(run: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The supervisor's home, data directory, pid file and SeaweedFS socket folder, all under tmp_path."""
    monkeypatch.setattr(run, "HOME", tmp_path / "home")
    monkeypatch.setattr(run, "DATA", tmp_path / "home" / "data")
    monkeypatch.setattr(run, "PIDFILE", tmp_path / "home" / "run.pid")
    monkeypatch.setattr(run, "SEAWEED_SOCKETS", tmp_path / "tmp")
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    return tmp_path / "home"


# ---------------------------------------------------------------- the nightly reset


@pytest.mark.parametrize(
    ("now", "due"),
    [
        (datetime(2026, 10, 13, 23, 59, 59, tzinfo=UTC), datetime(2026, 10, 14, 0, 0, tzinfo=UTC)),  # 02:59:59 EAT
        (datetime(2026, 10, 14, 0, 0, tzinfo=UTC), datetime(2026, 10, 15, 0, 0, tzinfo=UTC)),  # 03:00 EAT exactly
        (datetime(2026, 10, 14, 0, 0, 1, tzinfo=UTC), datetime(2026, 10, 15, 0, 0, tzinfo=UTC)),  # just after
        (datetime(2026, 10, 13, 12, 0, tzinfo=UTC), datetime(2026, 10, 14, 0, 0, tzinfo=UTC)),  # midday
        (datetime(2026, 12, 31, 22, 0, tzinfo=UTC), datetime(2027, 1, 1, 0, 0, tzinfo=UTC)),  # across a year
    ],
)
def test_the_reset_is_due_at_the_next_0300_in_nairobi(run: ModuleType, now: datetime, due: datetime) -> None:
    got = run.next_reset(now)
    assert got == due
    assert got.utcoffset() == timedelta(hours=3)
    assert (got.hour, got.minute, got.second) == (3, 0, 0)


@pytest.mark.parametrize("month", [1, 3, 4, 6, 10, 11])  # Europe's and America's DST switches change nothing
def test_the_reset_stays_at_midnight_utc_all_year(run: ModuleType, month: int) -> None:
    due = run.next_reset(datetime(2026, month, 15, 12, 0, tzinfo=UTC))
    assert due.astimezone(UTC) == datetime(2026, month, 16, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------- the wipe


def test_the_wipe_empties_the_data_directory_and_recreates_the_childrens_folders(run: ModuleType, home: Path) -> None:
    data = run.DATA
    (data / "postgres" / "base").mkdir(parents=True)
    (data / "postgres" / "base" / "1").write_text("rows", encoding="utf-8")
    (data / "stray.txt").write_text("x", encoding="utf-8")
    (run.SEAWEED_SOCKETS / "seaweedfs-filer-grpc-18888.sock").write_text("", encoding="utf-8")
    (run.SEAWEED_SOCKETS / "other.sock").write_text("", encoding="utf-8")
    run.wipe()
    assert sorted(p.name for p in data.iterdir()) == ["mail", "run", "s3"]
    assert all(not any((data / name).iterdir()) for name in ("mail", "run", "s3"))
    assert sorted(p.name for p in run.SEAWEED_SOCKETS.iterdir()) == ["other.sock"]  # only SeaweedFS's sockets go


def test_the_wipe_never_follows_a_symlink_out_of_the_data_directory(
    run: ModuleType, home: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / "keep").mkdir(parents=True)
    (outside / "keep" / "precious.txt").write_text("keep me", encoding="utf-8")
    (outside / "file.txt").write_text("keep me too", encoding="utf-8")
    run.DATA.mkdir()
    (run.DATA / "linked-dir").symlink_to(outside / "keep", target_is_directory=True)
    (run.DATA / "linked-file").symlink_to(outside / "file.txt")
    run.wipe()
    assert (outside / "keep" / "precious.txt").read_text(encoding="utf-8") == "keep me"
    assert (outside / "file.txt").read_text(encoding="utf-8") == "keep me too"
    assert not (run.DATA / "linked-dir").exists()
    assert not (run.DATA / "linked-file").is_symlink()


# ---------------------------------------------------------------- the public address


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (
            {"PUBLIC_BASE_URL": "https://129-151-10-20.sslip.io/", "SPACE_HOST": "x.hf.space"},
            "https://129-151-10-20.sslip.io",
        ),
        ({"SPACE_HOST": "owner-bridge-demo.hf.space", "CODESPACE_NAME": "c"}, "https://owner-bridge-demo.hf.space"),
        (
            {"CODESPACE_NAME": "fuzzy-train-q7", "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev"},
            "https://fuzzy-train-q7-7860.app.github.dev",
        ),
        ({"CODESPACE_NAME": "fuzzy-train-q7"}, "http://localhost:7860"),  # half the codespace's variables: not used
        ({}, "http://localhost:7860"),
    ],
)
def test_the_public_address_follows_the_host(
    run: ModuleType, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    for name in ("PUBLIC_BASE_URL", "SPACE_HOST", "CODESPACE_NAME", "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert run.public_base_url(7860) == expected


# ---------------------------------------------------------------- start-up validation


@pytest.fixture
def started(run: ModuleType, home: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    """Supervisor.run replaced: records (port, content) instead of booting anything."""
    calls: list[tuple[int, str]] = []

    def fake_run(self: Any) -> int:
        calls.append((self.port, self.content))
        return 0

    monkeypatch.setattr(run.Supervisor, "run", fake_run)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("PUBLIC_DEMO_CONTENT", raising=False)
    return calls


@pytest.mark.parametrize("port", ["abc", "0", "70000", "-1", "5432", "8000", "8080", "8333"])
def test_a_bad_or_internal_port_is_refused(
    run: ModuleType, started: list[tuple[int, str]], monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv("PORT", port)
    assert run.main([]) == 2
    assert started == []


def test_unknown_content_is_refused(
    run: ModuleType, started: list[tuple[int, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PUBLIC_DEMO_CONTENT", "everything")
    assert run.main([]) == 2
    assert started == []


def test_the_defaults_and_valid_values_start_the_supervisor(
    run: ModuleType, started: list[tuple[int, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run.main([]) == 0
    monkeypatch.setenv("PORT", "3000")
    monkeypatch.setenv("PUBLIC_DEMO_CONTENT", "full")
    assert run.main([]) == 0
    assert started == [(7860, "fictional"), (3000, "full")]


def test_an_unknown_command_prints_the_usage(run: ModuleType, started: list[tuple[int, str]]) -> None:
    assert run.main(["start"]) == 2
    assert started == []


# ---------------------------------------------------------------- the stop order


class FakeProc:
    def __init__(self, name: str, log: list[tuple[str, str]], *, stuck: bool = False) -> None:
        self.name, self.log, self.stuck, self.done = name, log, stuck, False
        self.pid = 4242

    def poll(self) -> int | None:
        return 0 if self.done else None

    def send_signal(self, signum: int) -> None:
        self.log.append((self.name, signal.Signals(signum).name))
        self.done = not self.stuck

    def wait(self, timeout: float | None = None) -> int:
        if not self.done:
            raise subprocess.TimeoutExpired(self.name, timeout or 0)
        return 0

    def kill(self) -> None:
        self.log.append((self.name, "SIGKILL"))
        self.done = True


def supervisor_with(run: ModuleType, log: list[tuple[str, str]], stuck: frozenset[str] = frozenset()) -> Any:
    supervisor = run.Supervisor(7860, "fictional")
    for name in ("postgres", "s3", "mailpit", "api", "worker", "web"):  # start order
        child = run.Child(name, ["true"], {})
        child.proc = FakeProc(name, log, stuck=name in stuck)
        supervisor.children[name] = child
    return supervisor


def test_the_children_stop_in_tiers_app_then_storage_then_postgres(run: ModuleType) -> None:
    log: list[tuple[str, str]] = []
    supervisor = supervisor_with(run, log)
    supervisor.stop_all()
    assert log == [
        ("web", "SIGTERM"),
        ("worker", "SIGTERM"),
        ("api", "SIGTERM"),
        ("mailpit", "SIGTERM"),
        ("s3", "SIGTERM"),
        ("postgres", "SIGINT"),  # Postgres's fast shutdown
    ]
    assert supervisor.children == {}


def test_a_child_that_ignores_the_signal_is_killed_after_its_grace(
    run: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "STOP_GRACE", {"s3": 0.0})
    log: list[tuple[str, str]] = []
    supervisor_with(run, log, stuck=frozenset({"s3"})).stop_all()
    assert log.index(("s3", "SIGKILL")) < log.index(("postgres", "SIGINT"))  # Postgres still stops last


# ---------------------------------------------------------------- one supervisor at a time


@pytest.fixture
def process() -> Iterator[Any]:
    """Start a short-lived Python process with the given extra argv (it exits on SIGUSR1 after writing a marker)."""
    started: list[subprocess.Popen[bytes]] = []

    def start(marker: Path, *argv: str) -> subprocess.Popen[bytes]:
        code = (
            "import pathlib, signal, sys, time\n"
            "def on_usr1(*_):\n"
            f"    pathlib.Path({str(marker)!r}).write_text('reset')\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGUSR1, on_usr1)\n"
            f"pathlib.Path({str(marker)!r} + '.ready').write_text('up')\n"
            "time.sleep(30)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", code, *argv])
        started.append(proc)
        deadline = time.monotonic() + 10
        while not Path(f"{marker}.ready").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return proc

    yield start
    for proc in started:
        proc.kill()
        proc.wait()


linux_only = pytest.mark.skipif(not LINUX_PROC, reason="the guard reads /proc/<pid>/cmdline (Linux)")


@linux_only
def test_a_second_supervisor_refuses_to_start(
    run: ModuleType, started: list[tuple[int, str]], process: Any, tmp_path: Path
) -> None:
    other = process(tmp_path / "marker", "/opt/infra/demo/space/run.py")
    run.PIDFILE.write_text(f"{other.pid}\n", encoding="utf-8")
    assert run.supervisor_pid() == other.pid
    assert run.main([]) == 1
    assert started == []


@linux_only
def test_a_stale_or_reused_pid_file_does_not_block_the_start(
    run: ModuleType, started: list[tuple[int, str]], process: Any, tmp_path: Path
) -> None:
    unrelated = process(tmp_path / "marker")  # alive, but not run.py: a pid reused by another program
    for pid in (unrelated.pid, os.getpid(), 2**22 + 1):  # another program, this very process, no such process
        run.PIDFILE.write_text(f"{pid}\n", encoding="utf-8")
        assert run.supervisor_pid() is None
    run.PIDFILE.write_text("not a pid\n", encoding="utf-8")
    assert run.supervisor_pid() is None
    assert run.main([]) == 0


@linux_only
def test_reset_signals_the_running_supervisor_only(run: ModuleType, home: Path, process: Any, tmp_path: Path) -> None:
    unrelated = process(tmp_path / "unrelated")
    run.PIDFILE.write_text(f"{unrelated.pid}\n", encoding="utf-8")
    assert run.main(["reset"]) == 1
    assert unrelated.poll() is None  # SIGUSR1 would have stopped it: it was never sent
    assert not (tmp_path / "unrelated").exists()

    supervisor = process(tmp_path / "supervisor", "run.py")
    run.PIDFILE.write_text(f"{supervisor.pid}\n", encoding="utf-8")
    assert run.main(["reset"]) == 0
    assert supervisor.wait(timeout=10) == 0
    assert (tmp_path / "supervisor").read_text(encoding="utf-8") == "reset"


def test_reset_without_a_pid_file_reports_none_running(run: ModuleType, home: Path) -> None:
    assert run.main(["reset"]) == 1


@linux_only
def test_a_restarted_container_whose_pid_file_names_this_very_supervisor_still_starts(tmp_path: Path) -> None:
    """After `docker restart`, run.pid survives and the new supervisor often gets the same pid (tini is 1): the guard
    must not mistake it for another supervisor. Checked from inside a process whose argv names run.py."""
    pidfile = tmp_path / "run.pid"
    code = (
        "import importlib.util, os, pathlib, sys\n"
        f"spec = importlib.util.spec_from_file_location('r', {str(RUN_PY)!r})\n"
        "run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)\n"
        f"run.PIDFILE = pathlib.Path({str(pidfile)!r})\n"
        "run.PIDFILE.write_text(f'{os.getpid()}\\n')\n"
        "print(run.supervisor_pid())\n"
    )
    found = subprocess.run([sys.executable, "-c", code, "run.py"], capture_output=True, text=True, check=True)
    assert found.stdout.strip() == "None"


# ---------------------------------------------------------------- PUBLIC_DEMO_FROZEN_AT, once per boot


def test_the_frozen_instant_is_iso_8601_utc_to_the_second(run: ModuleType) -> None:
    value = run.frozen_instant()
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0)
    assert value.endswith("+00:00")
    assert parsed.microsecond == 0
    assert abs(datetime.now(UTC) - parsed) < timedelta(seconds=5)


FROZEN = ("2026-10-13T12:00:00+00:00", "2026-10-14T00:01:00+00:00")


@pytest.fixture
def booting(run: ModuleType, home: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[tuple[str, ...]]]:
    """A supervisor whose boot runs for real (secrets, wipe, migrate order, start_app) except the processes: steps,
    spawns and readiness waits are recorded, with the PUBLIC_DEMO_FROZEN_AT each one was given."""
    events: list[tuple[str, ...]] = []
    instants = iter(FROZEN)

    def frozen() -> str:
        value = next(instants)
        events.append(("frozen", value))
        return value

    def step(self: Any, name: str, argv: list[str], env: dict[str, str], stdin: str | None = None) -> None:
        events.append(("step", " ".join(argv), env.get("PUBLIC_DEMO_FROZEN_AT", "")))

    def spawn(self: Any, child: Any) -> Any:
        self.children[child.name] = child
        events.append(("spawn", child.name, child.env.get("PUBLIC_DEMO_FROZEN_AT", "")))
        return child

    monkeypatch.setattr(run, "frozen_instant", frozen)
    monkeypatch.setattr(run.Supervisor, "start_postgres", lambda self: events.append(("postgres",)))
    monkeypatch.setattr(run.Supervisor, "start_storage", lambda self: events.append(("storage",)))
    monkeypatch.setattr(run.Supervisor, "step", step)
    monkeypatch.setattr(run.Supervisor, "spawn", spawn)
    monkeypatch.setattr(run.Supervisor, "wait_for", lambda self, *args: None)
    return run.Supervisor(7860, "fictional"), events


def test_the_frozen_instant_is_taken_after_the_seed_and_given_to_the_api_and_worker(
    run: ModuleType, booting: tuple[Any, list[tuple[str, ...]]]
) -> None:
    supervisor, events = booting
    supervisor.boot()
    steps = [event for event in events if event[0] == "step"]
    assert [event[1] for event in steps] == list(run.MIGRATE)
    assert all(event[2] == "" for event in steps)  # the migrate step and the seed run before the instant exists
    frozen_at = events.index(("frozen", FROZEN[0]))
    assert frozen_at == events.index(steps[-1]) + 1  # right after the seed
    assert events[frozen_at + 1 :] == [
        ("spawn", "api", FROZEN[0]),
        ("spawn", "worker", FROZEN[0]),
        ("spawn", "web", ""),
    ]


def test_a_crash_restarted_child_keeps_the_boots_frozen_instant(
    run: ModuleType, booting: tuple[Any, list[tuple[str, ...]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor, _ = booting
    supervisor.boot()
    restarted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        run.Child, "start", lambda self, stdin=None: restarted.append((self.name, self.env["PUBLIC_DEMO_FROZEN_AT"]))
    )
    for name in ("api", "worker"):
        child = supervisor.children[name]
        child.proc = FakeProc(name, [])
        child.proc.done = True  # it crashed
        child.restart_at = 0.0  # and its back-off is over
    supervisor.restart_crashed()
    assert restarted == [("api", FROZEN[0]), ("worker", FROZEN[0])]


def test_the_reset_takes_a_new_frozen_instant_after_its_own_seed(
    run: ModuleType, booting: tuple[Any, list[tuple[str, ...]]]
) -> None:
    supervisor, events = booting
    supervisor.boot()
    events.clear()
    supervisor.reset("test")
    steps = [event for event in events if event[0] == "step"]
    assert all(event[2] == "" for event in steps)  # the old instant is not handed to the new seed
    assert events.index(("frozen", FROZEN[1])) == events.index(steps[-1]) + 1
    assert [event for event in events if event[0] == "spawn"] == [
        ("spawn", "api", FROZEN[1]),
        ("spawn", "worker", FROZEN[1]),
        ("spawn", "web", ""),
    ]
