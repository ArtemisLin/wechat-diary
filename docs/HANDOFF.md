# HANDOFF — 交接文档

> 写给下一个接手本项目的 AI Agent。最后更新: **2026-08-16**。
> 读完本文件, 你应该知道: 下一件事干什么、系统怎么跑起来的、对话链路长什么样、
> 哪些坑别再踩、哪些事没做完需要主动提醒用户。
>
> **⚠️ 本项目现在是 020 插件版的"影子": 产品形态/文案/规则以 020 为准, 改动先在 020 做、再回灌到这里。**
> 020 的交接文档在 `../020obs-wechatdairy/HANDOFF.md`(本地文件, 不进 git), 两份要一起读。

## 0. 现状与下一步 (2026-08-16)

**v2.1.0 (commit 4b9a657) = 与 020 插件版 0.3.0 同步的产品形态重做, 已提交本地、未 push、未打包发版。**
谷雨的意图: "两个版本——没有 Obsidian 库的也能用"。019 停运状态未变
(`~/Library/LaunchAgents/com.wechat-diary.webui.plist.disabled`、`data/ilink_state.json.disabled-20260813`
两个文件改回原名即复活), 因为它和 020 抢同一个 bot, 谷雨自己用 020。

**这轮回灌了什么** (细节见 CHANGELOG v2.1.0):
单模式发什么记什么 / 「在吗」探活不落库 / 契约 v1.2 逻辑日 (`DAY_START_HOUR`) /
AI 停用 (代码保留) / 文案审定 9 项 / 图片明确回"没记上" / 「结束」后同分钟续写另起段头。
`python3 -m pytest tests/` **287 全绿**。

**没回灌的 (诚实清单, 按重要度)**:
1. **协议 5 处偏差仍在** (`../020obs-wechatdairy/docs/protocol-notes.md` §1): 最要紧的是
   `-14` 仍按"session 过期→exit 2→start.bat 删 state 重扫码"处理——官方语义是 stale token
   **暂停 1 小时**, 而且**服务端解绑不存在、token 删了不可逆**(8/14-16 查实)。这条对
   "没有 Obsidian 的用户"是真风险: 一次 -14 就把能用的 token 删了。要复活 019 给别人用, 先修这个。
   其余: longpolling_timeout_ms 塞错地方、BASE_URL 硬编码、登录状态机、binded_redirect 语义。
2. **图片不收**: 需要 AES-ECB 解密 (Python 无内置 AES, 得加 cryptography/pycryptodome 依赖,
   PyInstaller 打包也要跟着改)。020 的实现在 main.js `downloadImage`/`sniffImageExt`, 协议在
   protocol-notes。当前 bot 会明确告诉用户"这条没记上, 请用插件版"。
3. **半绑定自愈不适用**: 019 的 token/userId 都在 `data/ilink_state.json` 一个文件里, 没有
   020 那种 secretStorage/data.json 分裂问题, 不需要移植。
4. 020 的 skipBacklog(恢复后先推游标不落笔) 也不适用——019 没有"凭据在、游标丢"的场景。

**下一步**: 谷雨拍板要不要 push + 重新打包发 Release (打包脚本 `build/`, 见 §3)。
在那之前, 建议先修上面第 1 条的 -14 处理。

## 1. 一句话与不可谈判项

wechat-diary = 微信说话 → 用户自己电脑上的 markdown 日记。管道 + 提醒, 仅此而已。

**产品哲学红线 (用户 2026-08-10 在多方案推演后明确拍板, 不要再挑战):**

1. **只做记录管道 + 未写提醒**。用户明确拒绝一切"回声/回顾/把旧日记还给用户"
   类功能 (理由: 不完善的 Agent 递不合时宜的旧文是伤害)。**不要再提议此类功能。**
