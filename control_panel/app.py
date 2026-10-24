"""A visible, manual-only desktop panel. Opening it starts no service."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from .backend import AstrBotAPI, PanelError, Paths, Services
from .display import configure_window, enable_high_dpi, pixels


class ControlPanel:
    def __init__(self, root: tk.Tk, paths: Paths):
        self.root, self.paths = root, paths
        self.services = Services(paths)
        self.api = AstrBotAPI(paths.dashboard_url)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nanami-control")
        self.busy = False
        self.closing = False
        self.refresh_timer = None
        self.states = {}
        self.plugin_data = {}
        self.root.title("Nanami 服务控制台 · 手动启停")
        self.display_scale = configure_window(root)
        self.root.configure(bg="#eef2f7")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.configure_styles()
        self.build()
        self.schedule_refresh(100)

    def px(self, value):
        return pixels(value, self.display_scale)

    def configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background="#eef2f7")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="#eef2f7", foreground="#1e293b")
        style.configure("Card.TLabel", background="white", foreground="#1e293b")
        style.configure("Muted.TLabel", background="#eef2f7", foreground="#64748b")
        style.configure(
            "Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"), foreground="#0f172a"
        )
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure(
            "TButton", padding=self.px((12, 7)), background="#e2e8f0", foreground="#0f172a"
        )
        style.configure("Primary.TButton", background="#2563eb", foreground="white")
        style.map("Primary.TButton", background=[("active", "#1d4ed8"), ("disabled", "#cbd5e1")])
        style.configure("Danger.TButton", background="#fee2e2", foreground="#991b1b")
        style.configure(
            "Treeview", rowheight=self.px(30), background="white", fieldbackground="white"
        )
        style.configure("TNotebook.Tab", padding=self.px((6, 3)))
        style.configure(
            "Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), background="#e2e8f0"
        )

    def build(self):
        outer = ttk.Frame(self.root, padding=self.px(16))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Nanami 控制台", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="仅本机  ·  手动启动  ·  无开机自启", foreground="#1d4ed8").pack(
            side="right"
        )
        ttk.Label(
            outer,
            text="打开控制台不启动任何服务。关闭控制台时，会停止由它启动的服务。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=self.px((5, 10)))

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=self.px((0, 10)))
        self.action_buttons = []
        self.button(bar, "启动全部服务", self.start_all, "Primary.TButton").pack(side="left")
        self.button(bar, "全部停止", self.stop_all, "Danger.TButton").pack(
            side="left", padx=self.px(8)
        )
        ttk.Button(
            bar, text="打开 AstrBot 网页", command=lambda: webbrowser.open(self.paths.dashboard_url)
        ).pack(side="right")
        ttk.Button(bar, text="QQ 扫码登录", command=self.show_qr).pack(
            side="right", padx=self.px(8)
        )
        self.status_labels = {}
        cards = ttk.Frame(outer)
        cards.pack(fill="x")
        descriptions = {
            "astrbot": ("AstrBot", "管理面板、模型与插件；启动后机器人回复保持暂停"),
            "napcat": ("NapCat / QQ", "负责 QQ 登录；进程运行不代表已扫码登录"),
            "voice": ("GPT-SoVITS 语音", "本地音色合成；仅需要语音回复时运行"),
        }
        for key, (title, description) in descriptions.items():
            card = ttk.Frame(cards, style="Card.TFrame", padding=self.px((14, 5)))
            card.pack(fill="x", pady=self.px(3))
            card.columnconfigure(1, weight=1)
            ttk.Label(
                card,
                text=title,
                style="Card.TLabel",
                font=("Microsoft YaHei UI", 11, "bold"),
                width=19,
            ).grid(row=0, column=0, sticky="w")
            status = ttk.Label(card, text="检查中…", style="Card.TLabel", foreground="#64748b")
            status.grid(row=0, column=1, sticky="w")
            self.status_labels[key] = status
            self.button(card, "启动", lambda item=key: self.start_service(item)).grid(
                row=0, column=2, padx=self.px(5)
            )
            self.button(card, "停止", lambda item=key: self.stop_service(item)).grid(
                row=0, column=3
            )
            ttk.Label(card, text=description, style="Card.TLabel", foreground="#64748b").grid(
                row=1, column=0, columnspan=4, sticky="w", pady=self.px((3, 0))
            )

        auth = ttk.Frame(outer)
        auth.pack(fill="x", pady=self.px((13, 8)))
        ttk.Label(auth, text="管理机器人与插件", style="Sub.TLabel").pack(side="left")
        self.auth_status = ttk.Label(auth, text="先手动启动 AstrBot，再登录", style="Muted.TLabel")
        self.auth_status.pack(side="right")
        form = ttk.Frame(outer)
        form.pack(fill="x", pady=self.px((0, 9)))
        self.username = tk.StringVar(
            value=self.paths.config().get("dashboard", {}).get("username", "nanami")
        )
        self.password = tk.StringVar()
        self.code = tk.StringVar()
        for label, variable, width, secret in [
            ("账号", self.username, 15, False),
            ("密码", self.password, 22, True),
            ("验证码（可选）", self.code, 11, True),
        ]:
            ttk.Label(form, text=label).pack(side="left", padx=self.px((0, 5)))
            ttk.Entry(form, textvariable=variable, width=width, show="●" if secret else "").pack(
                side="left", padx=self.px((0, 10))
            )
        self.button(form, "登录管理", self.login, "Primary.TButton").pack(side="left")
        ttk.Label(
            outer,
            text="使用你现在的 AstrBot 面板密码。密码和登录令牌只保存在本次窗口内，不写入文件。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=self.px((0, 9)))

        # Reserve room for the log before giving the notebook the remaining space.
        log_box = ttk.Frame(outer)
        log_box.pack(side="bottom", fill="x", pady=self.px((8, 0)))
        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        bot_page = ttk.Frame(self.notebook, padding=self.px(10))
        plugin_page = ttk.Frame(self.notebook, padding=self.px(10))
        self.notebook.add(bot_page, text="机器人回复")
        self.notebook.add(plugin_page, text="插件运行")
        self.bots = self.tree(
            bot_page, ("id", "type", "status"), ("机器人", "连接类型", "回复状态")
        )
        bot_actions = ttk.Frame(bot_page)
        bot_actions.pack(side="bottom", fill="x", pady=self.px((8, 0)))
        self.button(
            bot_actions, "启用选中机器人", lambda: self.bot_action(True), "Primary.TButton"
        ).pack(side="left")
        self.button(bot_actions, "暂停选中机器人", lambda: self.bot_action(False)).pack(
            side="left", padx=self.px(8)
        )
        groups = self.paths.config().get("platform_settings", {}).get("id_whitelist", [])
        self.range_label = ttk.Label(
            bot_actions,
            text="当前范围：" + ("、".join(map(str, groups)) or "未限制，请在网页中设置"),
            style="Muted.TLabel",
        )
        self.range_label.pack(side="right")
        self.bots.pack(fill="both", expand=True)
        self.plugins = self.tree(
            plugin_page, ("title", "status", "version", "name"), ("插件", "状态", "版本", "标识")
        )
        plugin_actions = ttk.Frame(plugin_page)
        plugin_actions.pack(side="bottom", fill="x", pady=self.px((8, 0)))
        for title, action in [("启用插件", "on"), ("停用插件", "off"), ("重载插件", "reload")]:
            self.button(plugin_actions, title, lambda item=action: self.plugin_action(item)).pack(
                side="left", padx=self.px((0, 8))
            )
        ttk.Label(
            plugin_actions,
            text="内置插件受保护；功能细项可在 AstrBot 网页配置。",
            style="Muted.TLabel",
        ).pack(side="right")
        self.plugins.pack(fill="both", expand=True)
        self.bots.insert("", "end", iid="placeholder", values=("尚未连接管理", "", "未启动服务"))

        ttk.Label(log_box, text="操作记录", style="Sub.TLabel").pack(
            anchor="w", pady=self.px((0, 5))
        )
        self.log = scrolledtext.ScrolledText(
            log_box,
            height=3,
            font=("Microsoft YaHei UI", 9),
            relief="flat",
            bg="#0f172a",
            fg="#cbd5e1",
            state="disabled",
        )
        self.log.pack(fill="x")
        self.note("控制台已打开，未自动启动服务。")

    def button(self, parent, label, callback, style="TButton"):
        button = ttk.Button(parent, text=label, command=callback, style=style)
        self.action_buttons.append(button)
        return button

    def tree(self, parent, names, headings):
        tree = ttk.Treeview(parent, columns=names, show="headings", height=4, selectmode="browse")
        for name, title in zip(names, headings, strict=True):
            tree.heading(name, text=title)
            tree.column(name, width=self.px(160), minwidth=self.px(85), anchor="w")
        return tree

    def note(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self, title, function, callback=None):
        if self.busy or self.closing:
            return
        self.busy = True
        for button in self.action_buttons:
            button.state(["disabled"])
        self.note(title + "…")
        future = self.executor.submit(function)

        def finish():
            if not future.done():
                self.root.after(80, finish)
                return
            self.busy = False
            for button in self.action_buttons:
                button.state(["!disabled"])
            try:
                value = future.result()
                self.note(title + "完成。")
                if callback:
                    callback(value)
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, PanelError)
                    else "操作未完成，请检查服务路径、权限或本机日志。"
                )
                self.note(message)
                messagebox.showerror("操作未完成", message, parent=self.root)
            self.schedule_refresh(100)

        self.root.after(80, finish)

    def schedule_refresh(self, delay):
        if self.closing:
            return
        if self.refresh_timer is not None:
            self.root.after_cancel(self.refresh_timer)
        self.refresh_timer = self.root.after(delay, self.refresh)

    def refresh(self):
        self.refresh_timer = None
        if self.closing:
            return
        if self.busy:
            self.schedule_refresh(2000)
            return
        self.busy = True

        def read():
            states = {key: self.services.state(key) for key in ("astrbot", "napcat", "voice")}
            bots = plugins = None
            if self.api.authenticated:
                try:
                    bots, plugins = self.api.bots(), self.api.plugins()
                except PanelError:
                    self.api.authenticated = False
            return states, bots, plugins

        future = self.executor.submit(read)

        def finish():
            if not future.done():
                self.root.after(80, finish)
                return
            self.busy = False
            try:
                self.states, bots, plugins = future.result()
                for key, state in self.states.items():
                    color = (
                        "#15803d"
                        if state.startswith("运行中")
                        else "#b45309"
                        if state != "已停止"
                        else "#64748b"
                    )
                    self.status_labels[key].configure(text=state, foreground=color)
                self.auth_status.configure(
                    text="已登录 · 可管理机器人与插件"
                    if self.api.authenticated
                    else "尚未登录 · 服务开关仍可使用"
                )
                if bots is not None:
                    selected = self.bots.selection()
                    self.bots.delete(*self.bots.get_children())
                    for bot in bots:
                        identifier = bot["id"]
                        self.bots.insert(
                            "",
                            "end",
                            iid=identifier,
                            values=(
                                identifier,
                                bot.get("type", ""),
                                "已启用" if bot.get("enable") else "已暂停",
                            ),
                        )
                    self.restore_selection(self.bots, selected)
                if plugins is not None:
                    selected = self.plugins.selection()
                    self.plugins.delete(*self.plugins.get_children())
                    self.plugin_data = {p["name"]: p for p in plugins}
                    for plugin in plugins:
                        status = "运行中" if plugin.get("activated") else "已停用"
                        if plugin.get("reserved"):
                            status += " · 内置"
                        self.plugins.insert(
                            "",
                            "end",
                            iid=plugin["name"],
                            values=(
                                plugin.get("display_name") or plugin["name"],
                                status,
                                plugin.get("version", ""),
                                plugin["name"],
                            ),
                        )
                    self.restore_selection(self.plugins, selected)
            except Exception:
                self.auth_status.configure(text="状态读取失败，请检查运行目录。")
            if not self.closing:
                self.schedule_refresh(3000)

        self.root.after(80, finish)

    @staticmethod
    def restore_selection(tree, selection):
        if selection and tree.exists(selection[0]):
            tree.selection_set(selection[0])
        elif tree.get_children():
            tree.selection_set(tree.get_children()[0])

    def start_service(self, key):
        self.run("启动" + self.paths.service(key).title, lambda: self.services.start(key))

    def confirm_external(self, keys) -> bool | None:
        external = [
            self.paths.service(key).title for key in keys if self.services.external_processes(key)
        ]
        if not external:
            return False
        if messagebox.askyesno(
            "停止外部启动的服务",
            "以下服务不是本控制台启动的："
            + "、".join(external)
            + "。\n是否按安装路径停止它们及其子进程？不会结束其他同名程序。",
            parent=self.root,
        ):
            return True
        return None

    def stop_service(self, key):
        external = self.confirm_external([key])
        if external is not None:
            self.run(
                "停止" + self.paths.service(key).title, lambda: self.services.stop(key, external)
            )

    def start_all(self):
        def start():
            started = []
            try:
                for key in ("voice", "astrbot", "napcat"):
                    if self.services.state(key) == "已停止":
                        self.services.start(key)
                        started.append(key)
            except Exception:
                for key in reversed(started):
                    self.services.stop(key)
                raise

        self.run("启动尚未运行的服务（新启动的 AstrBot 默认暂停回复）", start)

    def stop_all(self):
        external = self.confirm_external(["astrbot", "voice", "napcat"])
        if external is not None:
            self.run("停止全部服务", lambda: self.services.stop_all(external))

    def login(self):
        username, password, code = (
            self.username.get().strip(),
            self.password.get(),
            self.code.get().strip(),
        )
        if not username or not password:
            messagebox.showinfo(
                "需要登录信息", "请输入当前 AstrBot 管理面板账号和密码。", parent=self.root
            )
            return
        self.password.set("")
        self.code.set("")
        self.run("登录本机管理接口", lambda: self.api.login(username, password, code))

    def bot_action(self, enabled):
        if not self.api.authenticated:
            messagebox.showinfo(
                "请先登录", "手动启动 AstrBot 后，使用上方表单登录。", parent=self.root
            )
            return
        selected = self.bots.selection()
        if selected:
            identifier = selected[0]
            self.run(
                "启用机器人回复" if enabled else "暂停机器人回复",
                lambda: self.api.set_bot(identifier, enabled),
            )

    def plugin_action(self, action):
        if not self.api.authenticated:
            messagebox.showinfo(
                "请先登录", "手动启动 AstrBot 后，使用上方表单登录。", parent=self.root
            )
            return
        selected = self.plugins.selection()
        if not selected:
            return
        name = selected[0]
        if self.plugin_data.get(name, {}).get("reserved"):
            messagebox.showinfo(
                "内置插件",
                "为保留基本管理能力，此控制台不操作 AstrBot 内置插件。",
                parent=self.root,
            )
            return
        self.run(
            {"on": "启用插件", "off": "停用插件", "reload": "重载插件"}[action],
            lambda: self.api.plugin_action(name, action),
        )

    def show_qr(self):
        path = self.paths.qr_path()
        if not path or self.services.state("napcat") == "已停止":
            messagebox.showinfo(
                "QQ 登录", "请先手动启动 NapCat。需要登录时，它会生成二维码。", parent=self.root
            )
            return
        window = tk.Toplevel(self.root)
        window.title("QQ 扫码登录")
        window.resizable(False, False)
        label = ttk.Label(window)
        label.pack(padx=self.px(24), pady=self.px(16))
        text = ttk.Label(window, text="使用机器人对应的手机 QQ 扫码，并在手机确认登录。")
        text.pack(padx=self.px(16), pady=self.px(5))

        def update():
            image_path = self.paths.qr_path()
            if image_path:
                try:
                    image = tk.PhotoImage(file=str(image_path)).zoom(2, 2)
                    label.configure(image=image)
                    label.image = image
                except tk.TclError:
                    text.configure(text="二维码暂不可用，请稍后刷新。")

        ttk.Button(window, text="刷新显示最新二维码", command=update).pack(pady=self.px((6, 16)))
        update()

    def close(self):
        if self.closing:
            return
        external = self.confirm_external(["astrbot", "voice", "napcat"])
        if external is None:
            external = False  # Declining only preserves explicitly external processes.
        self.closing = True
        for button in self.action_buttons:
            button.state(["disabled"])
        self.note("正在退出并停止本面板启动的服务…")

        def cleanup():
            try:
                self.services.stop_all(external)
            finally:
                self.api.close()

        future = self.executor.submit(cleanup)

        def finish():
            if not future.done():
                self.root.after(100, finish)
                return
            try:
                future.result()
            except Exception:
                messagebox.showwarning(
                    "退出提示",
                    "部分外部服务未能停止，请在原启动窗口检查。本面板管理的进程组会随窗口退出而关闭。",
                    parent=self.root,
                )
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()

        self.root.after(100, finish)


def main(repo: Path):
    import win32api
    import win32event
    import winerror

    enable_high_dpi()
    mutex = win32event.CreateMutex(None, False, "Local\\NanamiManualControlPanel")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("控制台已打开", "请使用已打开的 Nanami 控制台，不会重复启动。")
        root.destroy()
        mutex.Close()
        return
    root = tk.Tk()
    try:
        ControlPanel(root, Paths(repo))
        root.mainloop()
    except Exception:
        messagebox.showerror(
            "控制台无法打开", "请检查相邻 AstrBot 环境和配置是否完整；没有自动启动任何服务。"
        )
    finally:
        mutex.Close()
