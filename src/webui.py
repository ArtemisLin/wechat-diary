"""本地 Web UI 入口 (docs/webui-design.md 的工程实现)。

单进程三件事:
- ThreadingHTTPServer 只绑 127.0.0.1, 提供 src/web/index.html + /api/* JSON 接口
- BotRunner 后台线程封装 scheduler + ilink.run_loop (完整复用 main._on_message)
- webbrowser.open 自动打开浏览器 (--no-browser 关闭)

安全 (localhost 也要设防, 见设计文档):
- 启动时 secrets.token_hex 生成随机 token, 注入页面 {{TOKEN}}; 所有 /api/*
  校验 X-Auth 头 (恶意网页无 CORS 头读不到响应, 拿不到 token)
- 校验 Host 头必须是 127.0.0.1/localhost (防 DNS rebinding)
- 响应绝不回显 AI key (只给 ai_key_set 布尔), 不提供任何读日记正文的接口

用法:
    python src/webui.py [--no-browser]
    WEBUI_PORT=9000 python src/webui.py   # 换端口
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import config
import envfile
import ilink
import mcp_server
import paths

DEFAULT_PORT = 8765
TOKEN = secrets.token_hex(16)
ENV_PATH = paths.ROOT / ".env"
WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_FILE = WEB_DIR / "index.html"
QRCODE_JS = WEB_DIR / "qrcode.js"  # qrcode-generator (MIT, Kazuhiko Arase), 本地伺服零外链
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SEAL_MARKER = "_(今日封存于"  # 与 mcp_server.recent / diary_writer.CLOSING_MARKER 一致

PLACEHOLDER_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>wechat-diary</title></head>
<body style="font-family: system-ui; padding: 2rem;">
<h1>wechat-diary</h1>
<p>前端页面 (src/web/index.html) 还没就位, 后端 API 已在运行。</p>
<script>window.AUTH_TOKEN = "{{TOKEN}}";</script>
</body></html>
"""


# === BotRunner: bot 生命周期封装 ===

