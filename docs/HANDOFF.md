# HANDOFF — 交接文档

> 写给下一个接手本项目的 AI Agent。最后更新: 2026-08-10 晚。
> 读完本文件, 你应该知道: 已经做了什么、正在等什么、哪些坑别再踩、
> 哪些事没做完需要主动提醒用户。

## 0. 一句话与不可谈判项

wechat-diary = 微信说话 → 用户自己电脑上的 markdown 日记。管道 + 提醒, 仅此而已。

**产品哲学红线 (用户 2026-08-10 在多方案推演后明确拍板, 不要再挑战):**

1. **只做记录管道 + 未写提醒**。用户明确拒绝一切"回声/回顾/把旧日记还给用户"
   类功能 (理由: 不完善的 Agent 递不合时宜的旧文是伤害)。**不要再提议此类功能。**
2. 它不是聊天 Agent。闲聊模式只是防误记的守门。
3. 数据主权: 纯本地 markdown, 永不做云托管/SaaS/多用户。
4. 零 key 可用是底线, AI 失败时原文照存。
5. 深度需求 (回顾/检索/周报) 的唯一出口 = 只读 MCP + 用户自选 Agent。
6. 命令行入口 (main.py / start.bat / ilink.py login) 永远保留, webui 是并列入口。
7. 开箱即用优先: 能少让用户配一样东西就少配一样。

## 1. 本轮 (2026-08-09 ~ 08-10) 做了什么

按时间序, 全部在 **feat/hackathon-mcp 分支** (未合 main):

1. **只读 MCP server** `src/mcp_server.py`: 零依赖 stdio JSON-RPC, 三个工具
   (diary_read/search/recent), 物理上无写入路径。配套 `docs/demo-vault/`
   (合成演示数据) 与 `docs/hackathon.md` (Eazo 黑客松参赛说明+表单文案)。
2. **本地 Web UI** (`src/webui.py` + `src/web/index.html` + `src/envfile.py`):
   三步向导 (扫码绑微信→选文件夹→启停面板)。ilink.py 仅增量改动:
   fetch_login_qr / check_login_status / run_loop 的 should_stop 参数。
   设计契约见 `docs/webui-design.md` (API 表 + 安全模型 + 跨平台陷阱)。
3. **v2 单文件打包**: `wechat-diary.spec` (PyInstaller) +
   `.github/workflows/build.yml` (windows+macos 云端矩阵构建, 带启动冒烟;
   推本分支即构建, 推 v* tag 自动发 Release)。
4. 测试从 150 → **187 个**, 全绿。每轮大改动后跑过多 agent 对抗审查,
   共确认并修复 10+ 个真 bug (复现脚本验证过)。

## 2. 当前状态 (交接时刻)

- **等待用户的 Windows 真机验证结果** (todo 挂起中):
  ① 全链路: 微信发「开始记日记」→ 说话 → 选定文件夹里出现当日 .md;
  ② 「浏览」按钮弹窗置顶修复是否生效 (修复包 = Actions run 31373519143 的
  wechat-diary-windows artifact)。
- 用户 Mac 上可能还有一个开发版 webui 进程挂在 8765 端口 (测试用, 可杀)。
- 用户的正式部署机是 Windows; **iLink session 是单点的, 在任何新机器扫码
  都会顶掉旧机器的登录** —— 在 Mac 上测试扫码前必须提醒用户这一点。
- **黑客松初赛提交状态未确认**: 截止是 2026-08-10 22:00, 用户当时说
  "先不管提交问题, 做网页版"。**接手后第一时间问用户是否赶上了提交**;
  若晋级复赛 (8/12 通知), 需要: 2 分钟演示视频 + ≤6 页 PPT + 至少一位
  同画像真实用户的体验反馈 (复赛 8/16 北京/上海线下路演, 8/17 新加坡)。

## 3. 用户预告的下一步: "大修"

用户原话: 接下来要大修, 包括 "Agent 内部的内容调整" 等多方面调整。
**具体范围未知, 开工前先问清楚**。大概率涉及: 文案 (welcome.py 集中了全部
微信端文案)、闲聊 prompt (chat_handler.py 的 CHAT_SYSTEM_PROMPT)、润色
prompt (diary_writer.py 的 POLISH_PROMPT)、提醒文案 (scheduler.py)。
注意: **tests/ 里大量断言绑定了具体文案字符串**, 改文案必须同步改测试。

