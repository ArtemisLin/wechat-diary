# HANDOFF — 交接文档

> 写给下一个接手本项目的 AI Agent。最后更新: **2026-08-11 中午 (美东)**。
> 读完本文件, 你应该知道: 下一件事干什么、系统怎么跑起来的、对话链路长什么样、
> 哪些坑别再踩、哪些事没做完需要主动提醒用户。
>
> **⚠️ 上下文已被清理过。用户手上有一批攒好的反馈意见, 接手第一件事是听他说完。**

## 0. 下一步要做的事 (2026-08-11 起, 当前任务)

**主题: Agent 对话质量整改 —— "功能都通了, 但它很不智能"。**

用户原话: *"现在功能性的问题做好了, 但是这个 Agent 它非常的不智能, 也就是说
它跟用户对话的时候经常会出现各种各样的问题, 我们接下来就要修复这样的问题。"*

工作方式建议:
1. **先把用户的反馈清单收完整再动手。** 他会一条条提 (可能是语音输入, 有错字)。
   逐条记录成清单, 分类 (意图识别 / 模式切换 / 回复文案 / 记录准确性 / 时机),
   再判断每条是"规则不够"还是"架构不对"。别听一条改一条, 这些问题大概率同源。
2. 改之前读下面 §2 的对话链路地图, 知道每个决策点在哪一行。
3. **守住 §1 的产品红线** —— 尤其"不做回顾/回声类功能""零 key 可用"
   "AI 失败原文照存"。对话变聪明不能以吞掉用户日记为代价。
4. 每改一处补测试; `python3 -m pytest tests/` 当前 **295 个应全绿**。
5. 大改动跑一轮多 agent 对抗审查再交付 (历史经验: 审查抓出的真 bug 远多于自查)。

### 我(上一任)观察到的可疑点 —— 仅供参照, 以用户实际反馈为准

这些是读代码时看到的结构性弱点, **没有经过用户确认**, 不要当成已定的 bug 清单:

- **diary 模式是个黑洞**: 除了 UNDO / FINALIZE, 其余任何消息一律直接写进日记
  ([main.py:75-80](../src/main.py))。用户在记录中问一句"刚才那条记上了吗"
  "你还在吗", 会被原样写进当天日记。这大概是"不智能"感最强的来源。
- **意图识别是纯规则 + 15 字长度阈值** ([intents.py](../src/intents.py)):
  超过 15 字就默认判日记, 只有 START_DIARY 有子串短语兜底。像
  "好了今天就先这样吧" 这种自然收尾语识别不到, 只认"结束/收工/归档"等词。
- **模式切换只认关键词**, 没有语义兜底; 而 chat 模式的 LLM 被明令禁止宣称
  自己切了模式 ([chat_handler.py:33-37](../src/chat_handler.py)) —— 用户
  说了个近义句没命中词表时, bot 只会干巴巴地重复"发『开始记日记』就开始"。
- **闲聊 LLM 没有任何记忆与画像**: system prompt 固定, 历史只有内存里 5 轮,
  进程重启即失忆 ([chat_handler.py:52-54](../src/chat_handler.py)); 也读不到
  用户的名字/习惯 (user_profile 有名字但没喂给 LLM)。
- **润色是单条无上下文** ([diary_writer.py:28-36](../src/diary_writer.py)),
  连续几段之间没有连贯性概念。
- **回复文案大量静态随机池** ([welcome.py](../src/welcome.py)), 多用几次
  就能感到机械重复。
- **成本提示可能烦人**: chat 第 2 条起每条都追加 CHAT_COST_REMINDER
  ([main.py:112-114](../src/main.py))。
- **跨天自动 reset 回 chat 模式** ([session_state.py:54-69](../src/session_state.py)):
  北京时间过 0 点后, 正在记录的用户下一条消息会掉回闲聊模式。
- **时区错位 (已实测, 见 §3)**: 用户人在美东, 日期按北京时间算。

## 1. 一句话与不可谈判项

wechat-diary = 微信说话 → 用户自己电脑上的 markdown 日记。管道 + 提醒, 仅此而已。

**产品哲学红线 (用户 2026-08-10 在多方案推演后明确拍板, 不要再挑战):**

1. **只做记录管道 + 未写提醒**。用户明确拒绝一切"回声/回顾/把旧日记还给用户"
   类功能 (理由: 不完善的 Agent 递不合时宜的旧文是伤害)。**不要再提议此类功能。**
2. 它不是聊天 Agent。闲聊模式只是防误记的守门。
   *(注: 本轮整改是让这个守门更聪明, 不是把它变成聊天机器人 —— 边界仍在。)*
