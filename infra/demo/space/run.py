#!/usr/bin/env python3
"""The public demo's supervisor (P28 track PD; REQ-FND-04): the whole seeded product in one container, on one port.

Standard library only: the image's command (infra/demo/space/Dockerfile), run as uid 1000 under tini. Each boot:

1. generates throwaway secrets with infra/demo/demo.py's generators (kept in memory and handed to the children's
   environments only: never printed, never written down) and wipes the data directory (``~/data``);
2. initialises PostgreSQL 16 (scram-sha-256 on the socket and on 127.0.0.1, its only address) and applies
   infra/postgres/roles.sql, the owner's and app's logins, the ``bridge`` database and prepare_db.sql, as
   infra/postgres/init/00-bridge.sh does;
3. starts SeaweedFS (S3, its telemetry off) and Mailpit on 127.0.0.1 only;
4. runs infra/docker-compose.demo.yml's migrate step (migrations, buckets, the provenance key, the demo seed) with the
   demo compose's environment plus ``PUBLIC_DEMO=true``;
5. starts the API (127.0.0.1:8000), the job worker and the web app on ``PORT`` (default 7860, every interface): the
   only port a visitor reaches.

A child that crashes is restarted with back-off. At 03:00 Africa/Nairobi (00:00 UTC; Kenya keeps no daylight saving),
or on SIGUSR1, the nightly reset stops the children, wipes the data and boots again with new secrets. SIGTERM and
SIGINT stop the children in order (the web, worker and API, then S3 and Mailpit, then Postgres) and exit. One
supervisor per home: it refuses to start while ``~/run.pid`` names a live run.py, and ``reset`` signals only that.

    python3 run.py          boot and supervise (the image's CMD)
    python3 run.py reset    ask the running supervisor for a reset now (sends it SIGUSR1)

Environment: PORT (default 7860); PUBLIC_BASE_URL, else https://$SPACE_HOST (Hugging Face sets it), else the
codespace's forwarded address ($CODESPACE_NAME, $GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN), else
http://localhost:$PORT; COOKIE_SECURE (default true); PUBLIC_DEMO_CONTENT (fictional, the default, or full). Nothing
else reaches the app. Email stays in the internal Mailpit, SMS and payments are simulated, LLM calls answer with the
deterministic fallback, scanning and embeddings are the fakes. The one connection that leaves the container is the
worker's: a registered proposal's certificate gets a real RFC 3161 timestamp from a public timestamp service (DigiCert,
FreeTSA as the fallback; the app's defaults, as in ``make demo``), which sees only a hash. Demo only.
"""

