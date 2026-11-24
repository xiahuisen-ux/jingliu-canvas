"""Task-scoped macOS sleep assertions; display sleep and system settings stay unchanged."""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import urllib.request
import task_diagnostics


class KeepAwake:
    def __init__(self):
        self.process = None

    def start(self):
        if sys.platform != 'darwin':
            return
        if self.process is not None and self.process.poll() is None:
            return
        if self.process is not None:
            self.process.wait()
        try:
            # -i prevents idle system sleep; -s also protects on AC power.
            # No -d or -u: the screen can sleep and the user can lock it.
            self.process = subprocess.Popen(
                ['/usr/bin/caffeinate', '-i', '-s', '-w', str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            if self.process.poll() is not None:
                self.process.wait()
                raise OSError('caffeinate exited before the task started')
        except OSError as error:
            raise RuntimeError('无法启用生成任务防休眠保护，未开始模型计算；请检查 macOS caffeinate') from error

    def stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        except ProcessLookupError:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        task_diagnostics.cleanup(self.stop)


def runtime_active(state):
    """Queued jobs also count, including gaps between shots in one sequence."""
    return bool(state.get('busy') or any(j.get('status') in {'queued', 'running'} for j in state.get('jobs', [])))


def process_identity(pid):
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                            capture_output=True, text=True, timeout=3)
    return result.stdout.strip() if result.returncode == 0 else ''


def watch_running_server(pid, port, stopped):
    """Bridge an already-running server without restarting its active generation.

    New server processes use KeepAwake directly. This bridge exits with the exact
    old server process; it is not an installed launch agent or recurring job.
    """
    identity = process_identity(pid)
    if not identity:
        return
    guard = KeepAwake()
    # Ignore environment HTTP proxies for this local-only status request.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_active = None
    try:
        while not stopped.is_set() and process_identity(pid) == identity:
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/runtime', timeout=5) as response:
                    active = runtime_active(json.load(response))
            except (OSError, ValueError):
                # Keep the last assertion while an alive server is temporarily unresponsive.
                stopped.wait(2)
                continue
            if active:
                guard.start()
            else:
                guard.stop()
            if active != last_active:
                print('任务防休眠：' + ('已启用，屏幕可关闭' if active else '已释放，恢复正常休眠'), flush=True)
                last_active = active
            stopped.wait(2)
    finally:
        guard.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch-server', type=int, required=True)
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    watch_running_server(args.watch_server, args.port, stopped)
