# HANDOFF — 交接文档

> 写给下一个接手本项目的 AI Agent。最后更新: 2026-08-10 深夜 (初赛提交完成后)。
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

按时间序 (当时在 feat/hackathon-mcp 分支, **现已全部合入 main**):

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

## 2. 当前状态 (交接时刻, 2026-08-10 深夜)

- **初赛已提交** (8/10 22:00 截止前): 源码包 = 桌面 wechat-diary-v2.0.0-src.zip;
  "自建 MCP (选填, 验证通过 +5)" 填的是下面的隧道 URL。每组一份, 已锁定。
- **⚠️ 用户这台 Mac 在评测结束前 (至少到 8/12 出结果) 不能关机/重启/合盖**:
  上面跑着 ① src/mcp_http.py (127.0.0.1:8977, 服务 demo-vault) ② cloudflared
  快速隧道 (http2 协议, URL: rough-existing-cathedral-letter.trycloudflare.com)
  ③ caffeinate 防休眠。隧道 URL 绑进程, 重启即永久失效 (表单改不了);
  短暂睡眠可自动重连、URL 不变。
- **v2.0.0 + v2.0.1 已发布** (Release 挂双平台单文件产物), main 已合并,
  build.yml 的临时分支触发已删。v2.0.1 = macOS 冻结版 CA 证书修复,
  v2.0.0 的资产也已原地替换成修复版。
- 用户的日记管道当前登录在这台 Mac 上 (webui, 端口 8901); 正式部署机
  Windows 被顶掉了 (iLink session 单点)。用户想切回去时在 Windows 重扫码即可。
- **朋友 (Mac 用户) 是第一个真实外部用户**: 首跑踩中证书 bug 已修复,
  需确认他用新包 (桌面 wechat-diary-win-mac.zip 或 Release latest) 跑通全链路;
  若晋级复赛, 他就是"同画像真实用户反馈"的人选 (复赛 8/16 北京/上海路演,
  8/17 新加坡; 需 2 分钟视频 + ≤6 页 PPT)。

## 3. 大修 (2026-08-10 晚, 已完成)

用户点的两个问题, 均已修复并提交:
1. **取名智能化**: 新增 src/names.py 规则引擎 (「叫我X」/「我叫X」/裸名/
   拒绝识别/复读折叠/疑问句排除, 配 key 走 LLM 兜底); awaiting_name 命令词
   拦截;「跳过」; chat 模式「叫我XX」改名 (白名单前缀+功能字过滤防误改)。
2. **一次发送=一段**: iLink 把 >200 字拆成同 msg 多 item → run_loop 用
   _coalesce_items 无损拼回一次投递; diary_writer 块内空行归一 + 排除前缀
   反斜杠转义, 契约"一个空行块=一条消息"闭环 (count/undo/MCP 同口径)。

流程: 4 视角多 agent 对抗审查 + 每发现 2 独立复核 → 确认 15 个真缺陷全部
修复 (2 critical: 闲聊「你叫我干嘛」误改名、「不用了谢谢」被当名字)。
测试 187 → 294, 全绿。

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

**打包态新增 (2026-08-10 深夜, 真实用户踩出) :**
- **macOS 冻结版必须带 CA 证书**: 构建机 Python 的证书路径在用户机器上不存在,
  缺 certifi 则所有 HTTPS 直接 CERTIFICATE_VERIFY_FAILED (二维码/AI 全挂);
  Windows 走系统证书库幸免。已修: spec 打入 certifi (故意不 try, 缺了就炸),
  config.py 冻结分支设 SSL_CERT_FILE。
- CI release job 的 mv 不能把产物改名成与 artifact 目录同名的路径 (撞名报
  "are the same file"), 已改移入 out/。
- **cloudflared 默认 QUIC 会被 Clash TUN 打死** (fake-IP 198.18.x 段),
  必须 --protocol http2; trycloudflare 快速隧道的 URL 绑进程生命周期。
- open.hirebox.cn (提交平台) 经 Clash 会 TLS 中断, 访问需直连。

