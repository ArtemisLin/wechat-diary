# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置: 网页版单文件应用 (webui 入口)。

在目标平台上构建 (exe 只能在 Windows 上打, .app 只能在 macOS 上打;
仓库的 GitHub Actions build 工作流会在云端两个平台各打一份):

    pip install -r requirements.txt pyinstaller certifi
    pyinstaller wechat-diary.spec --noconfirm

产物: dist/wechat-diary(.exe) —— 自带 Python 与全部依赖, 用户双击即用,
不需要装 Python、不碰 PATH、与系统里已有的 Python 互不干扰。
运行时文件 (.env / data/) 生成在可执行文件旁边 (便携式布局)。
"""
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# apscheduler 有动态导入; tzdata 是 Windows 上 zoneinfo 的时区数据来源;
# main/scheduler 由 webui 延迟导入, 静态分析扫不到
hiddenimports = ["main", "scheduler", "tzdata"] + collect_submodules("apscheduler")

datas = [("src/web", "web")] + collect_data_files("tzdata")
try:
    datas += copy_metadata("apscheduler")
except Exception:
    pass

# CA 根证书必须进包: 构建机 Python 的证书路径在用户机器上不存在,
# 缺了它 macOS 冻结态所有 HTTPS 直接握手失败 (config.py 冻结分支负责启用)。
# 故意不用 try 包裹 —— 构建机没装 certifi 就应该在这里炸, 不能再出哑弹包。
import certifi

datas += [(certifi.where(), "certifi")]

a = Analysis(
    ["src/webui.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="wechat-diary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 保留控制台: 收发消息日志可见, 出问题用户能看到原因
    disable_windowed_traceback=False,
)