class BotRunner:
    """封装 scheduler + ilink.run_loop 的启动/停止/状态, 供 HTTP 线程调用。

    并发模型 (对抗审查后收紧):
    - stop 只置停止位不阻塞: run_loop 在下一轮循环开头退出, 极端网络下一轮
      长轮询最长 ~70s (2 个 transport × 35s 超时), 期间 stopping=True
    - "停止中"窗口内的 start 不能走幂等分支 (旧线程注定退出, 直接返回成功
      会让 bot 静默死亡): 转 restart_async 等旧线程退出后拉起
    - _user_stop 跨 stop_event 换代存活: restart/relogin 的 join 窗口内用户
      点停止, 意图绝不被吞掉
    """

    JOIN_TIMEOUT = 90  # 必须大于最坏单轮长轮询阻塞 (2 transport × 35s)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._user_stop = False
        self.session_expired = False
        self.last_error = ""

    @property
    def running(self) -> bool:
        t = self._thread
        return bool(t and t.is_alive())

    @property
    def stopping(self) -> bool:
        """线程还活着但已收到停止信号 (等长轮询返回的窗口)。"""
        return self.running and self._stop_event.is_set()

    def _start_locked(self) -> None:
        """真正建线程。调用方必须持有 self._lock 且确认没有活线程。"""
        self._user_stop = False
        self._stop_event = threading.Event()
        self.session_expired = False
        self.last_error = ""
        t = threading.Thread(
            target=self._run,
            args=(self._stop_event,),
            name="bot-runner",
            daemon=True,
        )
        self._thread = t
        t.start()

    def start(self) -> tuple[bool, str]:
        """启动 bot。真在跑则幂等; 停止中则转后台重启 (等旧线程退出后拉起)。"""
        pending_restart = False
        with self._lock:
            if self.running:
                if not self._stop_event.is_set():
                    return True, ""  # 真在跑, 幂等
                self._user_stop = False  # 停止窗口内点启动 = 用户要它跑
                pending_restart = True
            else:
                self._start_locked()
        if pending_restart:
            self.restart_async()
        return True, ""

    def stop(self) -> None:
        """用户请求停止 (非阻塞)。_user_stop 跨事件换代存活, 重启窗口内也不丢。"""
        with self._lock:
            self._user_stop = True
            self._stop_event.set()

    def restart_async(self) -> None:
        """后台重启: 停当前线程(系统性, 非用户意图) → 等退出 → 无用户停止则拉起。"""
        def _do() -> None:
            with self._lock:
                self._stop_event.set()  # 不置 _user_stop: 这是重启不是用户停止
                t = self._thread
            if t is not None:
                t.join(timeout=self.JOIN_TIMEOUT)
            with self._lock:
                if not self._user_stop and not self.running:
                    self._start_locked()
        threading.Thread(target=_do, name="bot-restart", daemon=True).start()

    def relogin_async(self, new_state: dict) -> None:
        """重新扫码后的热切换: 停旧线程 → 等完全退出 → 重新落盘新登录态 → 拉起。

        必须 join 之后再 save_state: 停止信号置位前在途的长轮询返回时, 旧线程
        仍会用旧 state dict 整体落盘, 覆盖刚写入的新 bot_token (审查实测)。
        """
        def _do() -> None:
            with self._lock:
                self._stop_event.set()
                t = self._thread
            if t is not None:
                t.join(timeout=self.JOIN_TIMEOUT)
            ilink.save_state(new_state)
            with self._lock:
                self.session_expired = False
                if not self._user_stop and not self.running:
                    self._start_locked()
        threading.Thread(target=_do, name="bot-relogin", daemon=True).start()

    def _run(self, stop_event: threading.Event) -> None:
        sched = None
        try:
            # 延迟导入: apscheduler 只在真正启动 bot 时才需要,
            # webui 模块本身 (及其测试) 不强依赖它
            import main as diary_main
            import scheduler as diary_scheduler

            state = ilink.load_state()
            if not state.get("bot_token"):
                self.last_error = "未登录"
                return
            if not config.USER_ID:
                self.last_error = "未配置 USER_ID (重新扫码登录可自动补齐)"
                return
            # 复刻 main() 的离线提示: 离线超过 12 小时, 首条回复附一次性说明
            diary_main._offline_notice = diary_main._compute_offline_notice(state)
            send_fn = diary_main._make_send_fn(state)
            sched = diary_scheduler.create_scheduler(send_fn)
            sched.start()
            if diary_scheduler.run_catchup(send_fn):
                print("  已补发今日提醒 (启动补偿)")
            result = ilink.run_loop(
                state,
                on_message=diary_main._on_message,
                should_stop=stop_event.is_set,
            )
            # 被动过期才置位; relogin/restart 主动叫停的旧线程即使收到 -14
            # 也不该污染新登录态的状态位
            if result == "session_expired" and not stop_event.is_set():
                self.session_expired = True
        except Exception as e:  # 后台线程绝不静默死亡: 记原因供 status 排查
            self.last_error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            if sched is not None:
                sched.shutdown(wait=False)


RUNNER = BotRunner()

# 当前待轮询的登录二维码 (POST /api/login/start 写, GET /api/login/poll 读)
_login_lock = threading.Lock()
_login_qrcode = ""


# === API 实现 (纯函数风格, 与 HTTP 层解耦, 方便测试) ===

def _mask_user_id(user_id: str) -> str:
    """user_id 打码: 页面只需确认"是这个号", 不需要完整 ID。"""
    if not user_id:
        return ""
    if len(user_id) <= 8:
        return user_id[:2] + "***"
    return f"{user_id[:4]}...{user_id[-4:]}"


