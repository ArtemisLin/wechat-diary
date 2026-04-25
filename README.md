# wechat-diary

## 2026-04 网络说明(最新版)

若本文其他位置与本节冲突,以本节为准。

- `019Diary` 的 iLink 默认使用 `ILINK_PROXY_MODE=auto`
- `auto` 会先尝试直连 `ilinkai.weixin.qq.com`,失败后再尝试本地代理
- 本地代理默认自动探测 `127.0.0.1:7890 / 7897 / 7891`
- 无代理电脑通常不需要额外配置,保留默认 `auto` 即可
- 有 Clash/VPN/TUN 的电脑,也可以显式设置:

```ini
ILINK_PROXY_MODE=proxy
ILINK_PROXY_URL=http://127.0.0.1:7890
```

- 若想强制直连,可以设置:

```ini
ILINK_PROXY_MODE=direct
```

- `python src/ilink.py status` 会显示当前 `proxy_mode`、`active_transport` 和探活结果
- 登录时如果微信侧已经确认,但登录后的短探活暂时遇到网络抖动,程序会先保存 session,不再把这类 `network` 误判成登录失败
- 推荐优先用 `start.bat` 启动; 它会检查本地登录态,在 session 过期时自动要求重新扫码

一个专注做一件事的微信日记 Agent:**对着微信说话 → AI 轻度润色 → 自动存到 Obsidian vault**。

核心价值:
- 零切换成本:微信里直接说,不用打开别的 App
- 强制坚持:每晚北京时间 22:00 和 23:00 两次主动提醒,还没写就催你
- 无缝归档:写到 OneDrive 同步文件夹,Obsidian 自动可见

## 工作流

```
[微信] ─语音/文字→ [iLink] ←轮询─ [本机 wechat-diary]
                                        │
                                        ├─ LLM 轻度润色(去口语/分段)
                                        ├─ 追加到 OneDrive/DiaryVault/YYYY-MM-DD.md
                                        └─ 22:00/23:00 未写则微信提醒
                                                │
                                        OneDrive 同步 → Obsidian vault 自动可见
```

## 快速开始

### 1. 安装依赖

```bash
python -m pip install apscheduler tzdata
```

### 2. 建 `.env` 文件

在 `wechat-diary/` 根目录新建 `.env`,把下面这段复制进去并**只填三个密钥**:

```ini
# === 必填 ===
# DeepSeek API Key (https://platform.deepseek.com)
AI_API_KEY=

# iLink 扫码登录后返回的 ilink_user_id
# 先跑 `python src/ilink.py login` 拿到,再回填这里
USER_ID=

# 日记存放目录的绝对路径(目录不存在会自动创建)
# 用 Obsidian 的话, 填你的 vault 路径; 不用 Obsidian 的话, 任意目录都行
# 示例:
#   Windows: D:/Obsidian/MyDiary  或  C:/Users/<你的用户名>/Documents/MyDiary
#   macOS:   /Users/<你的用户名>/Documents/MyDiary
#   Linux:   /home/<你的用户名>/obsidian/MyDiary
# 想手机也能同步看: 放到 OneDrive / iCloud / Dropbox 等云盘同步目录下
DIARY_DIR=

# === 可选(默认就够用) ===
AI_BASE_URL=https://api.deepseek.com/chat/completions
AI_MODEL=deepseek-chat
TIMEZONE=Asia/Shanghai
REMIND_HOUR_1=22
REMIND_HOUR_2=23

# === 网络 ===
# iLink API 强制直连（不走 Clash，参考 017Pet/015fridge 踩坑经验），没有相关开关。
# 只有 AI API (DeepSeek) 可配代理：
# auto: 先直连,失败时尝试本地代理(适合大多数情况)
# direct: 强制直连
# proxy: 强制走代理(并配 AI_PROXY_URL)
AI_PROXY_MODE=auto
AI_PROXY_URL=http://127.0.0.1:7890
```

### 3. 扫码登录 iLink

```bash
cd src
python ilink.py login
```

扫码确认后会打印 `ilink_user_id`,把它粘到 `.env` 的 `USER_ID`。

### 4. 启动

双击根目录 `start.bat`,或命令行:

```bash
cd src
python main.py
```

看到 `=== wechat-diary 已启动 ===` 就 OK。

`start.bat` 会自动做两件事:
- 找到可用的 Python(支持 `py` / `python` / 常见本机安装目录)
- 如果 iLink session 过期,自动重新走扫码登录

