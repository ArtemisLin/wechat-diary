"""Minimal iLink client for wechat-diary.

Responsibilities:
- QR login
- long-poll receive loop
- send text messages
- cache context_token for proactive reminders
"""
from __future__ import annotations

import base64
import io
import json
import os
import random
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

# Load .env when ilink.py is run directly.
import config  # noqa: F401
import logger as app_logger
import paths

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


BASE_URL = "https://ilinkai.weixin.qq.com"

# Phase Debug: 实现 README "三重保险" 强制 iLink API 直连
# 即使 Clash TUN 模式劫持流量, 至少保证 Python urllib 层面不走 proxy。
# (注: TUN 模式 OS-level 劫持仍无法绕过, 用户需在 Clash 添加直连规则)
for _proxy_env in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_env, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

STATE_FILE = paths.ILINK_STATE
LOG_FILE = paths.ILINK_LOG
_LOG = app_logger.get_logger("ilink", LOG_FILE)
_state_lock = threading.Lock()

# 长轮询超时降噪阈值: 协议本身每隔几秒就会 timeout 重连, 视为正常 keep-alive。
# 仅当连续超过 NOISE_THRESHOLD 次仍超时, 才视为真实网络故障并告警。
LONGPOLL_NOISE_THRESHOLD = 5
LONGPOLL_OUTAGE_INTERVAL = 30
HEARTBEAT_INTERVAL_S = 300  # run_loop 存活时间戳落盘间隔 (v2 C.1 离线检测用)
CHANNEL_VERSION = os.environ.get("ILINK_CHANNEL_VERSION", "1.0.2")
PROXY_MODE = (os.environ.get("ILINK_PROXY_MODE", "auto").strip().lower() or "auto")
if PROXY_MODE not in {"auto", "direct", "proxy"}:
    PROXY_MODE = "auto"


def _log(message: str) -> None:
    _LOG.info(message)


def _normalize_proxy_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        return f"http://{raw}"
    return raw


def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _detect_proxy_url() -> str:
    for key in (
        "ILINK_PROXY_URL",
        "NETWORK_PROXY_URL",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "https_proxy",
        "http_proxy",
    ):
        url = _normalize_proxy_url(os.environ.get(key, ""))
        if url:
            return url
    for port in (7890, 7897, 7891):
        if _port_open("127.0.0.1", port):
            return f"http://127.0.0.1:{port}"
    return ""


PROXY_URL = _detect_proxy_url()
_DIRECT_OPENER = build_opener(ProxyHandler({}))
_PROXY_OPENER = (
    build_opener(ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}))
    if PROXY_URL
    else None
)
_ACTIVE_TRANSPORT = "proxy" if (_PROXY_OPENER and PROXY_MODE in {"auto", "proxy"}) else "direct"


def _proxy_status_text() -> str:
    if PROXY_MODE == "proxy" and not _PROXY_OPENER:
        return "proxy(requested but unavailable)"
    if PROXY_MODE == "proxy":
        return f"proxy ({PROXY_URL})"
    if PROXY_MODE == "direct":
        return "direct"
    if _PROXY_OPENER:
        return f"auto ({PROXY_URL})"
    return "auto (direct only)"


def _base_info() -> dict:
    return {"channel_version": CHANNEL_VERSION}


def _random_uin() -> str:
    return base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()


def _make_headers(bot_token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if bot_token:
        headers["AuthorizationType"] = "ilink_bot_token"
        headers["Authorization"] = f"Bearer {bot_token}"
        headers["X-WECHAT-UIN"] = _random_uin()
    return headers


def _request_once(
    opener,
    transport: str,
    method: str,
    path: str,
    body: dict | None,
    headers: dict | None,
    timeout: int,
) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            result = json.loads(raw.decode("utf-8")) if raw else {}
            code = result.get("ret")
            if code is None:
                code = result.get("errcode")
            if code not in (None, 0):
                result["_ret_error"] = code
                print(f"  API code={code}: {path}")
                _log(
                    f"{transport} api_code path={path} code={code} "
                    f"errmsg={str(result.get('errmsg', ''))[:120]}"
                )
            return result
    except HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"  HTTP {e.code}: {body_text[:200]}")
        _log(f"{transport} http_error path={path} code={e.code} body={body_text[:200]}")
        return {"error": e.code, "detail": body_text[:200]}
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        detail = str(e)[:200]
        _log(f"{transport} timeout path={path} detail={detail}")
        return {"timeout": True, "detail": detail}