2. 它不是聊天 Agent。v2.1 起连闲聊模式都没了: 发什么记什么, 「在吗」类探活回状态不落库。
   AI (润色/闲聊) 全面停用, 代码保留; 怎么把 AI 融回 Agent 是谷雨还在想的题 (020 HANDOFF #5/#7)。
   **别用 AI 判断"这条记不记"**——判错=静默丢用户的话, 记录工具第一美德是可预测。
3. 数据主权: 纯本地 markdown, 永不做云托管/SaaS/多用户。
4. 零 key 可用是底线 (现在是唯一形态), 写入失败必须响亮 (「⚠️ 这条没记上!」)。
5. 深度需求 (回顾/检索/周报) 的唯一出口 = 只读 MCP + 用户自选 Agent。
6. 命令行入口 (main.py / start.bat / ilink.py login) 永远保留, webui 是并列入口。
7. 开箱即用优先: 能少让用户配一样东西就少配一样。

## 2. 对话链路地图 (改 Agent 行为前必读)

```
微信消息
  └─ ilink.run_loop            长轮询收消息; _coalesce_items 把平台拆开的
                               同一条消息多 item 无损拼回"一次发送";
                               纯图片消息 → 回 IMAGE_UNSUPPORTED_REPLY (不静默)
       └─ main._on_message     离线>24h 时给首条回复附一次性提示
            └─ main._dispatch  ① _rollover: 逻辑日翻页→自动封存旧的一天
                               ② 首次见面: 内容优先(先记再欢迎) / 取名流程
                               ③ 跨天告知与"今天第一条"合并
                 └─ main._handle   ★ 单模式主路由
```

`_handle` 内部的判定顺序 (v2.1 单模式, 这就是全部的"智能"):

| 顺序 | 判定 | 说明 |
|---|---|---|
| 1 | 非本人消息直接拒 | 单用户产品 |
| 2 | `intents.detect_ex(text)` → (intent, suspect) | **纯规则, 无 LLM** |
| 3 | HELP → 帮助 | |
| 4 | CHAT (在吗/hello/测试…含复读折叠) → `ping_reply(今日段数)` | **不落库** |
| 5 | UNDO → 删最后一条, 回执带被删内容预览 | |
| 6 | FINALIZE → 写封存标记 (可选仪式, 不切模式); 之后继续发照记 | 收尾语分白天/晚安池 |
| 7 | START_DIARY: 短句→"现在不用了"; 长句(suspect)→整句照记+顺带告知 | 老习惯兼容 |
| 8 | 「叫我XX」→ 改名 (names.py 规则引擎) | |
| 9 | **其余一切 → 写入** | 每天第一条带完整命令提示, 之后干净 |

各模块职责:

- **[intents.py](../src/intents.py)** — 规则意图识别。`MAX_COMMAND_LEN=15`:
  只有短消息才匹配命令词; 长句仅靠 `_START_DIARY_PHRASES` 子串兜底 (→suspect)。
  normalize 剥尾部语气词和标点; `_fold_repeats` 折叠「在吗在吗」。
- **[session_state.py](../src/session_state.py)** — 只剩逻辑日翻页检测 `rollover()`,
  落盘 `data/session_state.json` (老字段 mode/chat_count_today 保留兼容, 语义忽略)。
- **[config.py](../src/config.py)** — `logical_today_str()` (凌晨 `DAY_START_HOUR` 前算前一天),
  `is_night_now()`, `weekday_for()`。**日记文件名/封存/计数一律走逻辑日, 别用 today_str()。**
- **[diary_writer.py](../src/diary_writer.py)** — 原文直存 + 原子写入 + 计数/撤回(返回被删文本)/
  封存(可指定日期)/`count_day`。`polish()`/`_call_llm` 保留未调用。
  同分钟合并前提: `_can_merge_into_last_header` (最后段头同分钟**且在封存线之后**)。
- **[chat_handler.py](../src/chat_handler.py)** — 无调用点, 代码保留。
- **[names.py](../src/names.py)** — 取名规则引擎。踩过 2 个 critical:
  「你叫我干嘛」误改名、「不用了谢谢」被当成名字 —— 改这里务必跑测试。
- **[welcome.py](../src/welcome.py)** — 全部文案 (与 020 逐字对齐, 除"目录在哪改"那句
  按宿主不同)。**改文案两侧一起改。**
- **[user_profile.py](../src/user_profile.py)** — 用户名与 state 机
  (unknown / awaiting_name / active), 落盘 `data/user_profiles.json`。
- **[scheduler.py](../src/scheduler.py)** — 22:00/23:00 未写提醒 + 启动补偿。
  提醒文案已改为"直接发就行"。受 iLink"20 小时无互动不能主动发消息"限制。

## 3. 当前运行状态 (2026-08-11 中午 · 美东)

**服务在用户这台 Mac 上, 由 launchd 常驻:**

- 标签 `com.wechat-diary.webui`, 装/卸: `bash scripts/install-launchd-mac.sh [--uninstall]`
- 页面 http://127.0.0.1:8765/ · 日志 `data/logs/webui.out.log` / `webui.err.log`
- **改了 `src/*.py` 必须重启才生效**:
  `launchctl kickstart -k gui/$(id -u)/com.wechat-diary.webui`
  (改 `src/web/index.html` 不用重启, 每次请求现读文件, 刷新页面即可)
- KeepAlive=true: 进程被 kill 也会自动拉回 (实测 8 秒)。所以**光 kill 停不掉它**,
  要停用 `--uninstall` 或 `launchctl bootout`。
- 微信登录态: 2026-08-11 12:17 重新扫码, `logged_in: true`, bot 正在跑。
  上一次的 session 活了约 27 小时后 `code=-14 session timeout`。
  **iLink session 会自然过期, 过期后页面第①步重新扫码即可, 不是 bug。**

**⚠️ 别碰的东西 (赛事评测中, 至少到 8/12 出结果):**
同一台 Mac 上还跑着 `src/mcp_http.py` (127.0.0.1:8977) + cloudflared 隧道
(URL 绑进程, 重启即永久失效, 表单改不了) + caffeinate 防休眠。
**不要关机/重启/合盖, 不要 kill 这三个进程。**

**代码状态:**
- 分支 `fix/webui-honest-state-and-launchd` 已推 GitHub, **未合 main** (等用户决定)。
  两个 commit: webui 断线状态诚实化 + launchd 常驻脚本。
- 测试 295 全绿。

**🕐 待用户拍板的时区问题 (已实测, 会影响日记正确性):**
用户当前在**美东 (EDT)**, 但 `config.TIMEZONE` 固定 `Asia/Shanghai`:
- 提醒 22:00/23:00 北京时间 = 用户本地**上午 10:00/11:00** (提醒基本失效)
- 日期归属按北京时间算: 用户本地 8/11 中午写的日记, 落进 **8/12** 的文件
- 我已提出两个方向 (跟随本机时区 / 把提醒小时数挪到本地晚上), **用户尚未答复**。
  这件事和"Agent 不智能"是两码事, 但同样影响体验, 记得提醒他给个结论。

## 4. 已完成的历史 (简史, 不必细看)

- **2026-08-09~10**: 只读 MCP server (`mcp_server.py`, 三工具, 物理无写路径) +
  本地 Web UI (`webui.py` + `web/index.html`, 三步向导) + PyInstaller 单文件
  打包与 CI 双平台构建。测试 150 → 187。
- **2026-08-10 晚**: 取名智能化 (新增 `names.py`) + "一次发送=一段"契约闭环
  (`_coalesce_items`)。4 视角对抗审查确认并修复 15 个真缺陷。测试 → 294。
- **2026-08-10 22:00**: 黑客松初赛已提交 (源码包 + 自建 MCP 隧道 URL)。
  v2.0.0 / v2.0.1 已发 Release (v2.0.1 = macOS 冻结版 CA 证书修复)。
- **2026-08-11 上午**: 事故复盘 + 修复 (见 §5 最后一条) + launchd 常驻。测试 → 295。

## 5. 踩过的坑 (别再踩)

**打包态 (PyInstaller) 专属:**
- `sys.executable` 在冻结态是 exe 自己, 不是 Python —— 用它 spawn 子进程会
  把程序自我复制 (Windows 真机事故, 现目录选择框走 PowerShell)。
- Windows 的 SO_REUSEADDR 允许第二个进程静默绑上已占用端口 → WebUIServer
  已在 win32 关掉 allow_reuse_address。
- APScheduler 的 trigger="cron" 字符串走 setuptools entry points, 冻结态
  找不到 → 已改显式 CronTrigger (timezone 必须显式传)。
- Windows 裸 Python 没有时区数据 → tzdata 的数据文件必须进包 (spec 已处理)。
- 冻结态 .env/data/ 必须放 exe 旁边 (paths.py/config.py 有 frozen 分支),
  放临时解包目录会每次运行丢状态。
- **macOS 冻结版必须带 CA 证书**: 构建机 Python 的证书路径在用户机器上不存在,
  缺 certifi 则所有 HTTPS 直接 CERTIFICATE_VERIFY_FAILED (二维码/AI 全挂);
  Windows 走系统证书库幸免。已修: spec 打入 certifi, config.py 冻结分支设
  SSL_CERT_FILE。

**iLink 平台:**
- qrcode_img_content 是**二维码页面的链接** (text/html), 不是图片 —— 前端用
  本地 qrcode.js (MIT) 把链接画成码, 另有"官方二维码页面"兜底链接。
- bot ~20 小时无互动就不能主动发消息 (平台反骚扰, 无法绕开): 任何依赖
  "bot 主动找用户"的设计都要打问号; 22:00/23:00 提醒本身也受此约束。
- 登录 session 单点, 新扫码顶掉旧机器; session 约 1 天后自然过期 (-14)。
- iLink API 强制直连 (代码清 proxy 环境变量), Clash TUN 模式仍可能干扰。

**并发 (webui.py BotRunner, 对抗审查抓出的):**
- 停止是异步的: run_loop 在长轮询返回后才检查停止位, 最长 ~70s
  (2 transport × 35s)。JOIN_TIMEOUT=90 必须大于这个值。
- "停止中"窗口内 start 不能走幂等分支; 用户 stop 意图用 _user_stop 跨
  stop_event 换代保存; 重扫码热切换必须 join 旧线程后再落盘新 state
  (relogin_async), 否则旧线程整体覆盖新 token。

**网络环境 (用户机器上常年开着 Clash):**
- **cloudflared 默认 QUIC 会被 Clash TUN 打死** (fake-IP 198.18.x 段),
  必须 --protocol http2; trycloudflare 快速隧道的 URL 绑进程生命周期。
- open.hirebox.cn (提交平台) 经 Clash 会 TLS 中断, 访问需直连。

**macOS 常驻与权限 (2026-08-11, 真实事故):**
- 事故: 8/10 23:55 服务进程被关掉, 一整晚微信消息没人接; 第二天早上页面却还
  写着"运行中"、绿点在闪、停止按钮可点。根因是前端轮询失败时只挂了离线横幅,
  面板继续渲染断线前的快照 → **服务已死, 页面在说它活着**。已修 (markOffline)。
- **launchd 进程不继承任何 TCC 授权**: 日记目录在 ~/Documents (受保护),
  终端里跑得好好的, 换 launchd 就 readdir EPERM。注意 **stat 能过、readdir 才挂**,
  所以是 `_diary_dir_ok` 判 True 之后才炸。解法: 给 Python 开完全磁盘访问。
- **授权必须给真身**: /usr/bin/python3 是 xcode-select 跳板, 会 exec 掉
  `/Library/Developer/CommandLineTools/.../3.9/bin/python3.9`, TCC 认后者。
  plist 里也要写真身路径 (安装脚本用 realpath 解析), 否则用户授权了也对不上号。
  **用户已给这个 python3.9 开了完全磁盘访问** (读写均已实测通过)。
- 连带加固: api_status 对 OSError 降级返回 `diary_dir_error`, 不再让整个
  /api/status 500 —— 否则前端只显示"连不上本地服务", 把一个能修的权限问题
  伪装成程序挂了 (而 bot 还活着、还在收消息、还在写不进去, 消息会被吃掉)。

**环境:**
- 部署机 Python 3.9 (语法必须 3.9 兼容; CI 是 3.11/3.13), Windows 终端 GBK
  (所有 stdio 都要显式 UTF-8 包装)。
- Mac (开发机) 的 pytest/apscheduler/pyinstaller 装在 user site,
  本机 python3 即 3.9.6 (与部署机同版本, 跑通测试即验证了 3.9 兼容)。

## 6. 已知未修的小问题 (记录在案, 优先级低)

- mcp_server.message_blocks 两个边界与契约有细微出入 (时间头后直接跟正文的
  块、frontmatter 不闭合) —— 仅手工编辑过的文件会触发, writer 不会产出。
- envfile 同名键多次出现只替换首行 (与 config 解析器"首行生效"一致, 故意的)。
- webui _read_json_body 对虚报 Content-Length 的请求会阻塞 (localhost +
  token 门槛下接受)。
- 值以引号开头/结尾的 .env roundtrip 不可逆 (文档化的降级)。
- exe 无代码签名 → SmartScreen 警告; 无自动更新机制 (用户重新下载)。
- start-web.bat 与 Mac 版二进制均未真机验证过。
- 取名裸兜底对"就就"类叠引导字名字会剥坏; 陌生人发纯空语音会收到"没听清"
  回复 (绕过单用户拒绝, 预先存在)。

## 7. 没做的事 (需要主动提醒用户)

- [ ] **时区结论** (见 §3), 用户还没答复。
- [ ] `fix/webui-honest-state-and-launchd` 要不要合 main。
- [ ] **8/12 关注晋级通知**; 若晋级: 2 分钟演示视频 + ≤6 页 PPT + 朋友的
  真实用户反馈 (他踩中并见证修复的证书 bug 本身就是好素材)。
- [ ] **确认朋友用修复版跑通全链路** (桌面 wechat-diary-win-mac.zip 已是
  v2.0.1 内容; 旧的 submission.zip 是过时草稿, 建议删除)。
- [ ] 评测结束后收尾: 停掉 Mac 上的 mcp_http/cloudflared/caffeinate;
  日记管道要不要迁回 Windows 部署机 (重扫码即可)。
- [ ] 官网落地页 (Cloudflare Pages, 介绍+下载按钮) —— 用户认可的方向, 未做。
- [ ] 隐私遗留问题 (对抗推演指出、用户未表态): 用户日记含第三方敏感信息
  (客户咨询等), 送云端 LLM 润色存在张力; 本地模型选项 (如 Ollama) 值得
  在某个版本提供; 一切对外展示/demo 必须剔除可识别第三方信息。
  **本轮改 Agent 智能度时, 若打算把更多上下文喂给云端 LLM, 必须先跟用户
  确认这条。**

## 8. 与用户协作的方式

- 用户常用语音输入, 消息里会有错字/同音字 (如 "VBUI"="webui"), 按语境理解。
- 解释技术事项要具体到"打开什么、点什么、输入什么", 避免行话; 但用户产品
  直觉很强, 讨论产品决策时直接给判断和理由, 别绕。
- 他会给很具体的产品反馈, 认真当需求听; 但涉及 §1 红线时直说"这条你定过了"。
- 改动前后必跑 `python3 -m pytest tests/` (当前 295 全绿); 重大改动跑一轮
  多 agent 对抗审查再交付。
- 提交风格: 中文 commit message, `feat/fix(scope): 摘要` + 正文写清为什么。
- 用户要求推送时才推; 合 main 之类的决定先问。
- 涉及他机器上的操作 (系统设置/权限/进程), 他可能不熟 macOS 术语 ——
  给出"面板标题长什么样"这类可核对的判断标准, 比报路径管用。