3. 数据主权: 纯本地 markdown, 永不做云托管/SaaS/多用户。
4. 零 key 可用是底线, AI 失败时原文照存。
5. 深度需求 (回顾/检索/周报) 的唯一出口 = 只读 MCP + 用户自选 Agent。
6. 命令行入口 (main.py / start.bat / ilink.py login) 永远保留, webui 是并列入口。
7. 开箱即用优先: 能少让用户配一样东西就少配一样。

## 2. 对话链路地图 (改 Agent 行为前必读)

```
微信消息
  └─ ilink.run_loop            长轮询收消息; _coalesce_items 把平台拆开的
     (src/ilink.py:587)        同一条消息多 item 无损拼回"一次发送"
       └─ main._on_message     离线>12h 时给首条回复附一次性提示
          (src/main.py:174)
            └─ main._dispatch  首次见面欢迎 / 取名流程的守门
               (src/main.py:118)   profile.state: unknown → awaiting_name → active
                 └─ main._handle   ★ 双模式主路由, 绝大多数"不智能"问题在这里
                    (src/main.py:49)
```

`_handle` 内部的判定顺序 (这就是全部的"智能"):

| 顺序 | 判定 | 代码位置 | 说明 |
|---|---|---|---|
| 1 | 非本人消息直接拒 | main.py:51 | 单用户产品 |
| 2 | `session_state.load_or_reset` | main.py:55 | 取 mode, 跨天自动回 chat |
| 3 | `intents.detect(text)` | main.py:56 | **纯规则, 无 LLM** |
| 4 | HELP 全模式生效 | main.py:59 | |
| 5 | **diary 模式**: UNDO / FINALIZE / 其余全部写日记 | main.py:63-80 | 每 4 段追加劝收尾 |
| 6 | **chat 模式**: START_DIARY → 进 diary | main.py:83-92 | 同句带称呼会一并收下 |
| 7 | chat 模式: UNDO/FINALIZE → 提示不在记录中 | main.py:94-97 | |
| 8 | chat 模式: 「叫我XX」→ 改名 | main.py:100-103 | names.py 规则引擎 |
| 9 | chat 模式: CHAT(招呼词) → 静态回复池 | main.py:105-107 | 省 LLM 开销 |
| 10 | chat 模式: 其余 → LLM 闲聊 | main.py:110 | chat_handler.chat |
| 11 | chat 第 2 条起附成本提示 | main.py:112-114 | |

各模块职责:

- **[intents.py](../src/intents.py)** — 规则意图识别。`MAX_COMMAND_LEN=15`:
  只有短消息才匹配命令词; 长句仅靠 `_START_DIARY_PHRASES` 子串兜底。
  normalize 会剥尾部语气词 (吧/啊/啦/呀/哦/嘛/呗/哈) 和标点。
- **[session_state.py](../src/session_state.py)** — chat/diary 双态 +
  当日 chat 计数, 落盘 `data/session_state.json`, 跨天 reset。
- **[chat_handler.py](../src/chat_handler.py)** — 闲聊 LLM。system prompt
  里有一段**强约束禁止它宣称模式切换** (历史上它撒过谎), 改 prompt 时别删。
  历史 5 轮, 内存 deque, 不持久化。
- **[diary_writer.py](../src/diary_writer.py)** — 润色 (`POLISH_PROMPT`,
  temperature 0.3) + 原子写入 + 计数/撤回/封存。**LLM 失败必须原文照存**,
  错误分类 → `NET_NOTE_BY_KIND` 友好提示。
- **[names.py](../src/names.py)** — 取名规则引擎 (「叫我X」/裸名/拒绝识别/
  复读折叠/疑问句排除), 配 key 时 LLM 兜底。踩过 2 个 critical:
  闲聊「你叫我干嘛」误改名、「不用了谢谢」被当成名字 —— 改这里务必跑测试。
- **[welcome.py](../src/welcome.py)** — 全部静态文案与随机池 (欢迎/帮助/
  招呼/收尾/劝收尾/成本提示/取名相关模板)。**改文案基本都在这个文件。**
- **[user_profile.py](../src/user_profile.py)** — 用户名与 state 机
  (unknown / awaiting_name / active), 落盘 `data/user_profiles.json`。
- **[scheduler.py](../src/scheduler.py)** — 22:00/23:00 (北京时间) 未写提醒 +
  启动补偿 `run_catchup`。受 iLink"20 小时无互动不能主动发消息"限制。

一条消息的实际日志足迹: `data/logs/ilink.log` (收发), `data/logs/ai.log`
(LLM 调用与失败), `data/logs/webui.out.log` (控制台打印, 含提醒触发)。

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
