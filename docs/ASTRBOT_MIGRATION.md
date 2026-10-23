# AstrBot 迁移指南

## 架构

```text
QQ ↔ NapCat ↔ AstrBot（OneBot v11）↔ DeepSeek / GPT-SoVITS
                 └─ Nanami 插件：存档、图片对称、点歌、QQ 互动

Q群bot/
├─ nanami_bot/                 # 本 Git 仓库，只存源码与配置模板
├─ AstrBot/                    # 独立运行目录，不提交到本仓库
│  ├─ .venv/                   # 独立 Python 环境
│  ├─ .env                     # 本机模型密钥
│  ├─ local-access.txt         # 本机面板登录信息，严禁上传
│  └─ data/                    # 配置、人格、会话、插件与存档
├─ NapCat.44498.Shell/         # 保留原 QQ 登录环境
└─ GPT-sovits/                # 保留语音服务及音色模型
```

迁移基线：**AstrBot 4.29.1、Python 3.12+**。没有把 AstrBot 本体或第三方 NoneBot 插件源码复制到本仓库；`requirements.txt` 是自定义插件依赖，`pyproject.toml` 中的 NoneBot 依赖仅供回退。

## Windows 安装与切换

已有旧项目 `.env`、`.env.prod`、人格文件和有效参考音频时，在仓库运行：

```powershell
.\setup_astrbot.ps1
```

脚本将官方 AstrBot 安装到相邻的 `AstrBot/.venv`，迁移原 DeepSeek 密钥、管理员、人设和 GPT-SoVITS 参考音色，并**复制**旧存档。原 `.env`、存档、QQ 登录和模型文件保留。不要把运行目录放进本仓库。

启动 `start.bat`，访问 **http://127.0.0.1:6185**。用户名和随机强密码见 `AstrBot/local-access.txt`。管理面板和 OneBot 均只监听 `127.0.0.1`。

确认配置和测试后，切换已有 NapCat 连接（先自动备份）：

```powershell
.\setup_astrbot.ps1 -ActivateNapCat
```

仅修改原地址 `ws://127.0.0.1:8080/onebot/v11/ws` 的已启用连接，改为 **`ws://127.0.0.1:8080/ws`**，并设置与 AstrBot 一致的随机令牌。重启 NapCat 生效；不需要重新创建 QQ 号或改用 SnowLuma。

之后按原方式启动 GPT-SoVITS 和 NapCat，再运行 `start.bat`。不要同时运行旧 NoneBot 和新 AstrBot，两者默认占用同一个 8080 端口。

已存在的运行配置不会被重复迁移覆盖；再次执行安装脚本仅同步插件，面板改动会保留。自定义目录可用 `-Runtime`，启动时将 `NANAMI_ASTRBOT_ROOT` 设置为同一路径。

## 面板管理

- **模型**：DeepSeek 对话模型、GPT-SoVITS 本地语音；密钥初始使用 `$DEEPSEEK_API_KEY` 引用，只在本机 `.env` 保存真实值。
- **人格**：`nanami`，从原语音人设导入，可在面板编辑；初始工具和技能列表为空。
- **配置文件**：保留按群成员隔离、@触发及语音回复；历史改由 AstrBot 持久化。主动回复默认关闭。
- **插件 → 七海千秋**：存档、互动、图片对称、点歌及直接朗读开关；语音字数、等待时限和互动冷却。
- **日志**：检查加载与连接情况。请勿公开分享含私人信息的完整调试日志。

模型切换、人格和 `/reset` 由 AstrBot 提供；本插件不再单独维护模型请求和临时聊天历史。

## 功能命令

| 功能 | 用法 |
|---|---|
| AI 聊天 | 群内 @机器人；私聊直接发送 |
| 直接朗读 | `tts 文字`，使用当前会话的 TTS |
| 存档 | 回复消息发送 `存档 [标签...]` 或 `/savechat [标签...]` |
| 列表、搜索 | `listchat [页码]`、`findchat 关键词` |
| 抽取 | `rollchat [标签]`，转发失败时降级文字 |
| 管理 | `tagchat 编号 标签...`、`delchat 编号`，仅管理员 |
| 清空 | `clearchat 确认`，仅管理员，不带确认不删除 |
| 存档帮助 | `archhelp` |
| QQ 互动 | `zanwo`、`chuowo`，仅作用于发送者，带冷却 |
| 贴表情 | `emoji ❤`，可引用目标消息，支持 QQ 表情 |
| 图片对称 | `左右对称`、`上下对称`，随后上传图片，也支持指令附图 |
| 网易云点歌 | `点歌 歌名` / `网易云 歌名`，随后回复序号 |
| QQ 点歌 | `QQ点歌 歌名`，随后回复序号 |
| 帮助与测试 | `nanamihelp`、`帮助`、`功能`、`test`；原生 `/help` 保留 |

旧存档保持编号、标签、时间、原始内容兼容，复制到 `AstrBot/data/plugin_data/astrbot_plugin_nanami/chat_archive/`；原 QQ 图片链接如果已过期，迁移不会使其恢复。

点歌改为独立异步实现，不再依赖 `nonebot-plugin-multincm`；搜索、可播放性和卡片发送仍受音乐平台及 NapCat 接口限制，不绕过会员或版权限制。图片只从 QQ 媒体域名下载，并限制大小和像素，不读取群友指定的本机文件。

## 自定义开发与验证

入口 `main.py`，业务逻辑 `nanami_core.py`，面板设置 `_conf_schema.json`，元数据 `metadata.yaml`。

修改后同步，再在面板点击本插件“重载”：

```powershell
..\AstrBot\.venv\Scripts\python.exe scripts\migrate_local.py --runtime ..\AstrBot --sync-only
```

在其他 AstrBot 面板中也可直接安装此仓库插件；插件安装不会导入原电脑的密钥和私人数据。

```powershell
..\AstrBot\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio ruff python-dotenv
..\AstrBot\.venv\Scripts\python.exe -m pytest tests -q
..\AstrBot\.venv\Scripts\ruff.exe check main.py nanami_core.py scripts tests
..\AstrBot\.venv\Scripts\python.exe scripts\check_secrets.py --staged
```

测试覆盖存档兼容和并发、管理员权限、清空确认、编号不复用、图片对称与下载限制、普通聊天不触发动作、戳一戳目标与冷却、密钥隔离、重复迁移保护。

## 回退

先关闭 AstrBot，恢复备份连接，再重启 NapCat 并启动 `start-nonebot.bat`：

```powershell
..\AstrBot\.venv\Scripts\python.exe scripts\rollback_napcat.py
```

原 Python 环境必须仍有效。迁移后新增存档保留在 AstrBot 目录，回退不会自动合并到旧目录。不要删除 AstrBot 运行目录或其中的备份。

详细安全边界见 [SECURITY.md](../SECURITY.md)。本机 `.env` 与 `local-access.txt` 是私人明文文件，不能上传。

官方文档：[AstrBot](https://docs.astrbot.app/) · [插件开发](https://docs.astrbot.app/dev/star/plugin-new.html) · [NapCat](https://napneko.github.io/) · [NoneBot](https://nonebot.dev/)

移植来源为原 Nanami 自研插件。AstrBot、NapCat、GPT-SoVITS 和原第三方插件分别遵循各自许可；框架、QQ 登录文件、音色模型均不属于本插件源码。