def _day_summary(diary_dir: Path, date: str) -> dict:
    """某天的 {date, count, sealed}, 用 mcp_server 纯函数算, 不碰正文。"""
    f = mcp_server.diary_file(diary_dir, date)
    if not f.exists():
        return {"date": date, "count": 0, "sealed": False}
    try:
        text = mcp_server._read_text(f)
    except OSError:
        return {"date": date, "count": 0, "sealed": False}
    return {
        "date": date,
        "count": len(mcp_server.message_blocks(text)),
        "sealed": SEAL_MARKER in text,
    }


def _diary_dir_ok(diary_dir: str) -> bool:
    return bool(diary_dir) and os.path.isabs(diary_dir) and Path(diary_dir).is_dir()


def api_status() -> dict:
    state = ilink.load_state()
    logged_in = bool(state.get("bot_token")) and not RUNNER.session_expired
    user_id = state.get("ilink_user_id", "") or config.USER_ID
    diary_dir = config.DIARY_DIR
    dir_ok = _diary_dir_ok(diary_dir)

    today = {"date": config.today_str(), "count": 0, "sealed": False}
    recent: list = []
    if dir_ok:
        root = Path(diary_dir)
        today = _day_summary(root, config.today_str())
        for date in reversed(mcp_server.list_dates(root)[-7:]):
            recent.append(_day_summary(root, date))

    return {
        "logged_in": logged_in,
        "bot_running": RUNNER.running,
        "bot_stopping": RUNNER.stopping,
        "last_error": RUNNER.last_error,
        "session_expired": RUNNER.session_expired,
        "user_id_masked": _mask_user_id(user_id),
        "diary_dir": diary_dir,
        "diary_dir_ok": dir_ok,
        "ai_key_set": bool(config.AI_API_KEY),
        "remind_hours": [config.REMIND_HOUR_1, config.REMIND_HOUR_2],
        "today": today,
        "recent": recent,
    }


def api_login_start() -> dict:
    global _login_qrcode
    qr = ilink.fetch_login_qr()
    if not qr or not qr.get("qrcode") or not qr.get("qr_img_url"):
        return {"ok": False, "error": "获取二维码失败, 请检查网络后重试"}
    with _login_lock:
        _login_qrcode = qr["qrcode"]
    return {"ok": True, "qr_img_url": qr.get("qr_img_url", "")}


def api_login_poll() -> dict:
    global _login_qrcode
    with _login_lock:
        qrcode = _login_qrcode
    if not qrcode:
        return {"status": "error", "error": "还没有获取二维码, 请先点击开始登录"}

    result = ilink.check_login_status(qrcode)
    status = result.get("status", "error")

    if status == "confirmed":
        state = result.get("state") or {}
        user_id = state.get("ilink_user_id", "")
        if user_id:
            # 消灭手工复制 USER_ID: 写 .env + 同步更新运行中的 config
            envfile.update_env(ENV_PATH, {"USER_ID": user_id})
            config.USER_ID = user_id
            os.environ["USER_ID"] = user_id
        if RUNNER.running:
            # bot 运行中重扫码: 旧线程手里的旧 state dict 会在心跳/cursor 更新时
            # 整体落盘, 覆盖新 token —— 必须停旧线程、等退出、重落盘、再拉起
            RUNNER.relogin_async(state)
        else:
            RUNNER.session_expired = False
        with _login_lock:
            _login_qrcode = ""
        return {"status": "confirmed", "user_id": user_id}

    if status in {"expired", "canceled"}:
        with _login_lock:
            _login_qrcode = ""
    return {"status": status}


