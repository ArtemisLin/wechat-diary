"""webui 的集成测试: 真实起服务于随机端口, monkeypatch ilink 网络函数,
http.client 走一遍 登录流 / config 校验 / token 拒绝 / Host 校验 / 未登录 start 被拒。
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import ilink  # noqa: E402
import webui  # noqa: E402


# === 基础设施 ===

@pytest.fixture
def client(monkeypatch, tmp_path):
    """真实服务起在端口 0 (随机), 环境彻底隔离: .env / config / RUNNER。"""
    monkeypatch.setattr(webui, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(webui, "RUNNER", webui.BotRunner())
    monkeypatch.setattr(webui, "_login_qrcode", "")
    # config 运行时属性与环境变量都交给 monkeypatch, 测试结束自动还原
    monkeypatch.setattr(config, "USER_ID", "")
    monkeypatch.setattr(config, "DIARY_DIR", "")
    monkeypatch.setattr(config, "AI_API_KEY", "")
    monkeypatch.setenv("USER_ID", "")
    monkeypatch.setenv("DIARY_DIR", "")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setattr(ilink, "load_state", lambda: {})

    srv = webui.create_server(port=0)
    # poll_interval 调小: shutdown 等待间隔默认 0.5s, 20 个用例白等 10s
    thread = threading.Thread(
        target=lambda: srv.serve_forever(poll_interval=0.02), daemon=True,
    )
    thread.start()
    yield SimpleNamespace(
        port=srv.server_address[1],
        token=webui.TOKEN,
        env=tmp_path / ".env",
        tmp=tmp_path,
    )
    srv.shutdown()
    srv.server_close()


def request(port, method, path, token=None, body=None, host=None):
    """发一个请求, 返回 (status_code, 解析后的 body)。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {}
    if token is not None:
        headers["X-Auth"] = token
    if host is not None:
        headers["Host"] = host  # 显式传 Host 时 http.client 不再自动生成
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = raw.decode("utf-8", errors="replace")
    return resp.status, parsed


def _make_day(vault: Path, date: str, sealed: bool = False) -> None:
    """按数据契约造一天的日记文件: 段头 + 一条消息, 可选封存尾注。"""
    f = vault / date[:4] / f"{date}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    text = f"# {date}\n\n**21:00**\n\n今天试了新的手冲配方\n"
    if sealed:
        text += "\n---\n\n_(今日封存于 23:00)_\n"
    f.write_text(text, encoding="utf-8")


# === 认证与 Host 校验 ===

def test_api_rejects_missing_token(client):
    status, body = request(client.port, "GET", "/api/status")
    assert status == 401
    assert body["ok"] is False


def test_api_rejects_wrong_token(client):
    status, _ = request(client.port, "GET", "/api/status", token="wrong-token")
    assert status == 401


def test_rejects_foreign_host_header(client):
    """DNS rebinding 防御: Host 不是 127.0.0.1/localhost 一律 403。"""
    status, _ = request(
        client.port, "GET", "/api/status",
        token=client.token, host="evil.example.com",
    )
    assert status == 403
    status, _ = request(client.port, "GET", "/", host="evil.example.com:8765")
    assert status == 403


def test_localhost_host_header_accepted(client):
    status, _ = request(
        client.port, "GET", "/api/status",
        token=client.token, host=f"localhost:{client.port}",
    )
    assert status == 200


def test_index_injects_token_without_auth(client):
    """GET / 不需要 X-Auth (token 就是从这里注入的), {{TOKEN}} 必须被替换。"""
    status, html = request(client.port, "GET", "/")
    assert status == 200
    assert "{{TOKEN}}" not in html
    assert client.token in html


def test_unknown_api_path_404(client):
    status, _ = request(client.port, "GET", "/api/nope", token=client.token)
    assert status == 404
    status, _ = request(client.port, "GET", "/etc/passwd")
    assert status == 404


def test_post_malformed_json_400(client):
    conn = http.client.HTTPConnection("127.0.0.1", client.port, timeout=10)
    conn.request(
        "POST", "/api/config", body=b"{not json",
        headers={"X-Auth": client.token},
    )
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 400


# === /api/status ===

def test_status_not_logged_in(client):
    status, body = request(client.port, "GET", "/api/status", token=client.token)
    assert status == 200
    assert body["logged_in"] is False
    assert body["bot_running"] is False
    assert body["diary_dir_ok"] is False
    assert body["ai_key_set"] is False
    assert body["remind_hours"] == [config.REMIND_HOUR_1, config.REMIND_HOUR_2]
    assert body["today"]["count"] == 0
    assert body["recent"] == []