### 5. 网络兼容

- **iLink API 强制直连**：参考 017Pet/015fridge 的踩坑经验，`ilinkai.weixin.qq.com` 走 Clash 会出现 TLS 中间层延迟、QR 状态轮询超时等怪问题。代码里通过清空 proxy 环境变量 + `no_proxy=*` + `ProxyHandler({})` 三重保险强制绕过。**没有开关可调。**
- **AI API 可选代理**：DeepSeek 默认 auto（先直连，失败回落 Clash），也可 direct/proxy 强制。

程序运行时会在 `data/logs/ilink.log` 写调试日志,用于排查收发消息问题。

## 验收流程

1. **基本写入**:在微信对 bot 发语音"今天天气不错" → Agent 回 `🎤 记下啦 ✍️ 今天第 1 段` → 去 `DIARY_DIR` 看到当天 md 文件,内容已润色
2. **同日追加**:再说一段 → 回 `🎤 记下啦 ✍️ 今天第 2 段` → 同文件尾追加,旧段原样保留
3. **LLM 故障**:临时把 `AI_API_KEY` 改错,发一段 → 回复带 `(网络波动,原文已存)`,文件里是原始转写
4. **提醒**:临时把 `.env` 里 `REMIND_HOUR_1` 改成马上要到的那个小时,重启 → 到点收到微信提醒
5. **已写跳过**:当天已写过日记,等到 22:00/23:00 → 应无提醒
6. **Obsidian**:在 Obsidian 打开 vault + 开启 Daily Notes 插件 → 日历上高亮当天

## 运行测试

```bash
python -m pytest tests/ -v
```

应看到 22 条全绿。

## 关键设计

### 时区

系统时间可能不是北京(比如开发机在美西),所有日期/时间计算**强制走 `config.now_bj()` / `config.today_str()`**,绝不用 `datetime.now()`。APScheduler 也用 `timezone="Asia/Shanghai"` 配置,触发时间严格按北京时间。

### 主动提醒的 24h 限制

iLink 要求 bot 只能在有有效 `context_token` 时主动发消息。如果超过 20h 没给 bot 发过消息,提醒会跳过(日志提示,不崩溃)。你下次发任何消息会自动刷新 token。这是 iLink 的反骚扰设计,无法绕开。

### 只追加,不重写

AI 只润色本次说的片段,然后 `append` 到文件尾。**旧段落永远不改**,最大化数据安全,避免 LLM 误删。

### 原子写入

所有写文件先写 `.tmp` 再 `os.replace()`,防崩溃丢数据。

## 目录结构

```
wechat-diary/
├── src/
│   ├── config.py          # env + 时区工具
│   ├── paths.py           # data/ 路径集中管理 + 旧文件迁移
│   ├── users.py           # 单用户实现(接口预留多用户)
│   ├── diary_writer.py    # LLM 润色 + 写 md
│   ├── ilink.py           # 精简 iLink 客户端(从 017Pet 借鉴)
│   ├── scheduler.py       # APScheduler 提醒
│   ├── welcome.py         # 文案 + 欢迎逻辑
│   ├── welcome_store.py   # 已欢迎用户集合持久化
│   └── main.py            # 入口
├── tests/                 # 单测(pytest)
├── start.bat              # 双击启动
├── data/                  # 运行时生成(勿入 git): state/log/已欢迎记录
│   ├── ilink_state.json
│   ├── welcomed_users.json
│   └── logs/
│       └── ilink.log
└── .env                   # 密钥(自建,勿入 git)
```

## 未来开源扩展

第一版单用户,但代码已为多用户预留接口:

| 现在 | 扩展只改这里 |
|------|-----------|
| `.env` 读 `USER_ID` / `DIARY_DIR` | `users.py` 改成从 `users.json` 或 SQLite 加载 |
| `users.load(user_id)` 只接受 env 中的 ID | 扩展 `users.load` 内部实现 |
| `users.all_active()` 返回单个 ID | 返回多个 |

**业务代码不用改**:`diary_writer.write(user_id, ...)` / `scheduler.check_and_remind(user_id, ...)` 签名完全不变。

## 明确不做

- 跨笔记本适配(Notion/飞书/印象笔记)
- 日记搜索、检索、导出
- 情绪分析、主题提炼、周报月报
- 图片/视频附件
- 进程自启/守护(未来补)

## 许可

未决定(至少先跑稳再谈开源)。
