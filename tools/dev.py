"""Start Panther's complete local API, UI and generation workers together."""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

from dotenv import dotenv_values
from dev_server import Store
from dev_playback_worker import private_root

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ('editorial', 'image', 'transcription', 'summary', 'playback', 'video', 'narration', 'episode', 'thumbnail')
SERVICES = {'image': 'images', 'episode': 'episodes'}
LOCKS = {'image': 'images'}


def preflight(env_file):
    path = Path(env_file).expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Create a private .env file at the repository root and run chmod 600 .env.')
    values = {**{key: value for key, value in dotenv_values(path).items() if isinstance(value, str)}, **os.environ}
    missing = [name for name in ('OPENAI_API_KEY', 'FAL_API_KEY', 'ELEVENLABS_API_KEY') if not values.get(name, '').strip()]
    if missing:
        raise ValueError('Missing local generation credentials: ' + ', '.join(missing))
    absent = [tool for tool in ('ffmpeg', 'ffprobe', 'npm') if not shutil.which(tool)]
    if absent:
        raise ValueError('Install required local tools: ' + ', '.join(absent))
    return values


def available_processors(database):
    """Reject already-owned worker locks before spawning an overlapping stack."""
    for worker in WORKERS:
        lock_path = database.with_name(database.name + '.' + LOCKS.get(worker, worker) + '.lock')
        with lock_path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(f'{worker.capitalize()} is already running for this database. Stop the existing stack after active provider requests finish.') from exc


def wait_ready(children, store, started_at, root, *, timeout=45):
    deadline = time.monotonic() + timeout
    pending = {name for name, _ in children}
    while pending:
        for worker, child in children:
            if child.poll() is not None:
                raise ValueError(f'{worker.capitalize()} worker did not start. See {root / (worker + ".log")}.')
            service = store.get('service', SERVICES.get(worker, worker)) or {}
            if service.get('status') == 'BLOCKED' and service.get('updatedAt', 0) >= started_at:
                raise ValueError(f'{worker.capitalize()} is blocked: {service.get("message") or "check its configuration"}. See {root / (worker + ".log")}.')
            if service.get('status') == 'RUNNING' and service.get('updatedAt', 0) >= started_at:
                pending.discard(worker)
        if not pending:
            return
        if time.monotonic() >= deadline:
            raise ValueError('Processors did not become ready: ' + ', '.join(sorted(pending)) + f'. See logs in {root}.')
        time.sleep(.1)


def wait_server(child, port, root, *, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        if child.poll() is not None:
            raise ValueError(f'Local API did not start. See {root / "server.log"}.')
        with socket.socket() as check:
            if check.connect_ex(('127.0.0.1', port)) == 0:
                return
        if time.monotonic() >= deadline:
            raise ValueError(f'Local API did not bind port {port}. See {root / "server.log"}.')
        time.sleep(.1)


def run(port, database, work_dir, env_file, build=True):
    os.umask(0o077)
    environment = preflight(env_file)
    with socket.socket() as check:
        if check.connect_ex(('127.0.0.1', port)) == 0:
            raise ValueError(f'Port {port} is already running. Stop that local server before starting the full stack.')
    if build:
        subprocess.run(['npm', 'run', 'build', '--prefix', str(ROOT / 'web/ui')], cwd=ROOT, check=True)
    root = private_root(work_dir)
    store = Store(database)
    database = store.path
    available_processors(database)
    children, logs = [], []
    stopping = False
    reload_server = False
    def stop(*_args):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    def reload_api(*_args):
        nonlocal reload_server
        reload_server = True
    signal.signal(signal.SIGHUP, reload_api)
    try:
        started_at = time.time()
        for worker in WORKERS:
            log = (root / (worker + '.log')).open('ab')
            logs.append(log)
            command = [sys.executable, str(ROOT / 'tools' / ('dev_' + worker + '_worker.py')), '--database', str(database), '--work-dir', str(root / worker)]
            if worker in {'editorial', 'image', 'transcription', 'summary', 'video', 'narration'}:
                command += ['--env-file', str(env_file)]
            if worker in {'editorial', 'summary'}:
                command += ['--model', environment.get('PANTHER_EDITORIAL_MODEL', 'gpt-5-mini')]
            children.append((worker, subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)))
        # Do not expose the app until every required processor has started successfully.
        wait_ready(children, store, started_at, root)
        log = (root / 'server.log').open('ab')
        logs.append(log)
        # Only workers receive provider keys. The server loads credentials narrowly for voice listing.
        server_environment = {key: value for key, value in os.environ.items() if key not in {'OPENAI_API_KEY', 'FAL_API_KEY', 'ELEVENLABS_API_KEY', 'XAI_API_KEY'}}
        children.append(('server', subprocess.Popen([sys.executable, str(ROOT / 'tools/dev_server.py'), '--database', str(database), '--port', str(port)], cwd=ROOT, env=server_environment, stdout=log, stderr=subprocess.STDOUT)))
        wait_server(children[-1][1], port, root)
        print(f'Panther is running at http://127.0.0.1:{port}/ — logs: {root}', flush=True)
        while not stopping:
            if reload_server:
                # Refresh API code without interrupting any paid worker request.
                previous = children[-1][1]
                previous.terminate()
                previous.wait(timeout=10)
                replacement = subprocess.Popen([sys.executable, str(ROOT / 'tools/dev_server.py'), '--database', str(database), '--port', str(port)], cwd=ROOT, env=server_environment, stdout=log, stderr=subprocess.STDOUT)
                children[-1] = ('server', replacement)
                wait_server(replacement, port, root)
                reload_server = False
            for worker, child in children:
                if child.poll() is not None:
                    raise ValueError(f'{worker.capitalize()} stopped. See {root / (worker + ".log")}.')
            time.sleep(1)
    finally:
        for _, child in children:
            if child.poll() is None:
                child.terminate()
        for _, child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        for log in logs:
            log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--database', type=Path, default=Path.home() / '.local/state/panther/development.sqlite')
    parser.add_argument('--work-dir', type=Path, default=Path.home() / '.local/state/panther/development-workers')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args()
    try:
        run(args.port, args.database, args.work_dir, args.env_file, not args.no_build)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