def test_status_with_diary_and_login(client, monkeypatch):
    full_id = "wxid_abcdefgh1234567890"
    monkeypatch.setattr(
        ilink, "load_state",
        lambda: {"bot_token": "bt", "ilink_user_id": full_id},
    )
    vault = client.tmp / "vault"
    today = config.today_str()
    _make_day(vault, today)
    _make_day(vault, "2020-01-01", sealed=True)
    monkeypatch.setattr(config, "DIARY_DIR", str(vault))

    status, body = request(client.port, "GET", "/api/status", token=client.token)
    assert status == 200
    assert body["logged_in"] is True
    assert body["diary_dir_ok"] is True
    assert body["today"] == {"date": today, "count": 1, "sealed": False}
    assert len(body["recent"]) == 2
    assert body["recent"][0]["date"] == today, "recent 应最新在前"
    assert body["recent"][1] == {"date": "2020-01-01", "count": 1, "sealed": True}
    # 完整 user_id 不泄露, 只给打码版
    assert body["user_id_masked"] != full_id
    assert full_id not in json.dumps(body)


# === 登录流 ===

def test_login_flow_confirmed_writes_env(client, monkeypatch):
    monkeypatch.setattr(
        ilink, "fetch_login_qr",
        lambda: {"qrcode": "qr-1", "qr_img_url": "https://ilink.example/qr.png"},
    )
    status, body = request(
        client.port, "POST", "/api/login/start", token=client.token, body={},
    )
    assert status == 200
    assert body == {"ok": True, "qr_img_url": "https://ilink.example/qr.png"}

    # 第一次轮询: waiting
    seen = []

    def fake_check(qrcode):
        seen.append(qrcode)
        return {"status": "waiting"}

    monkeypatch.setattr(ilink, "check_login_status", fake_check)
    status, body = request(client.port, "GET", "/api/login/poll", token=client.token)
    assert (status, body["status"]) == (200, "waiting")
    assert seen == ["qr-1"], "poll 应该用 start 时拿到的 qrcode 查询"

    # 第二次轮询: confirmed → 写 .env + 更新 config
    user_id = "wxid_confirmed_12345678"
    monkeypatch.setattr(
        ilink, "check_login_status",
        lambda qrcode: {
            "status": "confirmed",
            "state": {"bot_token": "bt", "ilink_user_id": user_id},
        },
    )
    status, body = request(client.port, "GET", "/api/login/poll", token=client.token)
    assert status == 200
    assert body["status"] == "confirmed"
    assert body["user_id"] == user_id
    assert f"USER_ID={user_id}" in client.env.read_text(encoding="utf-8")
    assert config.USER_ID == user_id


def test_login_start_failure(client, monkeypatch):
    monkeypatch.setattr(ilink, "fetch_login_qr", lambda: None)
    status, body = request(
        client.port, "POST", "/api/login/start", token=client.token, body={},
    )
    assert status == 200
    assert body["ok"] is False
    assert "error" in body


def test_login_poll_without_start(client):
    status, body = request(client.port, "GET", "/api/login/poll", token=client.token)
    assert status == 200
    assert body["status"] == "error"


def test_login_poll_expired_clears_qrcode(client, monkeypatch):
    monkeypatch.setattr(
        ilink, "fetch_login_qr", lambda: {"qrcode": "qr-2", "qr_img_url": "u"},
    )
    request(client.port, "POST", "/api/login/start", token=client.token, body={})
    monkeypatch.setattr(ilink, "check_login_status", lambda q: {"status": "expired"})
    status, body = request(client.port, "GET", "/api/login/poll", token=client.token)
    assert body["status"] == "expired"
    # 过期后再 poll 应提示重新开始, 而不是拿旧码继续查
    status, body = request(client.port, "GET", "/api/login/poll", token=client.token)
    assert body["status"] == "error"


# === /api/config ===

def test_config_rejects_relative_path(client):
    status, body = request(
        client.port, "POST", "/api/config",
        token=client.token, body={"diary_dir": "relative/path"},
    )
    assert status == 200
    assert body["ok"] is False
    assert "绝对路径" in body["error"]


def test_config_rejects_empty_update(client):
    status, body = request(
        client.port, "POST", "/api/config", token=client.token, body={},
    )
    assert body["ok"] is False


def test_config_writes_env_updates_runtime_no_key_echo(client):
    vault = client.tmp / "new-vault"
    status, body = request(
        client.port, "POST", "/api/config",
        token=client.token,
        body={"diary_dir": str(vault), "ai_api_key": "sk-secret-123"},
    )
    assert status == 200
    assert body == {"ok": True}, "响应不得回显 AI key"
    assert vault.is_dir(), "目录应被自动创建"
    text = client.env.read_text(encoding="utf-8")
    assert f"DIARY_DIR={vault}" in text
    assert "AI_API_KEY=sk-secret-123" in text
    assert config.DIARY_DIR == str(vault)
    assert config.AI_API_KEY == "sk-secret-123"
    # 之后的 status 也只给布尔, 不泄露 key
    status, body = request(client.port, "GET", "/api/status", token=client.token)
    assert body["ai_key_set"] is True
    assert "sk-secret-123" not in json.dumps(body)


# === bot 启停 ===