# ruff: noqa: T201  (a command-line script: its usage and the reset command's answer are printed)
from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
INFRA = HERE.parents[1]  # infra/ in a checkout, /opt/infra in the image
HOME = Path(os.environ.get("DEMO_HOME") or Path.home())
DATA = HOME / "data"
PIDFILE = HOME / "run.pid"
BACKEND = Path(os.environ.get("DEMO_BACKEND_DIR", "/app"))
WEB = Path(os.environ.get("DEMO_WEB_DIR", "/web"))
PG_BIN = Path(os.environ.get("DEMO_PG_BIN", "/usr/lib/postgresql/16/bin"))
EAT = timezone(timedelta(hours=3), "EAT")
RESET_HOUR_EAT = 3
PG_PORT, API_PORT, SMTP_PORT, S3_PORT = 5432, 8000, 1025, 8333
# Every port the children listen on inside the container (SeaweedFS: master, volume, filer, S3 and their gRPC ports).
INTERNAL_PORTS = {PG_PORT, API_PORT, SMTP_PORT, 8025, S3_PORT, 8080, 8888, 9333, 18080, 18333, 18888, 19333}
STOP_SIGNALS = {"postgres": signal.SIGINT}  # Postgres's fast shutdown; SIGTERM would wait for clients to leave
# Seconds a child may take to stop before it is killed. SeaweedFS's filer waits on its own open gRPC streams and never
# finishes a graceful stop; its data is wiped at every boot, so it gets a short grace.
STOP_GRACE, STOP_SECONDS = {"s3": 3.0}, 10.0
# The demo compose's environment (infra/docker-compose.dev.yml's backend-env and the demo override), on loopback.
DEMO_ENV = {
    "APP_ENV": "dev",
    "FEATURE_TIER2_ENABLED": "true",
    "FEATURE_DEALS_ENABLED": "true",
    "ATTACHMENT_SCANNER": "fake",
    "EMBEDDER": "fake",
    "SMS_PROVIDER": "fake",
    "EMAIL_PROVIDER": "smtp",
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": str(SMTP_PORT),
    # SeaweedFS runs without S3 authentication here, as in the dev stack; boto3 still signs, so any key does.
    "OBJECT_STORE": "s3",
    "S3_ENDPOINT_URL": f"http://127.0.0.1:{S3_PORT}",
    "S3_ACCESS_KEY_ID": "dev",
    "S3_SECRET_ACCESS_KEY": "dev",
    # The web app, on 127.0.0.1, is the API's only client: the X-Forwarded-For it passes on (what the host's edge
    # proxy sends: Hugging Face, Codespaces, Caddy) names the visitor, so throttles are per visitor. With no edge
    # proxy in front, a visitor can choose that header: acceptable for a demo, never for production.
    "TRUSTED_PROXIES": "127.0.0.1",
    "PUBLIC_DEMO": "true",
}
APP_SECRETS = ("SECRET_KEY", "DATA_ENCRYPTION_KEY", "RECOVERY_CODE_PEPPER", "TIER2_LOCAL_KEK", "PROVENANCE_SIGNING_KEY")
INITDB = "-U postgres --auth-local=scram-sha-256 --auth-host=scram-sha-256 --encoding=UTF8 --locale=en_US.UTF-8"
# Ephemeral data, wiped at every boot: no fsync, which makes the migrations and the seed much faster.
PG_SETTINGS = {"listen_addresses": "127.0.0.1", "port": PG_PORT, "fsync": "off", "synchronous_commit": "off"}
LOGINS_SQL = """\\getenv owner_pw BRIDGE_OWNER_PASSWORD
\\getenv app_pw BRIDGE_APP_PASSWORD
ALTER ROLE bridge_owner LOGIN PASSWORD :'owner_pw';
ALTER ROLE bridge_app LOGIN PASSWORD :'app_pw';
CREATE DATABASE bridge OWNER bridge_owner;
"""
# The demo compose's flags (64 volume slots of 128 MB: the default sizes them from the free disk), on loopback only;
# no usage statistics sent to SeaweedFS (on by default), no Iceberg or Lance endpoints, no 10 s pause at stop.
WEED = (
    "-logtostderr=true server -s3 -ip=127.0.0.1 -ip.bind=127.0.0.1 -master.volumeSizeLimitMB=128 -volume.max=64 "
    "-master.telemetry=false -volume.preStopSeconds=0 -s3.port.iceberg=0 -s3.port.lance=0"
)
SEAWEED_SOCKETS = Path("/tmp")  # noqa: S108 - where SeaweedFS always puts its gRPC sockets (no flag moves them)
MIGRATE = (  # infra/docker-compose.demo.yml's migrate command, one step at a time
    "alembic upgrade head",
    "python -m bridge.storage ensure-buckets",
    "python -m bridge.provenance register-key --if-configured",
    "python -m bridge.seed --demo",
)
# backend/Dockerfile's CMD, on loopback (the 75 s keep-alive outlasts the web's idle proxy sockets: P16-F).
API = (
    f"uvicorn bridge.main:create_app --factory --host 127.0.0.1 --port {API_PORT} --proxy-headers "
    "--timeout-keep-alive 75"
)
_OUT = threading.Lock()
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # probes never go through a proxy


class Stopping(Exception):
    """SIGTERM or SIGINT arrived: unwind and stop."""


class BootError(Exception):
    """A boot step failed; the message says which."""


