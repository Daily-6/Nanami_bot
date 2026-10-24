"""Fixed service commands, scoped process ownership, and loopback-only AstrBot API."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import psutil


class PanelError(RuntimeError):
    """An intentionally credential-free message suitable for the desktop UI."""


@dataclass(frozen=True)
class ServiceSpec:
    key: str
    title: str
    command: tuple[str, ...]
    cwd: Path
    port: int | None


class Paths:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.workspace = self.repo.parent
        self.runtime = Path(
            os.environ.get("NANAMI_ASTRBOT_ROOT", self.workspace / "AstrBot")
        ).resolve()
        self.config_path = self.runtime / "data/cmd_config.json"
        self.logs = self.workspace / "work/control-panel"
        self.napcat = self.workspace / "NapCat.44498.Shell"
        self.voice = self.workspace / "GPT-sovits/GPT-SoVITS-v2pro-20250604-nvidia50"

    def config(self) -> dict:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise PanelError("找不到有效的 AstrBot 配置，请检查相邻的 AstrBot 目录。") from None

    @property
    def dashboard_port(self) -> int:
        port = int(self.config().get("dashboard", {}).get("port", 6185))
        if not 1 <= port <= 65535:
            raise PanelError("AstrBot 面板端口配置无效。")
        return port

    @property
    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.dashboard_port}"

    def service(self, key: str) -> ServiceSpec:
        if key == "astrbot":
            return ServiceSpec(
                key,
                "AstrBot",
                (
                    str(self.runtime / ".venv/Scripts/python.exe"),
                    str(self.repo / "scripts/run_astrbot.py"),
                ),
                self.repo,
                self.dashboard_port,
            )
        if key == "voice":
            return ServiceSpec(
                key,
                "语音服务",
                (
                    str(self.voice / "runtime/python.exe"),
                    "api_v2.py",
                    "-a",
                    "127.0.0.1",
                    "-p",
                    "9880",
                    "-c",
                    "GPT_SoVITS/configs/tts_infer.yaml",
                ),
                self.voice,
                9880,
            )
        if key == "napcat":
            # Derive the account from the user's existing launcher, never log it.
            import re

            launcher = self.napcat / "napcat.quick.bat"
            text = launcher.read_text(encoding="utf-8-sig", errors="replace")
            match = re.search(r"NapCatWinBootMain\.exe[\"\s]+([0-9]{5,20})", text, re.I)
            if not match:
                raise PanelError("NapCat 快速启动脚本中没有找到机器人账号，请检查原启动器。")
            return ServiceSpec(
                key,
                "NapCat / QQ",
                (str(self.napcat / "NapCatWinBootMain.exe"), match.group(1)),
                self.napcat,
                None,
            )
        raise PanelError("未知服务。")

    def pause_bots_offline(self) -> None:
        """A service start never implicitly enables QQ responses."""
        if listening(self.dashboard_port):
            raise PanelError("AstrBot 正在运行，不能离线修改。请在机器人列表中暂停回复。")
        config = self.config()
        for bot in config.get("platform", []):
            bot["enable"] = False
        temporary = self.config_path.with_name(".manual-control-config.tmp")
        try:
            temporary.write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8-sig"
            )
            os.replace(temporary, self.config_path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise PanelError("无法保存启动状态，请检查运行目录写入权限。") from None

    def qr_path(self) -> Path | None:
        files = list(self.napcat.glob("versions/*/resources/app/napcat/cache/qrcode.png"))
        return max(files, key=lambda path: path.stat().st_mtime) if files else None


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.15)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class OwnedJob:
    """Windows kills this job's descendants if its last controller handle closes."""

    def __init__(self, command: list[str], cwd: Path, log: Path, env: dict[str, str] | None = None):
        if os.name != "nt":
            raise PanelError("此控制台的进程保护需要 Windows。")
        import win32api
        import win32con
        import win32job

        self.handle = win32job.CreateJobObject(None, "Local\\NanamiService-" + uuid.uuid4().hex)
        limits = win32job.QueryInformationJobObject(
            self.handle, win32job.JobObjectExtendedLimitInformation
        )
        limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(
            self.handle, win32job.JobObjectExtendedLimitInformation, limits
        )
        log.parent.mkdir(parents=True, exist_ok=True)
        self.output = log.open("ab", buffering=0)
        self.process = None
        try:
            # The gate wrapper waits for GO before launching any child. Assignment to
            # the kill-on-close job therefore happens before the real service starts.
            wrapper = Path(__file__).with_name("service_runner.py")
            self.process = subprocess.Popen(
                [sys.executable, str(wrapper), json.dumps(command)],
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=self.output,
                stderr=self.output,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                text=True,
            )
            process_handle = win32api.OpenProcess(
                win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, self.process.pid
            )
            try:
                win32job.AssignProcessToJobObject(self.handle, process_handle)
            finally:
                win32api.CloseHandle(process_handle)
            self.process.stdin.write("GO\n")
            self.process.stdin.flush()
            self.process.stdin.close()
        except Exception:
            if self.process:
                self.process.terminate()
                self.process.wait(timeout=5)
            self.close()
            raise PanelError("无法创建受控进程，服务未启动；请检查日志目录和本机权限。") from None

    def alive(self) -> bool:
        if self.handle is None:
            return False
        import win32job

        return (
            win32job.QueryInformationJobObject(
                self.handle, win32job.JobObjectBasicAccountingInformation
            )["ActiveProcesses"]
            > 0
        )

    def close(self) -> None:
        if getattr(self, "handle", None) is not None:
            import win32api
            import win32job

            win32job.TerminateJobObject(self.handle, 0)
            win32api.CloseHandle(self.handle)
            self.handle = None
        if getattr(self, "process", None) is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if getattr(self, "output", None):
            self.output.close()


