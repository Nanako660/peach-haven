"""Unified command-line management for the local compatibility servers.

One entry point starts/stops both the HTTP SDK server (8080) and the game TCP
server (21001), and exposes status, logs, LAN address, account, fixture and
smoke-test commands. Run from the repository root:

    python -m server.cli start
    python -m server.cli status
    python -m server.cli account list
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from .config import load_settings
from .storage import Storage

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "server" / "data"
HTTP_PID_FILE = DATA_DIR / "http.pid"
TCP_PID_FILE = DATA_DIR / "game_tcp.pid"


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def _terminate(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def _spawn(pid_file: Path, argv: Sequence[str], stdout: Path, stderr: Path) -> subprocess.Popen:
    stdout.parent.mkdir(parents=True, exist_ok=True)
    with stdout.open("ab") as out, stderr.open("ab") as err:
        proc = subprocess.Popen(
            [sys.executable, *argv],
            cwd=str(ROOT_DIR),
            stdout=out,
            stderr=err,
        )
    _write_pid(pid_file, proc.pid)
    return proc


def _settings(args: argparse.Namespace) -> Any:
    overrides: dict[str, Any] = {}
    if getattr(args, "http_port", None) is not None:
        overrides["http.port"] = args.http_port
    if getattr(args, "tcp_port", None) is not None:
        overrides["game.tcp_port"] = args.tcp_port
    return load_settings(args.config, overrides=overrides)


def _http_health(base: str, port: int, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{base}:{port}/healthz", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def lan_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))
        addresses.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return addresses


def cmd_start(args: argparse.Namespace) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = _settings(args)
    data_dir = settings.logging.data_dir
    http_port = settings.http.port
    tcp_port = settings.game.tcp_port

    config_argv = ["--config", str(args.config)] if args.config else []
    http_argv = ["-m", "server.main", *config_argv]
    tcp_argv = ["-m", "server.game_tcp", *config_argv]
    if args.http_port is not None:
        http_argv += ["--port", str(args.http_port)]
    if args.tcp_port is not None:
        tcp_argv += ["--port", str(args.tcp_port)]

    http_stdout = data_dir / "uvicorn.stdout.log"
    http_stderr = data_dir / "uvicorn.stderr.log"
    tcp_stdout = data_dir / "game_tcp.stdout.log"
    tcp_stderr = data_dir / "game_tcp.stderr.log"

    tcp_proc = _spawn(TCP_PID_FILE, tcp_argv, tcp_stdout, tcp_stderr)

    if getattr(args, "foreground", False):
        try:
            import uvicorn

            from .main import create_app

            uvicorn.run(create_app(settings), host=settings.http.host, port=http_port, reload=False)
        finally:
            _terminate(tcp_proc.pid)
            TCP_PID_FILE.unlink(missing_ok=True)
        return 0

    http_proc = _spawn(HTTP_PID_FILE, http_argv, http_stdout, http_stderr)

    deadline = time.time() + 15
    ready = False
    while time.time() < deadline:
        if _http_health("http://127.0.0.1", http_port) is not None and _port_open("127.0.0.1", tcp_port):
            ready = True
            break
        time.sleep(0.5)

    print(f"HTTP SDK server : http://0.0.0.0:{http_port} (pid={http_proc.pid})")
    print(f"Game TCP server : tcp://0.0.0.0:{tcp_port} (pid={tcp_proc.pid})")
    if ready:
        print("status          : ready")
    else:
        print("status          : starting (check `python -m server.cli status`)")
    ips = lan_addresses()
    if ips:
        print("LAN address     : " + "  ".join(f"http://{ip}:{http_port}" for ip in ips))
    print("default account : test / test1234")
    print("logs            : " + str(data_dir))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    for pid_file in (HTTP_PID_FILE, TCP_PID_FILE):
        pid = _read_pid(pid_file)
        if pid is not None:
            print(f"stopping pid {pid} ({pid_file.name})")
            _terminate(pid)
        pid_file.unlink(missing_ok=True)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings(args)
    http_port = settings.http.port
    tcp_port = settings.game.tcp_port
    http_pid = _read_pid(HTTP_PID_FILE)
    tcp_pid = _read_pid(TCP_PID_FILE)
    health = _http_health("http://127.0.0.1", http_port)

    print(f"HTTP SDK (port {http_port}): pid={http_pid or '-'} health={'ok' if health else 'down'}")
    print(f"Game TCP (port {tcp_port}): pid={tcp_pid or '-'} listen={'ok' if _port_open('127.0.0.1', tcp_port) else 'down'}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    settings = _settings(args)
    health = _http_health("http://127.0.0.1", settings.http.port)
    if health is None:
        print("health check failed: server is not responding")
        return 1
    print(json.dumps(health, ensure_ascii=False, indent=2))
    return 0


def cmd_lan(args: argparse.Namespace) -> int:
    settings = _settings(args)
    addresses = lan_addresses()
    if not addresses:
        print("no LAN address detected")
        return 1
    for ip in addresses:
        print(f"{ip}  ->  HTTP {ip}:{settings.http.port}  TCP {ip}:{settings.game.tcp_port}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    settings = _settings(args)
    data_dir = settings.logging.data_dir
    files: list[Path] = []
    if args.service in ("http", "all"):
        files += [data_dir / "uvicorn.stdout.log", data_dir / "uvicorn.stderr.log", data_dir / settings.logging.server_log]
    if args.service in ("game", "all"):
        files += [data_dir / "game_tcp.stdout.log", data_dir / "game_tcp.stderr.log", data_dir / settings.logging.game_tcp_log]

    for path in files:
        if path.exists():
            print(f"===== {path.name} =====")
            _tail(path, args.lines)
    if not args.follow:
        return 0

    print("\nfollowing new output (Ctrl+C to stop)...")
    positions = {path: (path.stat().st_size if path.exists() else 0) for path in files}
    try:
        while True:
            for path in files:
                if not path.exists():
                    continue
                size = path.stat().st_size
                if size > positions[path]:
                    with path.open("rb") as handle:
                        handle.seek(positions[path])
                        sys.stdout.write(handle.read().decode("utf-8", "replace"))
                        sys.stdout.flush()
                    positions[path] = size
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    return 0


def _tail(path: Path, lines: int) -> None:
    try:
        text = path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return
    sys.stdout.write("\n".join(text.splitlines()[-lines:]) + "\n")


def _find_user_id(storage: Storage, username: str) -> int | None:
    target = username.strip().lower()
    for row in storage.list_users():
        if row["username"].lower() == target:
            return int(row["id"])
    return None


def cmd_account(args: argparse.Namespace) -> int:
    storage = Storage()
    storage.initialize()

    if args.action == "list":
        for row in storage.list_users():
            print(f"{row['id']}\t{row['username']}")
        return 0

    if args.action == "create":
        row = storage.create_user(args.username, args.password)
        if row is None:
            print(f"failed to create account '{args.username}' (may already exist)")
            return 1
        print(f"created account: {row['username']} (id={row['id']})")
        return 0

    user_id = _find_user_id(storage, args.username)
    if user_id is None:
        print(f"account not found: {args.username}")
        return 1

    if args.action == "password":
        if storage.set_password(args.username, args.password):
            print(f"password updated for '{args.username}'")
            return 0
        print(f"failed to update password for '{args.username}'")
        return 1

    if args.action == "credit":
        balance = storage.credit_wallet(
            user_id,
            args.amount,
            reference_key=f"cli-credit:{user_id}:{time.time_ns()}",
            metadata={"source": "server.cli"},
        )
        print(f"credited {args.amount} G-points to '{args.username}' (balance={balance})")
        return 0

    if args.action == "balance":
        print(f"{args.username}: {storage.wallet_balance(user_id)} G-points")
        return 0

    print("unknown account action")
    return 1


def cmd_fixture(args: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, "-m", "server.fixture_tool", *args.remaining])


def cmd_smoke(args: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, "-m", "server.client", *args.remaining])


def cmd_test(args: argparse.Namespace) -> int:
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=str(ROOT_DIR)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="server.cli", description="Local compatibility server management")
    parser.add_argument("--config", help="path to a TOML configuration file")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start both servers")
    start.add_argument("--http-port", type=int)
    start.add_argument("--tcp-port", type=int)
    start.add_argument("--foreground", action="store_true", help="run HTTP server in the foreground")
    start.set_defaults(func=cmd_start)

    stop = sub.add_parser("stop", help="stop both servers")
    stop.set_defaults(func=cmd_stop)

    restart = sub.add_parser("restart", help="stop then start both servers")
    restart.add_argument("--http-port", type=int)
    restart.add_argument("--tcp-port", type=int)
    restart.set_defaults(func=cmd_restart)

    status = sub.add_parser("status", help="show server status")
    status.set_defaults(func=cmd_status)

    health = sub.add_parser("health", help="query /healthz")
    health.set_defaults(func=cmd_health)

    lan = sub.add_parser("lan", help="print LAN addresses")
    lan.set_defaults(func=cmd_lan)

    logs = sub.add_parser("logs", help="tail server logs")
    logs.add_argument("--service", choices=["http", "game", "all"], default="all")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("-n", "--lines", type=int, default=30)
    logs.set_defaults(func=cmd_logs)

    account = sub.add_parser("account", help="manage local accounts")
    account_sub = account.add_subparsers(dest="action", required=True)
    account_sub.add_parser("list").set_defaults(action="list")
    create = account_sub.add_parser("create")
    create.add_argument("username")
    create.add_argument("password")
    create.set_defaults(action="create")
    password = account_sub.add_parser("password")
    password.add_argument("username")
    password.add_argument("password")
    password.set_defaults(action="password")
    credit = account_sub.add_parser("credit")
    credit.add_argument("username")
    credit.add_argument("amount", type=int)
    credit.set_defaults(action="credit")
    balance = account_sub.add_parser("balance")
    balance.add_argument("username")
    balance.set_defaults(action="balance")
    account.set_defaults(func=cmd_account)

    fixture = sub.add_parser("fixture", help="delegate to server.fixture_tool")
    fixture.add_argument("remaining", nargs=argparse.REMAINDER)
    fixture.set_defaults(func=cmd_fixture)

    smoke = sub.add_parser("smoke", help="run the encrypted client smoke test")
    smoke.add_argument("remaining", nargs=argparse.REMAINDER)
    smoke.set_defaults(func=cmd_smoke)

    test = sub.add_parser("test", help="run the unittest suite")
    test.set_defaults(func=cmd_test)

    return parser


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    return cmd_start(args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
