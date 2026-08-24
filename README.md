# nanami_bot

基于 [NoneBot2](https://nonebot.dev/) + OneBot V11 协议的 QQ 群机器人，角色为「七海千秋」。

## 架构

```
┌────────────┐   OneBot V11 (WebSocket反向连接)   ┌──────────────────────┐
│   QQ 客户端  │ ◄───────────────────────────────► │  NoneBot2 (nanami)   │
│ (NapCat)    │   ws://127.0.0.1:8080/onebot/v11/ws│  Python + FastAPI     │
└────────────┘                                    └──────────┬───────────┘
                                                             │
                                                ┌────────────▼───────────┐
                                                │  src/plugins/*         │
                                                │  · chat (AI聊天)        │
                                                │  · archieve (存档)      │
                                                │  · emoji / like / pic  │
                                                │  · my_help / test_conn │
                                                └────────────────────────┘
```

- **NapCat**（独立部署，不在本仓库）负责登录 QQ 并把消息桥接为 OneBot V11 协议
- **nanami_bot** 是 NoneBot2 项目，监听 `127.0.0.1:8080`，NapCat 通过反向 WebSocket 连上来
- 插件均位于 `src/plugins/`，通过 `pyproject.toml` 的 `plugin_dirs` 自动加载

## 插件功能

| 插件 | 功能 | 触发方式 |
|---|---|---|
| `chat.py` | AI 闲聊（DeepSeek），支持表情包（`[meme:描述]`）| @机器人 |
| `archieve.py` | 消息存档/列表/随机抽/搜索/清空 | `/savechat` `/listchat` `/rollchat` `/findchat` `/clearchat` |
| `emoji.py` | 给消息贴 QQ 表情/Unicode emoji | `/emoji ❤` |
| `like.py` | 点赞、戳一戳 | `zanwo` `chuowo` |
| `pic.py` | 图片左右/上下对称 | `左右对称` `上下对称` |
| `my_help.py` | 功能列表 | `/help` `/帮助` |
| `test_conn.py` | 连通性测试 | `/test` |

## 目录结构

```
nanami_bot/
├── src/
│   └── plugins/
│       ├── chat.py            # AI 聊天主插件
│       ├── character_prompt.txt  # 人设（外置，可单独编辑）
│       ├── memes/             # 表情包图片（相对路径，不入库）
│       └── ...                # 其余插件
├── data/chat_archive/         # 聊天存档（运行时生成，不入库）
├── aitalk_config/             # aitalk 插件配置目录（未启用）
├── .env.example               # 配置模板（复制为 .env 填写真实值）
├── pyproject.toml
└── start.bat                  # Windows 启动脚本（激活 venv 后 nb run）
```

## 快速开始

1. 安装依赖并创建虚拟环境：

   ```bash
   pip install -e .
   ```

2. 复制配置模板并填写真实值：

   ```bash
   copy .env.example .env
   # 编辑 .env：填写 API Key、SUPERUSERS（管理员QQ号）等
   ```

3. 部署 NapCat 并配置反向 WebSocket 指向 `ws://127.0.0.1:8080/onebot/v11/ws`

4. 启动：

   ```bash
   nb run
   ```

## 配置说明（.env）

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（`chat.py` 使用） |
| `QWEN_API_KEY` | Qwen API Key（aitalk 多模型使用） |
| `SUPERUSERS` | 机器人管理员 QQ 号列表 |
| `HOST` / `PORT` | NoneBot 监听地址，NapCat 反向 WS 连接目标 |
| `aitalk_*` | aitalk 插件配置（当前插件已移至 `src/备用插件/`，未启用） |

> ⚠️ **安全**：`.env` 含真实密钥，已被 `.gitignore` 排除，切勿提交。