def api_config(body: dict) -> dict:
    updates = {}

    diary_dir = body.get("diary_dir")
    if diary_dir is not None:
        diary_dir = str(diary_dir).strip()
        if not diary_dir:
            return {"ok": False, "error": "日记目录不能为空"}
        if "\n" in diary_dir or "\r" in diary_dir:
            # 换行会把 .env 写成多行 → 任意键注入 (审查实测), 一律拒绝
            return {"ok": False, "error": "路径不能包含换行符"}
        if not os.path.isabs(diary_dir):
            return {"ok": False, "error": "请填写绝对路径 (如 /Users/you/Diary 或 D:/Diary)"}
        try:
            p = Path(diary_dir)
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".webui-write-test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            return {"ok": False, "error": f"目录不可写: {e}"}
        updates["DIARY_DIR"] = diary_dir

    ai_key = body.get("ai_api_key")
    if ai_key is not None:
        ai_key = str(ai_key).strip()
        if "\n" in ai_key or "\r" in ai_key:
            return {"ok": False, "error": "密钥不能包含换行符"}
        updates["AI_API_KEY"] = ai_key

    if not updates:
        return {"ok": False, "error": "没有可更新的配置项"}

    try:
        envfile.update_env(ENV_PATH, updates)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"写入 .env 失败: {e}"}

    # 运行时同步: 业务代码读的是 config 模块属性, 不重启进程也立刻生效
    for env_key, attr in (("DIARY_DIR", "DIARY_DIR"), ("AI_API_KEY", "AI_API_KEY")):
        if env_key in updates:
            setattr(config, attr, updates[env_key])
            os.environ[env_key] = updates[env_key]

    if RUNNER.running:
        RUNNER.restart_async()
    return {"ok": True}