## 4. 踩过的坑 (别再踩)

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

**iLink 平台:**
- qrcode_img_content 是**二维码页面的链接** (text/html), 不是图片 —— 前端用
  本地 qrcode.js (MIT) 把链接画成码, 另有"官方二维码页面"兜底链接。
- bot ~20 小时无互动就不能主动发消息 (平台反骚扰, 无法绕开): 任何依赖
  "bot 主动找用户"的设计都要打问号; 22:00/23:00 提醒本身也受此约束。
- 登录 session 单点, 新扫码顶掉旧机器。
- iLink API 强制直连 (代码清 proxy 环境变量), Clash TUN 模式仍可能干扰。

**并发 (webui.py BotRunner, 对抗审查抓出的):**
- 停止是异步的: run_loop 在长轮询返回后才检查停止位, 最长 ~70s
  (2 transport × 35s)。JOIN_TIMEOUT=90 必须大于这个值。
- "停止中"窗口内 start 不能走幂等分支; 用户 stop 意图用 _user_stop 跨
  stop_event 换代保存; 重扫码热切换必须 join 旧线程后再落盘新 state
  (relogin_async), 否则旧线程整体覆盖新 token。

**环境:**
- 部署机 Python 3.9 (语法必须 3.9 兼容; CI 是 3.11/3.13), Windows 终端 GBK
  (所有 stdio 都要显式 UTF-8 包装)。
- Mac (开发机) 的 pytest/apscheduler/pyinstaller 装在 user site。

## 5. 已知未修的小问题 (记录在案, 优先级低)

- mcp_server.message_blocks 两个边界与契约有细微出入 (时间头后直接跟正文的
  块、frontmatter 不闭合) —— 仅手工编辑过的文件会触发, writer 不会产出。
- envfile 同名键多次出现只替换首行 (与 config 解析器"首行生效"一致, 故意的)。
- webui _read_json_body 对虚报 Content-Length 的请求会阻塞 (localhost +
  token 门槛下接受)。
- 值以引号开头/结尾的 .env roundtrip 不可逆 (文档化的降级)。
- exe 无代码签名 → SmartScreen 警告; 无自动更新机制 (用户重新下载)。
- start-web.bat 与 Mac 版二进制均未真机验证过。

## 6. 没做的事 (需要主动提醒用户)

- [ ] **确认黑客松初赛是否提交** (见第 2 节, 接手第一件事)。
- [ ] 等 Windows 验证双通过后: 打 v2.0.0 tag 发首个 Release (build.yml 会
  自动挂产物), README 安装章节改成"下载 exe 即用"优先。
- [ ] 合并 feat/hackathon-mcp → main (体验链接指向仓库时评委看到的是 main);
  合并后可删掉 build.yml 里的临时 branch 触发。
- [ ] 官网落地页 (Cloudflare Pages, 介绍+下载按钮) —— 用户认可的方向, 未做。
- [ ] 隐私遗留问题 (对抗推演指出、用户未表态): 用户日记含第三方敏感信息
  (客户咨询等), 送云端 LLM 润色存在张力; 本地模型选项 (如 Ollama) 值得
  在某个版本提供; 一切对外展示/demo 必须剔除可识别第三方信息。
- [ ] 复赛材料 (若晋级): 视频/PPT/真实用户反馈。

## 7. 与用户协作的方式

- 用户常用语音输入, 消息里会有错字/同音字 (如 "VBUI"="webui"), 按语境理解。
- 解释技术事项要具体到"打开什么、点什么、输入什么", 避免行话; 但用户产品
  直觉很强, 讨论产品决策时直接给判断和理由, 别绕。
- 改动前后必跑 `python3 -m pytest tests/` (187 个应全绿); 重大改动跑一轮
  多 agent 对抗审查再交付 (本轮实践: 审查抓出的真 bug 比人肉自查多得多)。
- 提交风格: 中文 commit message, `feat/fix(scope): 摘要` + 正文写清为什么。
- 用户要求推送到分支时才推; 合 main 之类的决定先问。