def log(message: str, source: str = "demo") -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _OUT:
        sys.stdout.write(f"{stamp} [{source}] {message}\n")
        sys.stdout.flush()


def new_secrets() -> dict[str, str]:
    """The demo's secrets, from infra/demo/demo.py's own generators (the same names and shapes as ``make demo``)."""
    spec = importlib.util.spec_from_file_location("bridge_demo_launcher", INFRA / "demo" / "demo.py")
    if spec is None or spec.loader is None:
        raise BootError(f"cannot load {INFRA / 'demo' / 'demo.py'}")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return {**launcher.compose_env_values(), **launcher.backend_env_values()}


def public_base_url(port: int) -> str:
    if url := os.environ.get("PUBLIC_BASE_URL", "").strip():
        return url.rstrip("/")
    if host := os.environ.get("SPACE_HOST", "").strip():
        return f"https://{host}"
    name = os.environ.get("CODESPACE_NAME", "").strip()
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "").strip()
    if name and domain:
        return f"https://{name}-{port}.{domain}"
    return f"http://localhost:{port}"


def next_reset(now: datetime) -> datetime:
    local = now.astimezone(EAT)
    due = local.replace(hour=RESET_HOUR_EAT, minute=0, second=0, microsecond=0)
    return due if due > local else due + timedelta(days=1)


def http_status(url: str) -> int | None:
    try:
        with _LOCAL.open(url, timeout=3) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return exc.code
    except (OSError, ValueError):
        return None


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wipe() -> None:
    """Empty the data directory (its contents only: it may be a mount point) and recreate the children's folders."""
    DATA.mkdir(parents=True, exist_ok=True)
    for entry in DATA.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for name in ("s3", "mail", "run"):
        (DATA / name).mkdir(mode=0o700)
    for stale in SEAWEED_SOCKETS.glob("seaweedfs-*.sock"):  # a killed SeaweedFS leaves them behind
        stale.unlink(missing_ok=True)


def supervisor_pid() -> int | None:
    """The pid ``run.pid`` names when that process is alive, is not this one, and runs run.py (start-demo.sh's check);
    None when the file is missing or stale, or its pid now belongs to another program."""
    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return None
    if pid == os.getpid() or not any(Path(os.fsdecode(arg)).name == "run.py" for arg in argv):
        return None
    return pid


