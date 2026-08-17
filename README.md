# wechat-diary · 微信随手记 (Python 常驻版)

> ## 📦 本项目已归档 (2026-08-16), 请使用 Obsidian 插件版
>
> **👉 [obsidian-wechat-diary](https://github.com/ArtemisLin/obsidian-wechat-diary)** —— 在 Obsidian 第三方插件里搜 **WeChat Diary** 即可安装。
>
> 插件版功能更全 (支持图片、卸载重装自愈), 且**不需要"用" Obsidian**: 装上只是为了给它一个文件夹,
> 记下来的东西是纯 markdown, 拿任何编辑器都能开。装一个 Obsidian 比跑本项目的免签名 exe 更省事。
>
> 本仓库保留作为历史与黑客松提交物。最后一次代码更新 (v2.1.0) 已与插件版 0.3.0 的产品形态对齐,
> 但**未继续修复**已知协议偏差 (见 docs/HANDOFF.md §0), 也不再打包发布。
> 只读 MCP server (`src/mcp_server.py`) 读的是纯 md 文件夹, 与本程序进程无关, 对插件版写出的库同样可用。

**对着微信说话, 内容自动落进你自己电脑的 markdown 库。**

日记、备忘录、灵感、给爸妈记的病历——发出去, 就记下了。数据永远在你手上,
用什么 Agent (Claude Code / Codex / ...) 管理这个库是你的自由 —— 本项目只做管道。

> 有两种形态, 写出的文件遵循同一份 [数据契约](docs/data-contract.md), 可随时互迁:
> - **本项目 (Python 常驻脚本)**: 不需要 Obsidian, 任何电脑/NAS 挂着就收, 带定时提醒
> - **[Obsidian 插件版](https://github.com/ArtemisLin/obsidian-wechat-diary)**: 装进 Obsidian, 支持图片, 商城可搜 WeChat Diary
>
> 两者抢同一个微信 bot, **同一时间只能跑一个**。

- **发什么记什么**: 不用任何开场白, 发出去就记下了; 微信是最高频的输入入口, 推荐配合语音输入法说话即打字
- **数据主权**: 纯 markdown 落在本机 `DIARY_DIR`, 写入格式见 [docs/data-contract.md](docs/data-contract.md)
- **纯机械, 无 AI**: 原文直存一个字不改, 不发任何 LLM 请求, 行为完全可预测
- **可靠 routine**: 每晚 22:00 / 23:00 未写提醒 + 错过补偿 + 崩溃自动重启

## 工作流

```
[微信] ─文字/语音→ [iLink] ←长轮询─ [你电脑上的 wechat-diary]
                                        │
                                        ├─ 原文直存 (不经过任何 AI)
                                        ├─ 追加到 DIARY_DIR/YYYY/YYYY-MM-DD.md
                                        └─ 22:00/23:00 未写则微信提醒
                                                │
                                 DIARY_DIR 放同步盘 → 手机可看 + 天然备份
                                 你的 Agent 直接读写这个库 → 回顾/检索随你做
```

## 1 分钟上手 (推荐: 免安装)

从 [Releases](../../releases/latest) 下载对应平台的单文件版, 免解压免安装:

- Windows: `wechat-diary-windows.exe` (首次运行 SmartScreen 会警告 —— exe 未做
  代码签名, 点「更多信息 → 仍要运行」)
- macOS: `wechat-diary-macos` (首次运行需在「系统设置 → 隐私与安全性」允许)

双击后浏览器自动打开本地向导 (只监听 127.0.0.1): **扫码绑定微信 → 点选日记
文件夹 → 启动**, 三步完成。不需要装 Python、不需要编辑配置文件、不需要任何
AI key。之后在微信里给 bot 随便发点什么, 就记下了。

## 5 分钟源码部署

**图形化方式**: 装好依赖后运行 `python src/webui.py`, 浏览器会自动打开
本地页面 (只监听 127.0.0.1) —— 扫码绑定微信 → 点选日记文件夹 → 启动, 三步完成,
不用手工编辑 .env。命令行方式如下, 两者等价:

1. clone 本仓库, 安装依赖:

```bash
python -m pip install -r requirements.txt
```

2. 复制 `.env.example` 为 `.env`, 只需填 2 项: `USER_ID`(第 3 步获得) 和 `DIARY_DIR`
3. 扫码登录:

```bash
cd src
python ilink.py login
```

扫码确认后会打印 `ilink_user_id`, 粘到 `.env` 的 `USER_ID`。

4. 双击根目录 `start.bat` (或 `cd src && python main.py`), 看到 `=== wechat-diary 已启动 ===` 即可
5. 在微信里给 bot 随便说句话, 去 `DIARY_DIR` 看今天的文件

`start.bat` 会自动做三件事: 找到可用的 Python、session 过期时自动要求重新扫码、
崩溃后自动重启 (最多 3 次)。

## 诚实的限制 (先读再用)

- **电脑关机, 管道即停。** 本项目跑在你自己电脑上 —— 这是数据主权的代价
- **提醒是"尽力可靠"**: iLink 限制 bot 超过约 20 小时无互动就不能主动发消息
  (平台反骚扰规则, 无法绕开); 电脑睡眠时提醒也发不出。程序做了启动补偿兜底
  (错过提醒且当天未写, 启动时补发一次)
- **离线期间的消息**: 重启后按 iLink cursor 补拉 —— **24 小时内实测可补收**,
  更长时间未测; 检测到离线超过 24 小时, 会在你下一条消息的回复里
  附一次性提示, 提醒翻聊天记录补发
- **图片暂不支持** (bot 会明确告诉你这条没记上); 要收图请用 Obsidian 插件版

## 微信端用法

| 你发 | 效果 |
|------|------|
| (任何文字/语音) | 追加到今天的日记, 语音消息带 🎤 标记——**不用任何开场白** |
| 撤回 | 删掉刚记的最后一条 (回执会显示撤掉了什么) |
| 结束 | 给今天写个收尾标记 (可选仪式; 不发也没关系, 跨天自动收尾) |
| 在吗 / 你好 / 测试 | 探活: 回你"在的, 今天已记 N 段", **不会**被记进笔记 |
| 帮助 | 查看命令 |
| 叫我XX | 设置/修改你的称呼 |

**熬夜不怕跨天**: 凌晨 4 点前记的都算前一天 (`.env` 的 `DAY_START_HOUR` 可改)。

## 数据契约

写入格式是本项目对"任何管理这个库的 Agent"的接口承诺, 完整规范见
[docs/data-contract.md](docs/data-contract.md)。要点:

- 按年目录: `DIARY_DIR/YYYY/YYYY-MM-DD.md`, 文件名 = 北京时间**逻辑日** (凌晨 4 点前算前一天, 契约 v1.2)
- 新文件带 YAML frontmatter (`date` / `weekday` / `source`)
- 只追加, 永不改写历史段落; 原子写入防崩溃丢数据

从 v1 (平铺目录) 升级? 跑 `py scripts/migrate_v2.py` 干跑确认后加 `--apply`,
执行前会自动备份到 `DIARY_DIR/_backup_v1/`。

## vault 管理建议 (非约束)

- 把 `DIARY_DIR` 放在 OneDrive / 坚果云等同步盘目录里: 手机可看 + 天然备份
- 用 Obsidian 的话, 开 Daily Notes 插件, 日期格式设为 `YYYY/YYYY-MM-DD`
- 回顾 / 检索 / 周报交给你自己的 Agent 在库上做, 本项目不做也不干涉

## MCP 接口 (只读)

"用什么 Agent 管理这个库是你的自由"——`src/mcp_server.py` 是这句话的工程兑现:
一个零依赖的只读 MCP server, 任何支持 MCP 的客户端 (Claude Code / Codex / ...)
接上即可读日记, 不必自己解析数据契约。

```bash
# Claude Code 一行接入
claude mcp add wechat-diary -- python /绝对路径/wechat-diary/src/mcp_server.py
```

三个工具: `diary_read(date)` 读某天原文 / `diary_search(query, ...)` 全库检索 /
`diary_recent(n)` 近况概览。`DIARY_DIR` 读 `.env`, 也可用环境变量覆盖
(如接演示库: `DIARY_DIR=docs/demo-vault`)。

**只读是硬约束**: 该文件不 import 任何写入模块, 任何 MCP 客户端都无法通过
本接口写入或修改日记——本项目自身的写入永远只有微信管道一条路。(你的 Agent
当然仍可直接编辑 vault 里的文件, 那是你的库、你的自由。)

## 网络兼容

- **iLink API 强制直连**: `ilinkai.weixin.qq.com` 走 Clash 会出现 TLS 中间层延迟、
  QR 状态轮询超时等问题。代码通过清空 proxy 环境变量 + `no_proxy=*` +
  `ProxyHandler({})` 三重保险强制绕过, **没有开关可调**
- 登录时若微信侧已确认、但登录后的短探活遇到网络抖动, 程序会先保存 session,
  不会把这类 `network` 误判成登录失败
- 排查收发消息问题看 `data/logs/ilink.log`

## 运行测试

```bash
python -m pytest tests/ -v
```

## 关键设计

- **时区与逻辑日**: 部署机可能不在北京时区, 所有日期/时间强制走 `config.now_bj()`,
  日记文件名走 `logical_today_str()` (凌晨 4 点边界), 禁用裸 `datetime.now()`
- **只追加不重写**: 每条消息只 append, 旧段落永远不改
- **原子写入**: 所有写文件先写 `.tmp` 再 `os.replace()`, 防崩溃丢数据
- **失败响亮**: 写入失败回执以「⚠️ 这条没记上!」开头, 绝不伪装成功
- **单用户隔离**: 每个部署 = 一个用户, 其他人给 bot 发消息会被拒绝

## 目录结构

```
wechat-diary/
├── src/
│   ├── config.py          # env + 时区工具
│   ├── paths.py           # data/ 路径集中管理
│   ├── logger.py          # RotatingFileHandler 封装
│   ├── users.py           # 单用户实现
│   ├── intents.py         # 短消息意图识别
│   ├── names.py           # 取名回答的名字提取 (规则引擎)
│   ├── session_state.py   # 逻辑日翻页检测 (跨天自动封存)
│   ├── chat_handler.py    # LLM 闲聊 (v0.3 起无调用点, 代码保留)
│   ├── diary_writer.py    # 原文直存写 md (润色代码保留未启用)
│   ├── ilink.py           # 精简 iLink 客户端
│   ├── scheduler.py       # 提醒 + 启动补偿
│   ├── welcome.py         # 全部文案
│   ├── user_profile.py    # 用户名字 + 状态机持久化
│   ├── mcp_server.py      # 只读 MCP server (零依赖)
│   ├── envfile.py         # .env 原子更新 (webui 用)
│   ├── webui.py           # 本地 Web UI 入口 (扫码/选文件夹/启停, 零依赖)
│   ├── web/index.html     # Web UI 前端 (单文件, 无外部资源)
│   └── main.py            # 命令行入口
├── scripts/migrate_v2.py  # v1 → v2 存量迁移
├── docs/data-contract.md  # 数据契约 (对 Agent 的接口承诺)
├── docs/demo-vault/       # 演示日记库 (合成数据, 供体验与评测)
├── tests/                 # pytest 单测
├── start.bat              # 双击启动 (Windows)
├── data/                  # 运行时生成 (勿入 git)
└── .env                   # 密钥 (自建, 勿入 git)
```

## 明确不做

- 回顾 / 检索 / 周报 / 情绪分析 —— 交给你自己的 Agent 在 vault 上做
- 任何云同步 —— 借力现有同步盘
- 云托管 / 多用户 / 计费 —— 自部署形态下不存在
- 图片 / 视频附件

## 许可

[MIT](LICENSE)