class Services:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.jobs: dict[str, OwnedJob] = {}
        self.lock = threading.RLock()
        # Intentionally no start, resume, timer or startup-registration call.

    def external_processes(self, key: str) -> list[tuple[int, float]]:
        """Match the exact configured installation and entry point, never all Python/QQ."""
        spec = self.paths.service(key)
        expected_exe = os.path.normcase(os.path.abspath(spec.command[0]))
        managed = set()
        job = self.jobs.get(key)
        if job and job.process and job.process.poll() is None:
            try:
                parent = psutil.Process(job.process.pid)
                managed = {p.pid for p in parent.children(recursive=True)} | {parent.pid}
            except psutil.Error:
                pass
        found = []
        for process in psutil.process_iter(["pid", "exe", "cmdline", "cwd", "create_time"]):
            try:
                info = process.info
                if info["pid"] in managed:
                    continue
                exe = os.path.normcase(os.path.abspath(info["exe"] or ""))
                args = info["cmdline"] or []
                # Windows venv launchers can report the base interpreter as exe.
                launch_exe = os.path.normcase(os.path.abspath(args[0])) if args else ""
                own_install = exe == expected_exe or launch_exe == expected_exe
                if key == "astrbot":
                    own_install = own_install and any(
                        str(self.paths.repo / "scripts/run_astrbot.py").lower() == arg.lower()
                        for arg in args
                    )
                    own_install = own_install or (
                        exe
                        == os.path.normcase(str(self.paths.runtime / ".venv/Scripts/astrbot.exe"))
                        and "run" in args
                    )
                elif key == "voice":
                    own_install = (
                        own_install
                        and "api_v2.py" in args
                        and "9880" in args
                        and Path(info["cwd"] or "").resolve() == spec.cwd.resolve()
                    )
                if own_install:
                    found.append((info["pid"], info["create_time"]))
            except (psutil.Error, OSError):
                continue
        return found

    def state(self, key: str) -> str:
        with self.lock:
            job = self.jobs.get(key)
            if job and job.alive():
                spec = self.paths.service(key)
                return (
                    "运行中 · 本面板管理"
                    if not spec.port or listening(spec.port)
                    else "启动中 · 本面板管理"
                )
            if self.external_processes(key):
                return "外部启动 · 可停止"
            spec = self.paths.service(key)
            if spec.port and listening(spec.port):
                return "端口已占用 · 未接管"
            return "已停止"

    def start(self, key: str) -> None:
        with self.lock:
            if self.state(key) != "已停止":
                raise PanelError("该服务已运行或端口被占用，不会重复启动。")
            if key == "astrbot":
                self.paths.pause_bots_offline()
            spec = self.paths.service(key)
            if not Path(spec.command[0]).is_file():
                raise PanelError(f"找不到{spec.title}的启动程序，请检查安装目录。")
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "NANAMI_ASTRBOT_ROOT": str(self.paths.runtime),
                }
            )
            for name in ("TCL_LIBRARY", "TK_LIBRARY", "PYTHONHOME", "PYTHONPATH"):
                env.pop(name, None)
            previous = self.jobs.pop(key, None)
            if previous:
                previous.close()
            self.jobs[key] = OwnedJob(
                list(spec.command), spec.cwd, self.paths.logs / f"{key}.log", env
            )

    def stop(self, key: str, include_external: bool = False) -> None:
        with self.lock:
            job = self.jobs.pop(key, None)
            external = self.external_processes(key) if include_external else []
            if job is None and not external:
                return
            if job:
                job.close()
            if include_external:
                self._stop_external(key)
            if key == "astrbot" and not listening(self.paths.dashboard_port):
                self.paths.pause_bots_offline()

    def _stop_external(self, key: str) -> None:
        identities = self.external_processes(key)
        targets = {}
        for pid, created in identities:
            try:
                parent = psutil.Process(pid)
                if abs(parent.create_time() - created) > 0.01:
                    continue
                for process in [*parent.children(recursive=True), parent]:
                    targets[process.pid] = process.create_time()
            except psutil.Error:
                continue
        processes = []
        for pid, created in targets.items():
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - created) < 0.01:
                    process.terminate()
                    processes.append(process)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                raise PanelError(
                    "无法停止该外部进程，请在原启动窗口退出；不会结束其他同名程序。"
                ) from None
        _, alive = psutil.wait_procs(processes, timeout=4)
        for process in alive:
            try:
                if abs(process.create_time() - targets[process.pid]) < 0.01:
                    process.kill()
            except psutil.NoSuchProcess:
                pass

    def stop_all(self, include_external: bool = False) -> None:
        errors = []
        for key in ("napcat", "astrbot", "voice"):
            try:
                self.stop(key, include_external)
            except Exception as exc:
                errors.append(
                    str(exc) if isinstance(exc, PanelError) else "停止失败，请检查对应服务。"
                )
        if errors:
            raise PanelError("\n".join(errors))

    def has_owned(self) -> bool:
        return any(job.alive() for job in self.jobs.values())


