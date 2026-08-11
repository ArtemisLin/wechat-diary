#!/bin/bash
# 把 wechat-diary Web UI 注册成 macOS 用户级常驻服务 (launchd)。
#
# 解决的问题不是"开机自启"(这台机器几乎不重启), 而是 KeepAlive:
# 进程被误关 / 意外退出后, launchd 会自动把它拉回来。
# 2026-08-10 深夜进程被关掉, 一整晚微信消息没人接, 页面第二天还写着"运行中"
# —— 就是这个场景。
#
# 用法:
#     bash scripts/install-launchd-mac.sh              # 安装并立即启动
#     bash scripts/install-launchd-mac.sh --uninstall  # 卸载 (彻底停掉)
#     PYTHON=/opt/homebrew/bin/python3 bash scripts/install-launchd-mac.sh
#
# 装完之后:
#     打开 http://127.0.0.1:8765/
#     看日志:   tail -f data/logs/webui.out.log
#     手动重启: launchctl kickstart -k gui/$(id -u)/com.wechat-diary.webui
#     临时停掉: bash scripts/install-launchd-mac.sh --uninstall
#               (面板上的"停止"只停 bot 线程, 服务进程还在, 这是故意的)
set -euo pipefail

LABEL="com.wechat-diary.webui"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "这个脚本只用于 macOS。" >&2
  exit 1
fi

unload_if_present() {
  # 已注册就先卸掉, 让安装可以重复执行 (bootout 未注册时会报错, 忽略)
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
}

if [ "${1:-}" = "--uninstall" ]; then
  unload_if_present
  rm -f "$PLIST"
  echo "已卸载 $LABEL (服务已停止, 开机不再自启)。"
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-/usr/bin/python3}"
ENTRY="$ROOT/src/webui.py"

# 用源码运行, 不用 dist/ 里的打包版: 打包版把 .env 和 data/ 认在 exe 旁边,
# 指过去等于一个全新的空实例 (未登录、无日记目录)。
[ -f "$ENTRY" ] || { echo "找不到 $ENTRY" >&2; exit 1; }
[ -x "$PY" ] || { echo "找不到 Python: $PY (可用 PYTHON=... 指定)" >&2; exit 1; }
"$PY" -c "import apscheduler" 2>/dev/null || {
  echo "这个 Python 缺 apscheduler: $PY" >&2
  echo "先装: $PY -m pip install --user -r requirements.txt" >&2
  exit 1
}

# 解析到真实解释器再写进 plist。/usr/bin/python3 只是 xcode-select 跳板,
# 它会 exec 掉 CommandLineTools 里的真身 —— macOS 的 TCC (完全磁盘访问)
# 认的是真身那个可执行文件。plist 里写跳板的话, 用户在系统设置里授权谁都
# 对不上, 日记目录 (~/Documents 受保护) 依旧读不了。
PY_REAL="$("$PY" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
[ -x "$PY_REAL" ] || PY_REAL="$PY"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/data/logs"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY_REAL</string>
        <string>$ENTRY</string>
        <string>--no-browser</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$ROOT</string>
    <key>RunAtLoad</key>
    <true/>
    <!-- 进程无论怎么退出 (被 kill / Ctrl+C / 自己崩) 都拉回来 -->
    <key>KeepAlive</key>
    <true/>
    <!-- 端口被占之类的启动失败会立刻退出; 30s 间隔避免疯狂重启刷日志 -->
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <!-- 输出重定向到文件后 print 默认块缓冲, 提醒/错误会看不到 -->
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$ROOT/data/logs/webui.out.log</string>
    <key>StandardErrorPath</key>
    <string>$ROOT/data/logs/webui.err.log</string>
</dict>
</plist>
PLIST_EOF

unload_if_present
launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"

echo "已安装并启动: $LABEL"
echo "  Python:  $PY_REAL"
echo "  入口:    $ENTRY"
echo "  页面:    http://127.0.0.1:8765/"
echo "  日志:    $ROOT/data/logs/webui.out.log"
echo
echo "如果日记目录在 ~/Documents / ~/Desktop / ~/Downloads 下 (macOS 受保护目录),"
echo "还要给上面那个 Python 开「完全磁盘访问」, 否则服务起得来但读写不了日记:"
echo "  系统设置 → 隐私与安全性 → 完全磁盘访问权限 → + → ⌘⇧G 粘贴:"
echo "  $PY_REAL"
echo "授权后执行: launchctl kickstart -k $DOMAIN/$LABEL"
