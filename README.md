# wechat-diary

**"微信 → 你自己的 Obsidian vault" 的开源个人日记管道。**

对着微信说话, 日记自动落到你自己电脑的 markdown 库里。数据永远在你手上,
用什么 Agent (Claude Code / Codex / ...) 管理这个库是你的自由 —— 本项目只做管道。

- **输入零摩擦**: 微信是最高频的输入入口; 推荐配合语音输入法 (如豆包) 说话即打字
- **数据主权**: 纯 markdown 落在本机 `DIARY_DIR`, 写入格式见 [docs/data-contract.md](docs/data-contract.md)
- **零 key 可用**: 不配任何 AI key 也是完整产品; key 只是可选增强 (润色 + 闲聊)
- **可靠 routine**: 每晚 22:00 / 23:00 未写提醒 + 错过补偿 + 崩溃自动重启

## 工作流

```
[微信] ─文字/语音→ [iLink] ←长轮询─ [你电脑上的 wechat-diary]
                                        │
                                        ├─ (可选) LLM 轻度润色
                                        ├─ 追加到 DIARY_DIR/YYYY/YYYY-MM-DD.md
                                        └─ 22:00/23:00 未写则微信提醒
                                                │
                                 DIARY_DIR 放同步盘 → 手机可看 + 天然备份
                                 你的 Agent 直接读写这个库 → 回顾/检索随你做
```

## 5 分钟部署

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
5. 在微信里给 bot 发「开始记日记」, 说话, 去 `DIARY_DIR` 看今天的文件

想要 AI 润色和闲聊? 在 `.env` 填上 `AI_API_KEY` (DeepSeek) 即可, 不填也完整可用。

`start.bat` 会自动做三件事: 找到可用的 Python、session 过期时自动要求重新扫码、
崩溃后自动重启 (最多 3 次)。

## 诚实的限制 (先读再用)

- **电脑关机, 管道即停。** 本项目跑在你自己电脑上 —— 这是数据主权的代价
- **提醒是"尽力可靠"**: iLink 限制 bot 超过约 20 小时无互动就不能主动发消息
  (平台反骚扰规则, 无法绕开); 电脑睡眠时提醒也发不出。程序做了启动补偿兜底
  (错过提醒且当天未写, 启动时补发一次)
- **离线期间的消息**: 重启后按 iLink cursor 补拉 —— 短时离线已实测可补收,
  长时间离线的缓冲窗口未知; 检测到离线超过 12 小时, 会在你下一条消息的回复里
  附一次性提示, 提醒翻聊天记录补发

## 微信端用法

| 你发 | 效果 |
|------|------|
| 开始记日记 / 记日记 / 开始 | 进入记录模式, 之后说什么都记 |
| (记录模式下说话) | 追加到今天的日记, 语音消息带 🎤 标记 |
| 撤回 | 删掉刚才记的最后一段 |
| 结束 | 收尾归档今天 + 退出记录模式 |
| 帮助 | 查看命令 |

不在记录模式时是闲聊模式 (配了 key 走 LLM, 没配是固定文案), 说的话**不会**被记录 ——
避免随口一句话被误记进日记。跨天自动回到闲聊模式。

## 数据契约

写入格式是本项目对"任何管理这个库的 Agent"的接口承诺, 完整规范见
[docs/data-contract.md](docs/data-contract.md)。要点:

- 按年目录: `DIARY_DIR/YYYY/YYYY-MM-DD.md`, 文件名 = 北京时间日期
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
- **AI API 可选代理**: DeepSeek 默认 auto (先直连, 失败回落本地代理
  127.0.0.1:7890/7897/7891 自动探测), 也可在 `.env` 用 `AI_PROXY_MODE` 强制
  direct / proxy
- 登录时若微信侧已确认、但登录后的短探活遇到网络抖动, 程序会先保存 session,
  不会把这类 `network` 误判成登录失败
- 排查收发消息问题看 `data/logs/ilink.log`

## 运行测试

```bash
python -m pytest tests/ -v
```

## 关键设计

- **时区**: 部署机可能不在北京时区, 所有日期/时间强制走 `config.now_bj()` /
  `today_str()`, 禁用裸 `datetime.now()`; APScheduler 也固定 `Asia/Shanghai`
- **只追加不重写**: AI 只润色本次片段再 append, 旧段落永远不改, 防 LLM 误删
- **原子写入**: 所有写文件先写 `.tmp` 再 `os.replace()`, 防崩溃丢数据
- **AI 失败回落**: LLM 不可用时原文照存, 回复里附友好提示, 用户的话永不丢失
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
│   ├── session_state.py   # chat/diary 双模式状态机 + 跨天 reset
│   ├── chat_handler.py    # chat 模式 LLM 闲聊 (零 key 时固定文案)
│   ├── diary_writer.py    # (可选)润色 + 写 md
│   ├── ilink.py           # 精简 iLink 客户端
│   ├── scheduler.py       # 提醒 + 启动补偿
│   ├── welcome.py         # 全部文案
│   ├── user_profile.py    # 用户名字 + 状态机持久化
│   ├── mcp_server.py      # 只读 MCP server (零依赖)
│   └── main.py            # 入口
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