def _api_request(
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict | None = None,
    timeout: int = 10,
) -> dict:
    global _ACTIVE_TRANSPORT

    if PROXY_MODE == "proxy":
        transports = [("proxy", _PROXY_OPENER)] if _PROXY_OPENER else [("direct", _DIRECT_OPENER)]
    elif PROXY_MODE == "direct" or not _PROXY_OPENER:
        transports = [("direct", _DIRECT_OPENER)]
    elif _ACTIVE_TRANSPORT == "proxy":
        transports = [("proxy", _PROXY_OPENER), ("direct", _DIRECT_OPENER)]
    else:
        transports = [("direct", _DIRECT_OPENER), ("proxy", _PROXY_OPENER)]

    last_result = {"timeout": True, "detail": "no transport available"}
    for idx, (transport, opener) in enumerate(transports):
        if opener is None:
            continue
        result = _request_once(opener, transport, method, path, body, headers, timeout)
        if "error" not in result and "timeout" not in result:
            _ACTIVE_TRANSPORT = transport
            return result
        last_result = result
        if idx + 1 < len(transports):
            fallback_to = transports[idx + 1][0]
            _ACTIVE_TRANSPORT = fallback_to
            _log(f"retry via {fallback_to} path={path} proxy={PROXY_URL}")
    return last_result


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  状态文件损坏或不可读: {e}")
        _log(f"load_state failed: {e}")
        return {}


def save_state(state: dict) -> None:
    with _state_lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_FILE)


def probe_session(state: dict) -> str:
    if not state.get("bot_token"):
        return "no_token"
    body = {
        "get_updates_buf": state.get("cursor", ""),
        "base_info": _base_info(),
        "longpolling_timeout_ms": 100,
    }
    resp = _api_request(
        "POST",
        "/ilink/bot/getupdates",
        body=body,
        headers=_make_headers(state["bot_token"]),
        timeout=35,
    )
    if resp.get("timeout") or "error" in resp:
        return "network"
    code = resp.get("_ret_error") or resp.get("ret") or resp.get("errcode") or 0
    if code == -14:
        return "expired"
    if code:
        return f"api_error:{code}"
    return "ok"


