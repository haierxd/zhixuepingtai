"""Start and gracefully stop this checkout's Windows demo server."""
from __future__ import annotations

import argparse
import asyncio
import errno
import os
import socket
import subprocess
import sys
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "app" / "data" / "windows-launcher"
READY = RUNTIME / "port.txt"
STOP = RUNTIME / "stop"
LOG = RUNTIME / "server.log"
WAIT_SECONDS = 35


@contextmanager
def lock(name: str, timeout: float = 0):
    import msvcrt

    deadline = time.monotonic() + timeout
    with (RUNTIME / name).open("a+b") as file:
        while True:
            file.seek(0)
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.1)
        try:
            yield True
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


def bind_socket() -> socket.socket:
    # Keep the chosen socket open: the port cannot be taken between probing and startup.
    for port in (*range(8081, 8091), 0):
        bound = socket.socket()
        try:
            bound.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            bound.bind(("127.0.0.1", port))
            return bound
        except OSError as exc:
            bound.close()
            if port == 0 or exc.winerror not in {10013, 10048}:
                raise
    raise RuntimeError("找不到可用的本机端口。")


async def serve(bound: socket.socket) -> None:
    import uvicorn

    from scripts import offline

    settings = offline.enable()
    offline.STREAM_DELAY = 0.02
    from app.main import app

    print(f"[offline] 离线模式，数据目录 {settings.db_path.parent}")
    port = bound.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, timeout_graceful_shutdown=20))

    async def monitor():
        while not server.should_exit:
            if STOP.exists():
                server.should_exit = True
                break
            if server.started and not READY.exists():
                pending = READY.with_suffix(".tmp")
                pending.write_text(str(port), encoding="ascii")
                pending.replace(READY)
            await asyncio.sleep(0.1)

    task = asyncio.create_task(monitor())
    try:
        await server.serve(sockets=[bound])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def worker() -> None:
    with lock("server.lock") as acquired:
        if not acquired:
            return
        try:
            with bind_socket() as bound:
                asyncio.run(serve(bound))
        finally:
            READY.unlink(missing_ok=True)


def start(open_browser: bool) -> None:
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise RuntimeError("找不到新版前端，请先在 frontend 目录执行 npm ci 和 npm run build。")
    process = None
    with lock("server.lock") as available:
        if available:
            READY.unlink(missing_ok=True)
            STOP.unlink(missing_ok=True)
    if available:
        with LOG.open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-u", "-m", "scripts.windows_launcher", "_serve"],
                cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    elif STOP.exists():
        raise RuntimeError("智学正在关闭，请稍后再启动。")

    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            break
        try:
            port = int(READY.read_text(encoding="ascii"))
        except FileNotFoundError:
            time.sleep(0.1)
            continue
        url = f"http://127.0.0.1:{port}/"
        print(f"智学已启动：{url}")
        if open_browser and not webbrowser.open(url):
            raise RuntimeError(f"无法自动打开浏览器。请在浏览器中打开 {url}")
        return
    if process is not None and process.poll() is None:
        STOP.touch()
    raise RuntimeError(f"智学未能启动。日志：{LOG}")


def stop() -> None:
    with lock("server.lock") as available:
        if available:
            print("智学未通过启动按钮运行。")
            return
        STOP.touch()
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        with lock("server.lock") as available:
            if available:
                print("智学已关闭。")
                return
        time.sleep(0.1)
    raise RuntimeError(f"关闭请求已发送，智学仍在处理。日志：{LOG}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "_serve"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("此启动器仅适用于 Windows。")
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        if args.action == "_serve":
            worker()
        else:
            with lock("control.lock", timeout=WAIT_SECONDS) as acquired:
                if not acquired:
                    raise RuntimeError("另一个启动或关闭操作仍在进行，请稍后再试。")
                if args.action == "start":
                    start(not args.no_browser)
                else:
                    stop()
    except (OSError, RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