**macOS 常驻 (2026-08-11, scripts/install-launchd-mac.sh):**
- 起因: 8/10 23:55 进程被关掉, 一整晚消息没人接, 第二天页面还写着"运行中"。
  launchd 的价值不是开机自启 (这台机器 63 天没重启), 是 KeepAlive —— 进程
  被 kill 掉 8 秒内自动拉回 (实测)。
- **launchd 进程不继承任何 TCC 授权**: 日记目录在 ~/Documents (受保护),
  终端里跑得好好的, 换 launchd 就 readdir EPERM。注意 stat 能过、readdir 挂,
  所以 _diary_dir_ok 判 True 之后才炸。解法是给 Python 开完全磁盘访问。
- **授权必须给真身**: /usr/bin/python3 是 xcode-select 跳板, 会 exec 掉
  /Library/Developer/CommandLineTools/.../3.9/bin/python3.9, TCC 认后者。
  plist 里也要写真身路径 (安装脚本用 realpath 解析), 否则授权对不上号。
- 相应加固: api_status 对 OSError 降级返回 diary_dir_error, 不再让整个
  /api/status 500 —— 否则前端只显示"连不上本地服务", 把权限问题伪装成
  程序挂了 (而 bot 还在收消息、还在写不进去, 消息会被吃掉)。
- 前端同源问题: 轮询失败时只挂横幅、面板继续显示断线前快照 → "无法连接"
  和"运行中"同框、停止按钮可点。已改为 markOffline() 统一置为状态未知。

**环境:**
- 部署机 Python 3.9 (语法必须 3.9 兼容; CI 是 3.11/3.13), Windows 终端 GBK
  (所有 stdio 都要显式 UTF-8 包装)。
- Mac (开发机) 的 pytest/apscheduler/pyinstaller 装在 user site,
  本机 python3 即 3.9.6 (与部署机同版本, 跑通测试即验证了 3.9 兼容)。

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

- [ ] **8/12 关注晋级通知**; 若晋级: 2 分钟演示视频 + ≤6 页 PPT + 朋友的
  真实用户反馈 (他踩中并见证修复的证书 bug 本身就是好素材)。
- [ ] **确认朋友用修复版跑通全链路** (桌面 wechat-diary-win-mac.zip 已是
  v2.0.1 内容; 旧的 submission.zip 是凌晨的过时草稿, 建议删除)。
- [ ] 评测结束后收尾: 停掉 Mac 上的 mcp_http/cloudflared/caffeinate;
  用户日记管道要不要迁回 Windows 部署机 (重扫码即可)。
- [ ] 官网落地页 (Cloudflare Pages, 介绍+下载按钮) —— 用户认可的方向, 未做。
- [ ] 隐私遗留问题 (对抗推演指出、用户未表态): 用户日记含第三方敏感信息
  (客户咨询等), 送云端 LLM 润色存在张力; 本地模型选项 (如 Ollama) 值得
  在某个版本提供; 一切对外展示/demo 必须剔除可识别第三方信息。
- [ ] 小遗留: 取名裸兜底对"就就"类叠引导字名字会剥坏 (审查 minor, 记录在案);
  陌生人发纯空语音会收到"没听清"回复 (绕过单用户拒绝, 预先存在)。

## 7. 与用户协作的方式

- 用户常用语音输入, 消息里会有错字/同音字 (如 "VBUI"="webui"), 按语境理解。
- 解释技术事项要具体到"打开什么、点什么、输入什么", 避免行话; 但用户产品
  直觉很强, 讨论产品决策时直接给判断和理由, 别绕。
- 改动前后必跑 `python3 -m pytest tests/` (187 个应全绿); 重大改动跑一轮
  多 agent 对抗审查再交付 (本轮实践: 审查抓出的真 bug 比人肉自查多得多)。
- 提交风格: 中文 commit message, `feat/fix(scope): 摘要` + 正文写清为什么。
- 用户要求推送到分支时才推; 合 main 之类的决定先问。
