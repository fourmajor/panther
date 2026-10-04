"""Full local startup requires fresh processor heartbeats, tools, and private keys."""
import fcntl
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
spec = importlib.util.spec_from_file_location('dev_launcher', Path(__file__).parents[1] / 'tools/dev.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_preflight_rejects_missing_keys_and_permissions_without_exposing_values(tmp_path, monkeypatch):
    for key in ('OPENAI_API_KEY', 'FAL_API_KEY', 'ELEVENLABS_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    file = tmp_path / '.env'
    file.write_text('OPENAI_API_KEY=fictional-secret\n')
    file.chmod(0o600)
    with pytest.raises(ValueError) as caught:
        launcher.preflight(file)
    assert 'FAL_API_KEY' in str(caught.value) and 'fictional-secret' not in str(caught.value)
    file.chmod(0o644)
    with pytest.raises(ValueError, match='chmod 600'):
        launcher.preflight(file)


def test_preflight_handles_bare_dotenv_keys_and_requires_local_tools(tmp_path, monkeypatch):
    file = tmp_path / '.env'
    file.write_text('OPENAI_API_KEY=example\nFAL_API_KEY=example\nELEVENLABS_API_KEY=example\nOPTIONAL_VALUE\n')
    file.chmod(0o600)
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: None if name == 'ffmpeg' else '/fictional/tool')
    with pytest.raises(ValueError, match='ffmpeg'):
        launcher.preflight(file)
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: '/fictional/tool')
    assert all(isinstance(value, str) for value in launcher.preflight(file).values())


def test_readiness_requires_all_fresh_database_heartbeats(tmp_path):
    store = launcher.Store(tmp_path / 'private.sqlite')
    child = SimpleNamespace(poll=lambda: None)
    children = [('image', child), ('episode', child), ('editorial', child)]
    for service in ('images', 'episodes'):
        store.put('service', service, {'status': 'RUNNING', 'updatedAt': 11})
    store.put('service', 'editorial', {'status': 'RUNNING', 'updatedAt': 9})
    with pytest.raises(ValueError, match='editorial'):
        launcher.wait_ready(children, store, 10, tmp_path, timeout=0)
    store.put('service', 'editorial', {'status': 'RUNNING', 'updatedAt': 11})
    launcher.wait_ready(children, store, 10, tmp_path, timeout=0)


def test_readiness_rejects_crashed_or_blocked_processors(tmp_path):
    store = launcher.Store(tmp_path / 'private.sqlite')
    with pytest.raises(ValueError, match='did not start'):
        launcher.wait_ready([('video', SimpleNamespace(poll=lambda: 1))], store, 10, tmp_path)
    store.put('service', 'video', {'status': 'BLOCKED', 'updatedAt': 11, 'message': 'Credential missing'})
    with pytest.raises(ValueError, match='Credential missing'):
        launcher.wait_ready([('video', SimpleNamespace(poll=lambda: None))], store, 10, tmp_path)


def test_launcher_rejects_existing_worker_lock_before_spawning(tmp_path):
    database = tmp_path / 'private.sqlite'
    lock_path = database.with_name(database.name + '.images.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='Image is already running'):
            launcher.available_processors(database)
