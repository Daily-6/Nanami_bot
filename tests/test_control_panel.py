import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil
import pytest
from nanami_plugin.control_panel.backend import (
    AstrBotAPI,
    OwnedJob,
    PanelError,
    Paths,
    Services,
    ServiceSpec,
)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    repo = tmp_path / "nanami_bot"
    repo.mkdir()
    runtime = tmp_path / "AstrBot"
    (runtime / "data").mkdir(parents=True)
    monkeypatch.delenv("NANAMI_ASTRBOT_ROOT", raising=False)
    config = {
        "dashboard": {"host": "127.0.0.1", "port": 59761},
        "platform": [{"id": "test", "enable": True}],
        "platform_settings": {"id_whitelist": ["test-group"]},
        "provider_sources": [{"key": ["test-only-model-credential"]}],
    }
    (runtime / "data/cmd_config.json").write_text(json.dumps(config), encoding="utf-8-sig")
    napcat = tmp_path / "NapCat.44498.Shell"
    napcat.mkdir()
    (napcat / "napcat.quick.bat").write_text(
        ".\\NapCatWinBootMain.exe 12345678\n", encoding="utf-8"
    )
    return Paths(repo)


def test_opening_controller_never_starts_or_changes_config(paths, monkeypatch):
    original = paths.config_path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("constructor must never create a service process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    manager = Services(paths)
    assert manager.jobs == {}
    manager.stop_all()
    assert paths.config_path.read_bytes() == original


def test_starting_service_pauses_responses_preserves_secrets(paths, monkeypatch):
    monkeypatch.setattr("nanami_plugin.control_panel.backend.listening", lambda _: False)
    paths.pause_bots_offline()
    result = paths.config()
    assert result["platform"][0]["enable"] is False
    assert result["platform_settings"]["id_whitelist"] == ["test-group"]
    assert result["provider_sources"][0]["key"] == ["test-only-model-credential"]


def test_offline_write_refuses_running_server(paths, monkeypatch):
    monkeypatch.setattr("nanami_plugin.control_panel.backend.listening", lambda _: True)
    before = paths.config_path.read_bytes()
    with pytest.raises(PanelError):
        paths.pause_bots_offline()
    assert paths.config_path.read_bytes() == before


def test_service_commands_are_fixed_and_no_shell(paths):
    assert paths.service("napcat").command[-1] == "12345678"
    assert paths.service("voice").command[1] == "api_v2.py"
    assert paths.service("astrbot").command[-1].endswith("run_astrbot.py")
    with pytest.raises(PanelError):
        paths.service("arbitrary-shell-command")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:6185",
        "http://evil.example",
        "http://127.0.0.1:6185/api",
        "http://user:password@127.0.0.1:6185",
    ],
)
def test_api_cannot_send_credentials_to_external_hosts(url):
    with pytest.raises(PanelError):
        AstrBotAPI(url)


def test_bot_and_plugin_api_controls_are_explicit_and_password_not_persisted():
    seen = []

    def handler(request):
        seen.append(
            (
                request.method,
                request.url.path,
                json.loads(request.content) if request.content else {},
            )
        )
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"status": "ok", "data": {"token": "test-session"}})
        if request.url.path == "/api/v1/bots":
            return httpx.Response(
                200, json={"status": "ok", "data": {"bots": [{"id": "test", "enable": False}]}}
            )
        if request.url.path == "/api/plugin/get":
            return httpx.Response(
                200, json={"status": "ok", "data": [{"name": "test_plugin", "activated": True}]}
            )
        return httpx.Response(200, json={"status": "ok"})

    api = AstrBotAPI("http://127.0.0.1:6185", transport=httpx.MockTransport(handler))
    assert seen == []
    api.login("test-user", "test-password")
    assert api.authenticated
    assert len(seen) == 1  # Login does not enable bots or plugins.
    assert api.bots()[0]["enable"] is False
    assert api.plugins()[0]["activated"] is True
    api.set_bot("test", True)
    api.plugin_action("test_plugin", "off")
    api.plugin_action("test_plugin", "on")
    api.plugin_action("test_plugin", "reload")
    assert seen[3][2] == {"bot_id": "test", "enabled": True}
    assert seen[-1][2] == {"name": "test_plugin"}
    assert not hasattr(api, "password")
    api.close()
    assert not api.authenticated