def login() -> dict | None:
    print("\n=== 获取 iLink 登录二维码 ===")
    resp = _api_request("GET", "/ilink/bot/get_bot_qrcode?bot_type=3")
    if (
        not resp
        or "error" in resp
        or resp.get("timeout")
        or resp.get("_ret_error")
        or not resp.get("qrcode")
    ):
        print(f"  获取失败: {resp}")
        return None

    qrcode = resp.get("qrcode", "")
    qr_url = resp.get("qrcode_img_content", "")
    print(f"  二维码链接: {qr_url}")
    print("\n  >>> 用微信扫描以上链接里的二维码，扫码后在微信里点“确认登录” <<<\n")

    headers = {"iLink-App-ClientVersion": "1"}
    start = time.time()
    poll_count = 0
    last_status = None
    consecutive_ki = 0  # 连续 SSL 中断 (Windows quirk) 次数, ≥5 才真退出

    try:
        while time.time() - start < 300:
            poll_count += 1
            elapsed = int(time.time() - start)
            try:
                resp = _api_request(
                    "GET",
                    f"/ilink/bot/get_qrcode_status?qrcode={qrcode}",
                    headers=headers,
                    timeout=35,
                )
            except KeyboardInterrupt:
                # Phase Debug: SSL recv 被 OS 网络栈打断, Python 在 Windows 下
                # 误把它翻译成 KeyboardInterrupt (实际不是用户按 Ctrl+C)。
                # 当 timeout 处理: 等 1 秒重试, 连续 5 次才真退出。
                consecutive_ki += 1
                if consecutive_ki >= 5:
                    print(f"\n  连续 {consecutive_ki} 次 SSL 中断, 退出登录流程")
                    raise
                _log(
                    f"poll#{poll_count} ssl_interrupted "
                    f"(consecutive_ki={consecutive_ki}, treated as network glitch)"
                )
                time.sleep(1)
                continue
            consecutive_ki = 0  # 任何 _api_request 正常返回都 reset
            if not resp:
                time.sleep(1)
                continue
            if resp.get("timeout"):
                if poll_count % 5 == 0:
                    print(f"  [{elapsed}s] poll#{poll_count}: 二维码状态查询超时，继续等待...")
                continue
            if "error" in resp:
                print(f"  [{elapsed}s] poll#{poll_count}: HTTP 错误 {resp}")
                time.sleep(1)
                continue
            if "_ret_error" in resp:
                print(f"  [{elapsed}s] poll#{poll_count}: API 异常 {resp}")
                _log(f"login poll api error: {resp}")
                time.sleep(1)
                continue

            status = resp.get("status", "")
            if status != last_status:
                print(f"  [{elapsed}s] poll#{poll_count}: 状态 {status!r}")
                _log(f"login status={status!r} poll={poll_count}")
                last_status = status
            elif poll_count % 10 == 0:
                print(f"  [{elapsed}s] poll#{poll_count}: 仍是 {status!r}")

            if status == "confirmed":
                state = {
                    "bot_token": resp.get("bot_token", ""),
                    "bot_id": resp.get("ilink_bot_id", ""),
                    "ilink_user_id": resp.get("ilink_user_id", ""),
                    "login_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "cursor": "",
                    "cached_tokens": {},
                }
                save_state(state)
                _log(
                    "login confirmed "
                    f"bot_id={state.get('bot_id', '')} "
                    f"user_id={state.get('ilink_user_id', '')}"
                )
                print(f"\n  登录成功! ilink_user_id={state.get('ilink_user_id', '')}")
                print("  如果 .env 里的 USER_ID 还是空的，把上面这一串复制进去。")
                return state
            if status == "expired":
                print("  二维码已过期，请重新扫码")
                _log("login expired")
                return None
            if status in {"cancel", "canceled", "cancelled"}:
                print("  微信端已取消本次登录，请重新扫码")
                _log("login canceled by client")
                return None
            time.sleep(1)
    except KeyboardInterrupt:
        # 调试: 打印完整 traceback, 看 SIGINT 是从哪个 syscall 抛的
        # (谷雨实测: 没按 Ctrl+C 但仍触发, 怀疑 cmd / Windows / urllib 信号 quirk)
        print("\n  登录流程被本地中断 [DEBUG: traceback ↓]")
        traceback.print_exc()
        _log(f"login interrupted by keyboard:\n{traceback.format_exc()}")
        return None
    except BaseException as e:
        # 顺带 catch 其他基础异常 (SystemExit/GeneratorExit 等), 防止漏过
        print(f"\n  登录意外退出: {type(e).__name__}: {e}")
        traceback.print_exc()
        _log(f"login unexpected exit ({type(e).__name__}): {e}\n{traceback.format_exc()}")
        return None

    print("  等待超时(5分钟)，未收到 confirmed")
    _log("login timeout waiting for confirmed")
    return None


def send_message_raw(state: dict, to_user_id: str, context_token: str, text: str) -> dict:
    """发消息, 返回服务端原始响应 (供上层做返回码分流/记录)。"""
    client_id = f"diary:{int(time.time() * 1000)}-{random.randint(10000000, 99999999):08x}"
    body = {
        "msg": {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        },
        "base_info": _base_info(),
    }
    return _api_request(
        "POST",
        "/ilink/bot/sendmessage",
        body=body,
        headers=_make_headers(state["bot_token"]),
    )


def resp_ok(resp: dict | None) -> bool:
    """响应是否算成功。"""
    if not resp:
        return False
    return "error" not in resp and "timeout" not in resp and "_ret_error" not in resp