class Child:
    """One supervised process; its output is copied to ours, one prefixed line at a time."""

    def __init__(self, name: str, argv: list[str], env: dict[str, str], cwd: Path | None = None) -> None:
        self.name, self.argv, self.env, self.cwd = name, argv, env, cwd
        self.stop_signal = STOP_SIGNALS.get(name, signal.SIGTERM)
        self.proc: subprocess.Popen[str] | None = None
        self.pump: threading.Thread | None = None
        self.started = 0.0
        self.failures = 0
        self.restart_at: float | None = None

    def start(self, stdin: str | None = None) -> None:
        self.proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            self.argv,
            env=self.env,
            cwd=self.cwd,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        if stdin is not None and self.proc.stdin is not None:
            self.proc.stdin.write(stdin)
            self.proc.stdin.close()
        self.pump = threading.Thread(target=self._copy_output, args=(self.proc,), daemon=True)
        self.pump.start()
        self.started, self.restart_at = time.monotonic(), None

    def _copy_output(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            log(line.rstrip("\n"), self.name)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None


class Supervisor:
    def __init__(self, port: int, content: str) -> None:
        self.port, self.content = port, content
        self.base_url = public_base_url(port)
        self.cookie_secure = os.environ.get("COOKIE_SECURE", "true").strip() or "true"
        self.secrets: dict[str, str] = {}
        self.children: dict[str, Child] = {}
        self.stopping = False
        self.reset_requested = False

    # ---------------------------------------------------------------- environments
    def base_env(self, **extra: str) -> dict[str, str]:
        path = f"{BACKEND / '.venv' / 'bin'}:{PG_BIN}:/usr/local/bin:/usr/bin:/bin"
        lang = os.environ.get("LANG", "C.UTF-8")
        return {"PATH": path, "HOME": str(HOME), "LANG": lang, "PYTHONUNBUFFERED": "1", **extra}

    def pg_env(self, **extra: str) -> dict[str, str]:
        password = self.secrets["POSTGRES_SUPERUSER_PASSWORD"]
        return self.base_env(TZ="Africa/Nairobi", PGPASSWORD=password, **extra)

    def app_env(self) -> dict[str, str]:
        s, db = self.secrets, f"127.0.0.1:{PG_PORT}/bridge"
        return self.base_env(
            **DEMO_ENV,
            PUBLIC_BASE_URL=self.base_url,
            COOKIE_SECURE=self.cookie_secure,
            PUBLIC_DEMO_CONTENT=self.content,
            DATABASE_URL=f"postgresql+psycopg://bridge_app:{s['BRIDGE_APP_PASSWORD']}@{db}",
            DATABASE_OWNER_URL=f"postgresql+psycopg://bridge_owner:{s['BRIDGE_OWNER_PASSWORD']}@{db}",
            **{name: s[name] for name in APP_SECRETS},
        )

    def web_env(self) -> dict[str, str]:
        return self.base_env(
            NODE_ENV="production",
            NEXT_TELEMETRY_DISABLED="1",
            PORT=str(self.port),
            HOSTNAME="0.0.0.0",  # noqa: S104 - the web app serves the container's one public port
            API_ORIGIN=f"http://127.0.0.1:{API_PORT}",
            COOKIE_SECURE=self.cookie_secure,
            PUBLIC_DEMO="true",
            PUBLIC_DEMO_CONTENT=self.content,
        )

    # ---------------------------------------------------------------- process helpers
    def spawn(self, child: Child) -> Child:
        child.start()
        self.children[child.name] = child
        log(f"started {child.name} (pid {child.pid})")
        return child

    def step(self, name: str, argv: list[str], env: dict[str, str], stdin: str | None = None) -> None:
        """Run one boot step to completion (abandoned on SIGTERM); a non-zero exit fails the boot."""
        child = Child(name, argv, env, cwd=BACKEND)
        child.start(stdin)
        assert child.proc is not None
        while child.proc.poll() is None:
            if self.stopping:
                child.proc.terminate()
                child.proc.wait()
                raise Stopping
            time.sleep(0.2)
        if child.pump is not None:
            child.pump.join(timeout=5)
        if child.proc.returncode != 0:
            raise BootError(f"{name} ({argv[0]}) exited with {child.proc.returncode}")

    def wait_for(self, what: str, ready: Callable[[], bool], timeout: float, watch: Child) -> None:
        deadline = time.monotonic() + timeout
        while not ready():
            if self.stopping:
                raise Stopping
            if not watch.alive():
                raise BootError(f"{watch.name} exited while starting")
            if time.monotonic() > deadline:
                raise BootError(f"{what} not ready after {timeout:.0f} s")
            time.sleep(0.25)

    def stop_all(self) -> None:
        """Stop in tiers, each tier's processes together: the app, then S3 and Mailpit, then Postgres."""
        for tier in (("web", "worker", "api"), ("mailpit", "s3"), ("postgres",)):
            running = [self.children.pop(name) for name in tier if name in self.children]
            for child in running:
                if child.alive() and child.proc is not None:
                    child.proc.send_signal(child.stop_signal)
            began = time.monotonic()
            for child in running:
                if child.proc is None:
                    continue
                grace = STOP_GRACE.get(child.name, STOP_SECONDS)
                try:
                    child.proc.wait(max(0.1, began + grace - time.monotonic()))
                except subprocess.TimeoutExpired:
                    log(f"{child.name} did not stop within {grace:.0f} s: killed")
                    child.proc.kill()
                    child.proc.wait()
                log(f"stopped {child.name}")

    # ---------------------------------------------------------------- boot
    def boot(self) -> None:
        if self.stopping:
            raise Stopping
        began = time.monotonic()
        self.reset_requested = False
        self.secrets = new_secrets()
        wipe()
        log(f"boot: data wiped, new secrets; site {self.base_url} (content: {self.content})")
        self.start_postgres()
        self.start_storage()
        for command in MIGRATE:
            self.step("migrate", command.split(), self.app_env())
        log("migrated and seeded")
        self.start_app()
        log(f"ready in {time.monotonic() - began:.0f} s: {self.base_url} (port {self.port})")

    def start_postgres(self) -> None:
        pgdata, run, sql = DATA / "postgres", DATA / "run", INFRA / "postgres"
        pwfile = run / "superuser.pw"  # initdb reads the superuser's password from a file; removed right after
        with os.fdopen(os.open(pwfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
            handle.write(self.secrets["POSTGRES_SUPERUSER_PASSWORD"] + "\n")
        try:
            initdb = [str(PG_BIN / "initdb"), "-D", str(pgdata), f"--pwfile={pwfile}", *INITDB.split()]
            self.step("initdb", initdb, self.pg_env())
        finally:
            pwfile.unlink(missing_ok=True)
        settings = {**PG_SETTINGS, "unix_socket_directories": run}
        argv = [str(PG_BIN / "postgres"), "-D", str(pgdata), *(f"-c{key}={value}" for key, value in settings.items())]
        postgres = self.spawn(Child("postgres", argv, self.pg_env()))
        isready = [str(PG_BIN / "pg_isready"), "-q", "-h", "127.0.0.1", "-p", str(PG_PORT)]
        self.wait_for("postgres", lambda: subprocess.run(isready, check=False).returncode == 0, 60, postgres)  # noqa: S603
        psql = [str(PG_BIN / "psql"), *f"-X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p {PG_PORT} -U postgres".split()]
        self.step("psql", [*psql, "-d", "postgres", "-f", str(sql / "roles.sql")], self.pg_env())
        owner, app = self.secrets["BRIDGE_OWNER_PASSWORD"], self.secrets["BRIDGE_APP_PASSWORD"]
        logins = self.pg_env(BRIDGE_OWNER_PASSWORD=owner, BRIDGE_APP_PASSWORD=app)
        self.step("psql", [*psql, "-d", "postgres", "-f", "-"], logins, stdin=LOGINS_SQL)  # \getenv: no secret in argv
        self.step("psql", [*psql, "-d", "bridge", "-f", str(sql / "prepare_db.sql")], self.pg_env())
        log("postgres ready: roles, logins and the bridge database")

    def start_storage(self) -> None:
        run = DATA / "run"
        sockets = [f"-filer.localSocket={run / 'filer.sock'}", f"-s3.localSocket={run / 's3.sock'}"]
        weed = ["weed", *WEED.split(), f"-dir={DATA / 's3'}", *sockets]
        s3 = self.spawn(Child("s3", weed, self.base_env(), cwd=DATA / "s3"))
        mailbox = f"--database={DATA / 'mail' / 'mailpit.db'}"
        mailpit = ["mailpit", "--listen=127.0.0.1:8025", f"--smtp=127.0.0.1:{SMTP_PORT}", "--disable-version-check"]
        mail = self.spawn(Child("mailpit", [*mailpit, mailbox], self.base_env()))
        self.wait_for("s3", lambda: http_status(f"http://127.0.0.1:{S3_PORT}/healthz") == 200, 120, s3)
        self.wait_for("mailpit", lambda: port_open(SMTP_PORT), 60, mail)
        log("s3 and mailpit ready")

    def start_app(self) -> None:
        env = self.app_env()
        api_env = {key: value for key, value in env.items() if key != "PROVENANCE_SIGNING_KEY"}  # the API never signs
        api = self.spawn(Child("api", API.split(), api_env, cwd=BACKEND))
        self.spawn(Child("worker", ["procrastinate", "--app=bridge.jobs.app.app", "worker"], env, cwd=BACKEND))
        web = self.spawn(Child("web", ["node", "server.js"], self.web_env(), cwd=WEB))
        self.wait_for("api", lambda: http_status(f"http://127.0.0.1:{API_PORT}/healthz") == 200, 120, api)
        self.wait_for("web", lambda: http_status(f"http://127.0.0.1:{self.port}/") == 200, 120, web)

    def boot_with_retries(self, attempts: int = 3) -> None:
        for attempt in range(1, attempts + 1):
            try:
                self.boot()
                return
            except BootError as exc:
                log(f"boot failed ({exc}); attempt {attempt} of {attempts}")
                self.stop_all()
                if attempt == attempts:
                    raise
                pause = time.monotonic() + 10 * attempt
                while time.monotonic() < pause:
                    if self.stopping:
                        raise Stopping from exc
                    time.sleep(0.5)

    # ---------------------------------------------------------------- supervision
    def restart_crashed(self) -> None:
        now = time.monotonic()
        for child in list(self.children.values()):
            if child.alive():
                if child.failures and now - child.started > 60:
                    child.failures = 0  # it stayed up: the next crash starts the back-off again
                continue
            if child.restart_at is None:
                child.failures += 1
                delay = min(60, 2**child.failures)
                child.restart_at = now + delay
                code = child.proc.returncode if child.proc else None
                log(f"{child.name} exited with {code}; restarting in {delay} s")
            elif now >= child.restart_at:
                child.start()
                log(f"restarted {child.name} (pid {child.pid})")

    def reset(self, why: str) -> None:
        began = time.monotonic()
        log(f"reset ({why}): stopping the children")
        self.stop_all()
        self.boot_with_retries()
        log(f"reset done in {time.monotonic() - began:.0f} s")

    def _on_stop(self, _signum: int, _frame: Any) -> None:
        self.stopping = True  # handlers only set flags; the main loop logs and acts

    def _on_reset(self, _signum: int, _frame: Any) -> None:
        self.reset_requested = True

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._on_stop)
        signal.signal(signal.SIGINT, self._on_stop)
        signal.signal(signal.SIGUSR1, self._on_reset)
        HOME.mkdir(parents=True, exist_ok=True)
        PIDFILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
        code = 0
        try:
            self.boot_with_retries()
            due = next_reset(datetime.now(UTC))
            log(f"next nightly reset: {due:%Y-%m-%d %H:%M} EAT")
            while not self.stopping:
                if self.reset_requested or datetime.now(UTC) >= due:
                    self.reset("requested" if self.reset_requested else "nightly, 03:00 EAT")
                    due = next_reset(datetime.now(UTC))
                    log(f"next nightly reset: {due:%Y-%m-%d %H:%M} EAT")
                    continue
                self.restart_crashed()
                time.sleep(1)
        except Stopping:
            pass
        except BootError:
            code = 1
        finally:
            log("shutting down" if code == 0 else "giving up after repeated boot failures")
            self.stop_all()
            PIDFILE.unlink(missing_ok=True)
        log("stopped")
        return code


def request_reset() -> int:
    pid = supervisor_pid()
    if pid is None:
        print(f"run.py: no running supervisor to reset ({PIDFILE} names none)", file=sys.stderr)
        return 1
    os.kill(pid, signal.SIGUSR1)
    print(f"run.py: reset requested (supervisor pid {pid}); its log shows the progress")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["reset"]:
        return request_reset()
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    port_text = os.environ.get("PORT", "7860").strip() or "7860"
    content = os.environ.get("PUBLIC_DEMO_CONTENT", "fictional").strip() or "fictional"
    if not port_text.isdigit() or not 0 < int(port_text) < 65536 or int(port_text) in INTERNAL_PORTS:
        print(f"run.py: PORT={port_text} is not a free port (used inside: {sorted(INTERNAL_PORTS)})", file=sys.stderr)
        return 2
    if content not in {"fictional", "full"}:
        print(f"run.py: PUBLIC_DEMO_CONTENT={content} must be fictional or full", file=sys.stderr)
        return 2
    if (other := supervisor_pid()) is not None:
        print(f"run.py: a supervisor is already running (pid {other}); `run.py reset` restarts it", file=sys.stderr)
        return 1
    return Supervisor(int(port_text), content).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
