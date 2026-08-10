# 本地 Web UI 设计 (v1)

> 目标: 把「clone → 改 .env → 命令行扫码 → 复制 USER_ID → 双击启动」的部署流程,
> 变成「运行一个程序 → 浏览器自动打开 → 扫码 → 点选文件夹 → 开始用」。
> 网页只是操作界面, **运行时永远在用户自己的机器上, 数据不经过任何服务器**。

## 架构

单进程, 新入口 `src/webui.py`:

```
python src/webui.py
  ├─ 启动 localhost HTTP 服务 (标准库 ThreadingHTTPServer, 默认 127.0.0.1:8765)
  ├─ webbrowser.open() 自动打开浏览器
  └─ BotRunner 线程 (配置齐备后启动):
       ├─ APScheduler 提醒 (复用 scheduler.py)
       └─ ilink.run_loop 长轮询 (复用, 新增 should_stop 回调)
```

- 零新依赖: HTTP 服务用标准库; 前端单文件 HTML 内联 CSS/JS, 无构建、无 CDN
- 现有 CLI 入口 (main.py / ilink.py login / start.bat) 原样保留, webui 是并列入口
- 消息路由完整复用 main.py 的 `_on_message` (import main, 不复制业务逻辑)

## 登录流程 (关键发现)

`GET /ilink/bot/get_bot_qrcode?bot_type=3` 返回的 `qrcode_img_content` 就是
二维码图片 URL —— 网页 `<img src>` 直接显示。登录状态轮询是无状态 GET,
由浏览器 JS 驱动 (每 2s 调一次后端, 后端单次查询 iLink)。

`confirmed` 时后端自动: 保存 ilink state + **把 ilink_user_id 写进 .env 的
USER_ID** (消灭现在手工复制粘贴那一步) + 运行时更新 config。

ilink.py 新增两个小函数 (不动现有 login(), 竞赛期最小改动面):
- `fetch_login_qr() -> dict | None` — 取 {qrcode, qr_img_url}
- `check_login_status(qrcode) -> dict` — 单次查询; confirmed 时构建并 save_state, 返回 {status, state?}

`run_loop(state, on_message, should_stop=None)` — 新增可选参数, 每轮循环开头
检查, True 则优雅退出返回 "stopped"。默认 None 行为与现在完全一致。

## API 契约 (全部 JSON, 需 X-Auth 头)

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | / | - | index.html ({{TOKEN}} 占位符替换为本次运行的随机 token, 注入 `window.AUTH_TOKEN`) |
| GET | /api/status | - | {logged_in, bot_running, user_id_masked, diary_dir, diary_dir_ok, ai_key_set, remind_hours:[h1,h2], today:{date, count, sealed}, recent:[{date,count,sealed}...≤7]} |
| POST | /api/login/start | {} | {ok, qr_img_url} 或 {ok:false, error} |
| GET | /api/login/poll | - | {status: waiting/confirmed/expired/canceled/error, user_id?} |
| POST | /api/config | {diary_dir?, ai_api_key?} | {ok, error?} — 校验绝对路径/可写, 原子写 .env (保留注释与未知键), 运行时更新 config, bot 在跑则自动重启 |
| POST | /api/folder/pick | {} | {ok, path?} — 原生目录选择框; 失败/不支持返回 ok:false, 前端回落手输 |
| POST | /api/bot/start | {} | {ok, error?} — 需 logged_in && diary_dir_ok |
| POST | /api/bot/stop | {} | {ok} |

## 安全 (localhost 也要设防)

任何网页都能对 127.0.0.1 发请求 (CSRF/DNS rebinding), 而这个服务管着日记目录:

1. 只绑 127.0.0.1
2. 每次启动生成随机 token, 注入页面; 所有 /api/* 校验 `X-Auth` 头 — 恶意网页
   拿不到 token (无 CORS 头, 跨源读不了响应)
3. 校验 Host 头必须是 127.0.0.1/localhost (防 DNS rebinding)
4. 响应不回显 AI key (status 只给 ai_key_set 布尔)
5. 不提供任何读日记内容的接口 (状态只有条数/是否封存, 正文留在 Obsidian 里看)

## 目录选择框 (跨平台陷阱)

tkinter 的 filedialog 在 macOS 上必须跑主线程, HTTP handler 是子线程 → 崩。
方案: **子进程隔离** —— darwin 用 `osascript` (choose folder), Windows 用
`python -c "...tkinter askdirectory..."` 子进程, 其他平台返回 ok:false。
前端始终保留手动输入路径作为兜底。

## .env 写入 (src/envfile.py)

`update_env(path, {key: value})`: 逐行解析, 已有键原位替换, 新键追加到尾部,
注释与空行原样保留; 先写 .tmp 再 os.replace (原子)。值含空格/# 时加引号。

## 前端 (src/web/index.html)

单文件, 中文, 手机友好宽度。三步向导 + 状态面板, 按 /api/status 自动定位步骤:

1. **绑定微信**: 点按钮 → 显示二维码 → 轮询 → 成功打勾
2. **选日记文件夹**: [浏览...] (原生框) 或手输绝对路径; 可选填 AI key (DeepSeek)
3. **运行**: 大按钮启动; 状态面板显示 运行中/已停止、今天是否已记、最近 7 天
   概览 (日期+条数+封存)、提醒时间; session 过期时提示回第 1 步重新扫码

每 5s 轮询 /api/status。无任何外部资源引用。

## 测试

- envfile: 注释保留/原子性/引号/新增键
- webui API: 起真实服务于随机端口, monkeypatch ilink 的网络函数, http.client 走一遍
  登录流/config 校验/token 拒绝/Host 校验/未登录 start 被拒
- run_loop should_stop: 打桩 _api_request, 验证优雅退出
- 目录选择框、浏览器自动打开: 不进 CI (子进程/GUI), 手工冒烟

## v1 不做 (后续)

- 打包 exe / .app (pyinstaller, 需在 Windows 部署机上做) → v2
- 官网落地页 (Cloudflare Pages) → v2
- 提醒时间在页面上改、日志查看 → 观察需求再说
