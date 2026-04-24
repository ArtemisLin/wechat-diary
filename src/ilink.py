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
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

# Load .env when ilink.py is run directly.
import config  # noqa: F401
import paths

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


BASE_URL = "https://ilinkai.weixin.qq.com"
STATE_FILE = paths.ILINK_STATE
LOG_FILE = paths.ILINK_LOG
CHANNEL_VERSION = os.environ.get("ILINK_CHANNEL_VERSION", "1.0.2")
PROXY_MODE = (os.environ.get("ILINK_PROXY_MODE", "auto").strip().lower() or "auto")
if PROXY_MODE not in {"auto", "direct", "proxy"}:
    PROXY_MODE = "auto"


def _log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}\n"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


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

    try:
        while time.time() - start < 300:
            poll_count += 1
            elapsed = int(time.time() - start)
            resp = _api_request(
                "GET",
                f"/ilink/bot/get_qrcode_status?qrcode={qrcode}",
                headers=headers,
                timeout=35,
            )
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
        print("\n  登录流程被本地中断")
        _log("login interrupted by keyboard")
        return None

    print("  等待超时(5分钟)，未收到 confirmed")
    _log("login timeout waiting for confirmed")
    return None


def send_message(state: dict, to_user_id: str, context_token: str, text: str) -> bool:
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
    resp = _api_request(
        "POST",
        "/ilink/bot/sendmessage",
        body=body,
        headers=_make_headers(state["bot_token"]),
    )
    if resp is not None and "error" not in resp and "timeout" not in resp and "_ret_error" not in resp:
        _log(f"send ok to={to_user_id[:20]} text={text[:80]!r}")
        return True
    print(f"  发送失败: {resp}")
    _log(f"send failed to={to_user_id[:20]} text={text[:80]!r} resp={resp}")
    return False


def _is_token_fresh(info: dict, max_hours: int = 20) -> bool:
    cached_time = info.get("time")
    if not cached_time:
        return False
    try:
        cached_dt = datetime.strptime(cached_time, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False
    return datetime.now() - cached_dt < timedelta(hours=max_hours)


def send_to_user(state: dict, user_id: str, text: str) -> bool:
    cached = state.get("cached_tokens", {}).get(user_id)
    if not cached or not _is_token_fresh(cached):
        print(f"  主动发送→{user_id[:15]}: 跳过(无有效 context_token)")
        return False
    ok = send_message(state, user_id, cached["context_token"], text)
    print(f"  主动发送→{user_id[:15]}: {'OK' if ok else 'FAIL'}")
    return ok


def run_loop(state: dict, on_message) -> str:
    cursor = state.get("cursor", "")
    processed = set()
    timeout_streak = 0
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

            if resp.get("timeout"):
                timeout_streak += 1
                if timeout_streak == 1:
                    detail = resp.get("detail", "")
                    suffix = f": {detail}" if detail else ""
                    print(f"  iLink 连接超时/中断，正在重试{suffix}")
                elif timeout_streak % 10 == 0:
                    print(f"  iLink 连接仍未恢复(连续 {timeout_streak} 次)，继续重试...")
                time.sleep(1)
                continue

            if timeout_streak:
                print(f"  iLink 连接已恢复(之前连续超时 {timeout_streak} 次)")
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
    if probe in {"ok", "network"}:
        return 0
    return 1


def _cli() -> int:
    paths.migrate_legacy()
    state = load_state()
    if len(sys.argv) < 2:
        print("用法: python ilink.py <login|status|send TEXT>")
        return 1

    cmd = sys.argv[1]
    if cmd == "login":
        return 0 if login() else 1
    if cmd == "status":
        return _status_cli(state)
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