def resp_code(resp: dict | None) -> object:
    """从响应里抽出返回码 (ret / errcode / HTTP error / timeout)。"""
    if not resp:
        return "empty"
    if resp.get("timeout"):
        return "timeout"
    if "error" in resp:
        return f"http_{resp['error']}"
    code = resp.get("_ret_error")
    if code is None:
        code = resp.get("ret")
    if code is None:
        code = resp.get("errcode")
    return 0 if code is None else code


def send_message(state: dict, to_user_id: str, context_token: str, text: str) -> bool:
    resp = send_message_raw(state, to_user_id, context_token, text)
    if resp_ok(resp):
        _log(f"send ok to={to_user_id[:20]} text={text[:80]!r}")
        return True
    print(f"  发送失败: {resp}")
    _log(f"send failed to={to_user_id[:20]} text={text[:80]!r} resp={resp}")
    return False


def token_age_hours(info: dict | None) -> float | None:
    """缓存的 context_token 有多老(小时)。无缓存/时间戳坏了返回 None。

    注: 这个函数**只用于记录和展示**, 绝不用来决定发不发 —— 见 send_to_user。
    """
    if not info:
        return None
    cached_time = info.get("time")
    if not cached_time:
        return None
    try:
        cached_dt = datetime.strptime(cached_time, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    return (datetime.now() - cached_dt).total_seconds() / 3600


def _probe_log(line: str) -> None:
    """往 data/logs/remind-probe.log 追加一行人可读记录。写失败不影响主流程。"""
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(paths.REMIND_PROBE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{stamp}  {line}\n")
    except OSError:
        pass


def send_to_user(state: dict, user_id: str, text: str, use_token: bool = True) -> bool:
    """主动给用户发消息(提醒等)。**永远真的去发, 不做本地预判。**

    2026-08 修正 —— 原实现有个 `_is_token_fresh(max_hours=20)`, token 超过 20 小时
    就直接 print 跳过、根本不调 sendmessage。那个 20 小时是本地拍脑袋的数字:

      腾讯官方实现 (@tencent-weixin/openclaw-weixin, src/messaging/inbound.ts) 的
      contextToken store 是个纯 Map<string,string> —— 没有时间戳、没有 TTL、没有
      过期逻辑, 而且特意落盘以便 "survive gateway restarts"; 没有 token 时官方
      (src/channel.ts:123) 只 warn 一句然后照发。

    所以策略改成和官方一致: 有什么 token 就用什么, 没有也发, 失败了按返回码记录。
    每次发送往 data/logs/remind-probe.log 记一行, 攒真实数据回答"到底多久失效"。

    use_token=False 用于对照实验: 故意不带 context_token 发, 看服务端认不认。
    """
    cached = state.get("cached_tokens", {}).get(user_id) or {}
    context_token = cached.get("context_token", "") if use_token else ""
    age_h = token_age_hours(cached)
    age_label = f"{age_h:.1f}h" if age_h is not None else "none"

    resp = send_message_raw(state, user_id, context_token, text)
    ok = resp_ok(resp)
    code = resp_code(resp)

    _probe_log(
        f"{'OK  ' if ok else 'FAIL'} "
        f"token_age={age_label} has_token={bool(context_token)} "
        f"code={code} to={user_id[:15]} text={text[:40]!r} resp={str(resp)[:200]}"
    )
    print(f"  主动发送→{user_id[:15]}: {'OK' if ok else 'FAIL'} (token 年龄 {age_label}, code={code})")
    if not ok:
        print(f"    服务端响应: {resp}")
    return ok


def run_loop(state: dict, on_message) -> str:
    cursor = state.get("cursor", "")
    processed = set()
    timeout_streak = 0
    last_beat = 0.0
    print("  等待消息...(Ctrl+C 退出)\n")

    try:
        while True:
            body = {
                "get_updates_buf": cursor,
                "base_info": _base_info(),
                "longpolling_timeout_ms": 3000,
            }
            resp = _api_request(
                "POST",
                "/ilink/bot/getupdates",
                body=body,
                headers=_make_headers(state["bot_token"]),
                timeout=35,
            )
            if not resp:
                time.sleep(1)
                continue

            # 存活心跳: 任何成功响应(含 timeout keep-alive)都证明进程在收消息
            now_ts = time.time()
            if now_ts - last_beat > HEARTBEAT_INTERVAL_S:
                state["last_alive_ts"] = int(now_ts)
                save_state(state)
                last_beat = now_ts

            if resp.get("timeout"):
                timeout_streak += 1
                # 长轮询协议下少量 timeout 是正常 keep-alive, 不打印; 仅当连续
                # 多次失败才告警, 避免控制台被刷屏。底层错误细节已通过 _api_request
                # 的 _log 记入 ilink.log, 排查时看日志即可。
                if timeout_streak == LONGPOLL_NOISE_THRESHOLD:
                    detail = resp.get("detail", "")
                    suffix = f": {detail}" if detail else ""
                    print(f"  iLink 网络似乎不稳, 仍在重试{suffix}")
                elif timeout_streak > LONGPOLL_NOISE_THRESHOLD and \
                        timeout_streak % LONGPOLL_OUTAGE_INTERVAL == 0:
                    print(f"  iLink 已重试 {timeout_streak} 次, 仍在尝试...")
                time.sleep(1)
                continue

            if timeout_streak:
                if timeout_streak >= LONGPOLL_NOISE_THRESHOLD:
                    print(f"  iLink 连接已恢复(之前连续 {timeout_streak} 次)")
                timeout_streak = 0

            if "error" in resp or "_ret_error" in resp:
                code = resp.get("_ret_error") or resp.get("ret") or resp.get("errcode")
                if code == -14:
                    print("  Session 过期，需要重新登录")
                    _log("session expired")
                    return "session_expired"
                print(f"  getupdates 异常响应: {resp}")
                _log(f"getupdates abnormal resp={resp}")
                time.sleep(2)
                continue

            new_cursor = resp.get("get_updates_buf", cursor)
            if new_cursor != cursor:
                cursor = new_cursor
                state["cursor"] = cursor
                save_state(state)
                _log(f"cursor updated len={len(cursor)}")

            for msg in resp.get("msgs", []):
                seq = msg.get("seq") or msg.get("message_id", "")
                if seq and seq in processed:
                    continue
                if seq:
                    processed.add(seq)
                    if len(processed) > 200:
                        processed.clear()

                user_id = msg.get("from_user_id", "")
                context_token = msg.get("context_token", "")
                state.setdefault("cached_tokens", {})[user_id] = {
                    "context_token": context_token,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_state(state)

                for item in msg.get("item_list", []):
                    item_type = item.get("type", 0)
                    text = None
                    is_voice = False

                    if item_type == 1:
                        text = item.get("text_item", {}).get("text", "")
                    elif item_type == 3:
                        text = item.get("voice_item", {}).get("text", "")
                        is_voice = True
                        if not text:
                            send_message(state, user_id, context_token, "语音没听清呢，试试发文字？")
                            continue

                    if not text:
                        continue

                    print(f"\n  收到{'(语音)' if is_voice else ''}: {text[:50]}")
                    _log(f"inbound text from={user_id[:20]} voice={is_voice} text={text[:120]!r}")

                    try:
                        reply = on_message(user_id, text, is_voice)
                    except Exception as e:
                        print(f"  处理异常: {e}")
                        traceback.print_exc()
                        _log(f"handler exception: {e}")
                        reply = "出了点问题，再试一次？"

                    if reply:
                        ok = send_message(state, user_id, context_token, reply)
                        status = "OK" if ok else "FAIL"
                        print(f"  回复: {reply[:60]}{'...' if len(reply) > 60 else ''} {status}")
                        _log(f"reply {'ok' if ok else 'failed'} to={user_id[:20]} text={reply[:120]!r}")
    except KeyboardInterrupt:
        print("\n\n  bye")
        return "keyboard_interrupt"


def _status_to_exit_code(probe: str) -> int:
    """status 命令的 exit code 映射:
    0 = ok (网络通且 session 健康)
    2 = network (网络降级, 但 session 仍可沿用启动)
    1 = 其他 (session 失效, 需重新登录)
    """
    if probe == "ok":
        return 0
    if probe == "network":
        return 2
    return 1


def _status_cli(state: dict) -> int:
    if not state.get("bot_token"):
        print("  未登录，运行: python ilink.py login")
        return 1
    probe = probe_session(state)
    print(f"  本地 state: {state.get('login_time', '?')}")
    print(f"  bot_id: {state.get('bot_id', '?')}")
    print(f"  ilink_user_id: {state.get('ilink_user_id', '?')}")
    print(f"  缓存 token: {len(state.get('cached_tokens', {}))} 个用户")
    print(f"  channel_version: {CHANNEL_VERSION}")
    print(f"  proxy_mode: {_proxy_status_text()}")
    print(f"  active_transport: {_ACTIVE_TRANSPORT}")
    print(f"  探活: {probe}")
    return _status_to_exit_code(probe)


PING_USAGE = """用法: python ilink.py ping [--no-token] [自定义文字]

  立刻尝试主动给自己发一条消息, 打印 token 年龄和服务端完整响应。
  微信上收没收到, 就是最直接的答案。

  --no-token   对照实验: 故意不带 context_token 发, 看服务端认不认
  --log        只看历史探针记录, 不发新的

  结果同时追加到 data/logs/remind-probe.log"""


def _show_probe_log(n: int = 15) -> None:
    if not paths.REMIND_PROBE_LOG.exists():
        print("  (还没有探针记录)")
        return
    try:
        lines = paths.REMIND_PROBE_LOG.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"  读取探针日志失败: {e}")
        return
    print(f"\n  === 最近 {min(n, len(lines))} 条探针记录 (共 {len(lines)} 条) ===")
    for line in lines[-n:]:
        print(f"  {line}")


def _ping_cli(state: dict) -> int:
    """主动推送探针: 到点就发, 看服务端到底认不认。"""
    args = sys.argv[2:]
    if "--log" in args:
        _show_probe_log()
        return 0

    use_token = "--no-token" not in args
    custom = " ".join(a for a in args if not a.startswith("--")).strip()

    if not state.get("bot_token"):
        print("  未登录，先运行: python ilink.py login")
        return 1
    user_id = state.get("ilink_user_id", "")
    if not user_id:
        print("  state 里没有 ilink_user_id，请先重新登录")
        return 1

    cached = state.get("cached_tokens", {}).get(user_id) or {}
    age_h = token_age_hours(cached)
    age_label = f"{age_h:.1f} 小时前" if age_h is not None else "无缓存"

    print(f"\n  === 主动推送探针 ===")
    print(f"  上次收到你的消息: {cached.get('time', '(无记录)')}  ({age_label})")
    print(f"  context_token: {'带上' if use_token and cached.get('context_token') else '不带 (对照实验)' if not use_token else '无缓存, 空着发'}")

    text = custom or f"🔔 提醒探针 {config.hhmm_str()} (token 年龄 {age_label})"
    print(f"  发送内容: {text}")
    print("  → 发送中...\n")

    ok = send_to_user(state, user_id, text, use_token=use_token)

    print()
    if ok:
        print("  ✅ 服务端接受了。**去微信看一眼真的收到没有** —— 服务端返回 0 不等于用户看得见。")
    else:
        print("  ❌ 服务端拒绝了。上面的响应就是原因, 记进 remind-probe.log 了。")
    _show_probe_log(8)
    return 0 if ok else 1


def _cli() -> int:
    paths.migrate_legacy()
    state = load_state()
    if len(sys.argv) < 2:
        print("用法: python ilink.py <login|status|send TEXT|ping>")
        print()
        print(PING_USAGE)
        return 1

    cmd = sys.argv[1]
    if cmd == "login":
        return 0 if login() else 1
    if cmd == "status":
        return _status_cli(state)
    if cmd == "ping":
        return _ping_cli(state)
    if cmd == "send":
        if len(sys.argv) < 3:
            print("用法: python ilink.py send <TEXT>")
            return 1
        user_id = state.get("ilink_user_id", "")
        if not user_id:
            print("  state 里没有 ilink_user_id，请先重新登录")
            return 1
        text = " ".join(sys.argv[2:]).strip()
        return 0 if send_to_user(state, user_id, text) else 1

    print(f"  未知命令: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