class AstrBotAPI:
    def __init__(self, base_url: str, transport=None):
        from urllib.parse import urlsplit

        url = urlsplit(base_url)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.username
            or url.password
            or url.path not in ("", "/")
        ):
            raise PanelError("控制面板只允许连接本机 AstrBot。")
        self.client = httpx.Client(
            base_url=base_url,
            timeout=12,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )
        self.authenticated = False
        self.lock = threading.RLock()

    def close(self):
        self.authenticated = False
        self.client.cookies.clear()
        self.client.headers.pop("Authorization", None)
        self.client.close()

    def request(self, method: str, path: str, **kwargs):
        with self.lock:
            try:
                response = self.client.request(method, path, **kwargs)
            except httpx.HTTPError:
                raise PanelError("无法连接本机 AstrBot，请先手动启动 AstrBot 服务。") from None
            if response.status_code in (401, 403):
                self.authenticated = False
                raise PanelError("登录未通过或已过期，请输入当前 AstrBot 账号、密码及可选验证码。")
            try:
                body = response.json()
            except ValueError:
                raise PanelError("AstrBot 返回了无法识别的响应。") from None
            if response.is_error or body.get("status") != "ok":
                # Remote bodies can contain sensitive paths/values. Never echo them.
                raise PanelError("AstrBot 未确认操作成功，请在网页面板检查设置。")
            return body.get("data")

    def login(self, username: str, password: str, code: str = ""):
        self.authenticated = False
        self.client.headers.pop("Authorization", None)
        self.client.cookies.clear()
        data = (
            self.request(
                "POST",
                "/api/auth/login",
                json={"username": username, "password": password, "code": code},
            )
            or {}
        )
        token = data.get("token") or data.get("jwt")
        if token:
            self.client.headers["Authorization"] = "Bearer " + token
        self.authenticated = True

    def bots(self) -> list[dict]:
        return (self.request("GET", "/api/v1/bots") or {}).get("bots", [])

    def set_bot(self, bot_id: str, enabled: bool):
        self.request("PATCH", "/api/v1/bots/enabled", json={"bot_id": bot_id, "enabled": enabled})

    def plugins(self) -> list[dict]:
        data = self.request("GET", "/api/plugin/get") or []
        return data if isinstance(data, list) else data.get("plugins", [])

    def plugin_action(self, name: str, action: str):
        if action not in ("on", "off", "reload"):
            raise PanelError("未知插件操作。")
        self.request("POST", f"/api/plugin/{action}", json={"name": name})