def api_folder_pick() -> dict:
    """原生目录选择框, 子进程隔离 (tkinter 在 macOS 子线程直接崩, 见设计文档)。"""
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "选择日记存放目录")'
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False}
        path = (proc.stdout or "").strip()
        if proc.returncode != 0 or not path:
            # osascript 用户取消: exit 1 + stderr 带 -128, 与真实失败区分开
            canceled = "-128" in (proc.stderr or "")
            return {"ok": False, "canceled": canceled}
        return {"ok": True, "path": path.rstrip("/") or "/"}

    if sys.platform == "win32":
        code = (
            "import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "root = tk.Tk()\n"
            "root.withdraw()\n"
            "root.attributes('-topmost', True)\n"
            "print(filedialog.askdirectory())\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False}
        path = (proc.stdout or "").strip()
        if proc.returncode != 0 or not path:
            # tkinter askdirectory 用户取消: 正常退出但输出空串
            return {"ok": False, "canceled": proc.returncode == 0 and not path}
        return {"ok": True, "path": path}

    return {"ok": False, "error": "此平台不支持原生目录选择, 请手动输入路径"}


def api_bot_start() -> dict:
    state = ilink.load_state()
    if not state.get("bot_token") or RUNNER.session_expired:
        return {"ok": False, "error": "还没有绑定微信, 请先扫码登录"}

    diary_dir = config.DIARY_DIR
    if diary_dir and os.path.isabs(diary_dir):
        try:
            Path(diary_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    if not _diary_dir_ok(diary_dir):
        return {"ok": False, "error": "日记目录未配置或不可用, 请先在第 2 步设置"}

    # 兜底: .env 里 USER_ID 缺失但登录态有, 自动补齐 (老用户手工流程的遗留)
    if not config.USER_ID and state.get("ilink_user_id"):
        user_id = state["ilink_user_id"]
        try:
            envfile.update_env(ENV_PATH, {"USER_ID": user_id})
        except OSError:
            pass
        config.USER_ID = user_id
        os.environ["USER_ID"] = user_id

    ok, err = RUNNER.start()
    if not ok:
        return {"ok": False, "error": err or "启动失败"}
    return {"ok": True}


def api_bot_stop() -> dict:
    RUNNER.stop()
    return {"ok": True}


def render_index() -> str:
    """读前端页面并注入本次运行的 token。文件缺失时给占位提示页。"""
    if INDEX_FILE.exists():
        html = INDEX_FILE.read_text(encoding="utf-8")
    else:
        html = PLACEHOLDER_HTML
    return html.replace("{{TOKEN}}", TOKEN)


# === HTTP 层 ===

class WebUIHandler(BaseHTTPRequestHandler):
    server_version = "wechat-diary-webui"

    # --- 基础设施 ---

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 不往控制台刷访问日志 (每 5s 一次 status 轮询会刷屏)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in ALLOWED_HOSTS

    def _auth_ok(self) -> bool:
        supplied = self.headers.get("X-Auth") or ""
        return secrets.compare_digest(
            supplied.encode("utf-8", "replace"), TOKEN.encode("utf-8")
        )

    def _send_json(self, obj: dict, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, text: str, status: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict | None:
        """读 POST body 并解析 JSON。空 body 视为 {}; 畸形 JSON 返回 None。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def _guard_api(self) -> bool:
        """/api/* 公共守卫: X-Auth 校验。失败已发响应, 返回 False。"""
        if not self._auth_ok():
            self._send_json({"ok": False, "error": "unauthorized"}, status=401)
            return False
        return True

    # --- 路由 ---

    def do_GET(self) -> None:
        if not self._host_ok():
            self._send_json({"ok": False, "error": "forbidden host"}, status=403)
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send_html(render_index())
            return
        if path == "/qrcode.js":
            # 登录二维码在前端本地生成 (iLink 给的是网页链接不是图片, 见设计文档)
            if QRCODE_JS.exists():
                data = QRCODE_JS.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        if path.startswith("/api/"):
            if not self._guard_api():
                return
            if path == "/api/status":
                self._send_json(api_status())
                return
            if path == "/api/login/poll":
                self._send_json(api_login_poll())
                return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        if not self._host_ok():
            self._send_json({"ok": False, "error": "forbidden host"}, status=403)
            return
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        if not self._guard_api():
            return

        body = self._read_json_body()
        if body is None:
            self._send_json({"ok": False, "error": "请求体不是合法 JSON"}, status=400)
            return

        if path == "/api/login/start":
            self._send_json(api_login_start())
        elif path == "/api/config":
            self._send_json(api_config(body))
        elif path == "/api/folder/pick":
            self._send_json(api_folder_pick())
        elif path == "/api/bot/start":
            self._send_json(api_bot_start())
        elif path == "/api/bot/stop":
            self._send_json(api_bot_stop())
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)


class WebUIServer(ThreadingHTTPServer):
    daemon_threads = True  # handler 线程不阻塞进程退出


def create_server(port: int | None = None) -> WebUIServer:
    """创建只绑 127.0.0.1 的服务。port=0 分配随机端口 (测试用)。"""
    if port is None:
        try:
            port = int(os.environ.get("WEBUI_PORT", str(DEFAULT_PORT)))
        except ValueError:
            port = DEFAULT_PORT
    return WebUIServer(("127.0.0.1", port), WebUIHandler)


def main() -> int:
    paths.migrate_legacy()
    try:
        server = create_server()
    except OSError as e:
        print(f"  启动失败 (端口被占用?): {e}")
        print("  可设环境变量 WEBUI_PORT 换一个端口, 例如 WEBUI_PORT=9000")
        return 1

    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print("\n=== wechat-diary Web UI ===")
    print(f"  地址: {url}")
    print("  只监听本机 127.0.0.1, 不对外暴露")
    print("  浏览器没有自动打开的话, 手动访问上面的地址")
    print("  Ctrl+C 退出\n")

    # 配置齐备 (登录过 + USER_ID + 日记目录可用) 则自动拉起 bot,
    # 日常使用只需双击启动, 不必每次进页面点按钮
    state = ilink.load_state()
    if state.get("bot_token") and config.USER_ID and _diary_dir_ok(config.DIARY_DIR):
        RUNNER.start()
        print("  配置齐备, bot 已自动启动")

    if "--no-browser" not in sys.argv[1:]:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  bye")
    finally:
        RUNNER.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