def test_bot_start_rejected_when_not_logged_in(client):
    status, body = request(
        client.port, "POST", "/api/bot/start", token=client.token, body={},
    )
    assert status == 200
    assert body["ok"] is False
    assert "error" in body


def test_bot_start_rejected_without_diary_dir(client, monkeypatch):
    monkeypatch.setattr(
        ilink, "load_state", lambda: {"bot_token": "bt", "ilink_user_id": "u1"},
    )
    status, body = request(
        client.port, "POST", "/api/bot/start", token=client.token, body={},
    )
    assert body["ok"] is False
    assert "目录" in body["error"]


def test_bot_stop_always_ok(client):
    status, body = request(
        client.port, "POST", "/api/bot/stop", token=client.token, body={},
    )
    assert (status, body) == (200, {"ok": True})


# === run_loop should_stop ===

def test_run_loop_stops_immediately():
    result = ilink.run_loop({}, on_message=None, should_stop=lambda: True)
    assert result == "stopped"


def test_run_loop_stops_after_iterations(monkeypatch):
    """打桩 _api_request: 跑两轮空响应后 should_stop 变 True, 优雅退出。"""
    calls = []

    def fake_api(method, path, body=None, headers=None, timeout=10):
        calls.append(path)
        return {"get_updates_buf": "", "msgs": []}

    monkeypatch.setattr(ilink, "_api_request", fake_api)
    monkeypatch.setattr(ilink, "save_state", lambda state: None)

    checks = []

    def should_stop():
        checks.append(1)
        return len(checks) > 2

    state = {"bot_token": "bt", "cursor": ""}
    result = ilink.run_loop(state, on_message=None, should_stop=should_stop)
    assert result == "stopped"
    assert len(calls) == 2, "停止前应恰好轮询两次"


# === 对抗审查后的回归测试 (BotRunner 竞态 / .env 注入 / 状态字段) ===

def _fake_run(runner, started_evt, hold=True):
    """替身 _run: 置 started_evt 后等停止信号, 模拟长轮询线程。"""
    def run(stop_event):
        started_evt.set()
        if hold:
            stop_event.wait(timeout=10)
    return run


def _wait(cond, timeout=5.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_runner_start_during_stopping_window_restarts(monkeypatch):
    """stop 后立刻 start (旧线程还没退出): 不能吞掉, 最终必须真的在跑。"""
    r = webui.BotRunner()
    started = threading.Event()
    monkeypatch.setattr(r, "_run", _fake_run(r, started))
    r.start()
    assert _wait(lambda: r.running)
    first_thread = r._thread

    started.clear()
    r.stop()  # 置位但旧线程可能还活着 (fake _run 正 wait)
    ok, _ = r.start()  # 停止窗口内点启动
    assert ok
    # 最终新线程真的跑起来 (旧实现这里静默死亡)
    assert _wait(lambda: r.running and r._thread is not first_thread and started.is_set())


def test_runner_stop_during_restart_window_not_swallowed(monkeypatch):
    """restart_async 的 join 窗口内用户点停止: 停止意图必须生效。"""
    r = webui.BotRunner()
    started = threading.Event()
    monkeypatch.setattr(r, "_run", _fake_run(r, started))
    r.start()
    assert _wait(lambda: r.running)

    r.restart_async()
    r.stop()  # 紧跟在重启后面的用户停止
    # 最终必须停着 (旧实现: 重启把停止吞掉, bot 继续跑)
    import time
    time.sleep(1.0)
    assert _wait(lambda: not r.running)
    time.sleep(0.5)
    assert not r.running


def test_config_rejects_newline_injection(client):
    evil = "/tmp/x\nAI_API_KEY=evil"
    status, resp = request(client.port, "POST", "/api/config", token=client.token,
                           body={"diary_dir": evil})
    assert status == 200 and resp["ok"] is False
    assert "换行" in resp["error"]
    _, resp2 = request(client.port, "POST", "/api/config", token=client.token,
                       body={"diary_dir": "/tmp", "ai_api_key": "sk\nUSER_ID=x"})
    assert resp2["ok"] is False


def test_envfile_format_value_rejects_control_chars():
    import envfile
    with pytest.raises(ValueError):
        envfile.format_value("a\nb")
    with pytest.raises(ValueError):
        envfile.format_value("a\rb")


def test_status_exposes_stopping_and_last_error(client):
    webui.RUNNER.last_error = "SomeError: boom"
    _, resp = request(client.port, "GET", "/api/status", token=client.token)
    assert resp["last_error"] == "SomeError: boom"
    assert resp["bot_stopping"] is False


def test_login_start_requires_qr_img_url(client, monkeypatch):
    monkeypatch.setattr(ilink, "fetch_login_qr",
                        lambda: {"qrcode": "abc", "qr_img_url": ""})
    _, resp = request(client.port, "POST", "/api/login/start", token=client.token, body={})
    assert resp["ok"] is False
