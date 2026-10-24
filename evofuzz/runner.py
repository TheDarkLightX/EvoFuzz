"""Bounded subprocess transport; no shell and no claim of sandbox isolation."""
from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import threading
import time


@dataclass(frozen=True)
class ProcessResult:
    status: str
    code: int | None
    stdout: bytes
    stderr: bytes


def execute(command, payload, cwd, timeout_ms, output_bytes):
    try:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name == "posix")
    except OSError as exc:
        return ProcessResult("launch_error", None, b"", str(exc).encode()[:output_bytes])
    buffers = [bytearray(), bytearray()]
    lock = threading.Lock()
    exceeded = threading.Event()
    stopping = threading.Event()

    def stop():
        if stopping.is_set():
            return
        stopping.set()
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, PermissionError):
            pass

    def drain(stream, index):
        try:
            while chunk := stream.read1(4096):
                with lock:
                    remaining = output_bytes - sum(map(len, buffers))
                    buffers[index].extend(chunk[:max(0, remaining)])
                    if len(chunk) > remaining:
                        exceeded.set()
                if exceeded.is_set():
                    stop()
        except (OSError, ValueError):
            pass

    def send():
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    threads = [threading.Thread(target=drain, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, 1), daemon=True),
               threading.Thread(target=send, daemon=True)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout_ms / 1000
    timed_out = False
    while process.poll() is None or any(t.is_alive() for t in threads):
        if time.monotonic() >= deadline:
            timed_out = True
            stop()
            break
        time.sleep(0.002)
    # Also clean up ordinary child processes left behind by a completed parent.
    stop()
    process.wait()
    for thread in threads:
        thread.join(timeout=0.2)
    for stream, thread in zip((process.stdout, process.stderr, process.stdin), threads):
        if thread.is_alive():
            # An escaping child may retain a pipe; closing its reader here can
            # block on the reader thread's lock. This transport is not a sandbox.
            continue
        try:
            stream.close()
        except OSError:
            pass
    status = "output_limit" if exceeded.is_set() else "timeout" if timed_out else "completed"
    return ProcessResult(status, process.returncode, bytes(buffers[0]), bytes(buffers[1]))