def test_api_errors_never_echo_remote_sensitive_payloads():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            500, json={"status": "error", "message": "private-test-credential"}
        )
    )
    api = AstrBotAPI("http://127.0.0.1:6185", transport=transport)
    with pytest.raises(PanelError) as error:
        api.bots()
    assert "private-test-credential" not in str(error.value)
    api.close()


def test_expired_session_clears_authentication():
    api = AstrBotAPI(
        "http://127.0.0.1:6185",
        transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"status": "error"})),
    )
    api.authenticated = True
    with pytest.raises(PanelError):
        api.bots()
    assert not api.authenticated
    api.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows job object ownership")
def test_owned_services_are_not_external_and_external_venv_launcher_is_recognized(
    paths, monkeypatch
):
    cwd = paths.voice
    cwd.mkdir(parents=True)
    script = cwd / "api_v2.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    spec = ServiceSpec("voice", "test", (sys.executable, "api_v2.py", "9880"), cwd, None)
    monkeypatch.setattr(paths, "service", lambda key: spec)
    manager = Services(paths)
    external = None
    try:
        manager.start("voice")
        assert manager.external_processes("voice") == []
        manager.stop("voice")
        external = subprocess.Popen(
            list(spec.command), cwd=cwd, creationflags=subprocess.CREATE_NO_WINDOW
        )
        deadline = time.monotonic() + 5
        found = []
        while not found and time.monotonic() < deadline:
            found = manager.external_processes("voice")
            time.sleep(0.05)
        assert found
        assert external.pid in {
            p.pid for pid, _ in found for p in [psutil.Process(pid), *psutil.Process(pid).parents()]
        }
        manager.stop("voice", include_external=True)
        external.wait(timeout=5)
    finally:
        manager.stop_all()
        if external and external.poll() is None:
            external.terminate()
            external.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows job object ownership")
def test_closing_job_stops_its_child_but_not_unrelated_process(tmp_path):
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "child.py"
    script.write_text(
        "import os,time\nfrom pathlib import Path\nPath('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    job = None
    try:
        job = OwnedJob([sys.executable, str(script)], tmp_path, tmp_path / "test.log")
        deadline = time.monotonic() + 10
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pidfile.exists()
        pid = int(pidfile.read_text())
        assert job.alive()
        assert psutil.pid_exists(pid)
        job.close()
        deadline = time.monotonic() + 5
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(pid)
        assert unrelated.poll() is None
    finally:
        if job:
            job.close()
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows job object ownership")
@pytest.mark.parametrize("windowless", [False, True])
def test_unexpected_controller_exit_kills_managed_job(tmp_path, windowless):
    pidfile = tmp_path / "managed.pid"
    controller = tmp_path / "controller.py"
    root = Path(__file__).resolve().parents[1]
    controller.write_text(
        "import sys,os,time\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from control_panel.backend import OwnedJob\n"
        f"job=OwnedJob([sys.executable, '-c', \"import os,time;from pathlib import Path;Path('managed.pid').write_text(str(os.getpid()));time.sleep(60)\"],Path({str(tmp_path)!r}),Path({str(tmp_path / 'abrupt.log')!r}))\n"
        "deadline=time.monotonic()+10\n"
        "while not Path('managed.pid').exists() and time.monotonic()<deadline: time.sleep(.05)\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    interpreter = Path(sys.executable).with_name("pythonw.exe") if windowless else sys.executable
    result = subprocess.run(
        [str(interpreter), str(controller)],
        cwd=tmp_path,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0
    assert pidfile.exists()
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(pid)
