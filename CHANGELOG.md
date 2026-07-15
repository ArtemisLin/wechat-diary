# Changelog

## v2.0.0 (2026-07)

定位收敛: "微信 → 你自己的 Obsidian vault" 的开源个人日记管道。

- 零 key 模式: 不配 AI_API_KEY 也完整可用 (原文直存, chat 固定文案引导)
- 数据契约 v1: 按年目录 DIARY_DIR/YYYY/ + YAML frontmatter + 语音 🎤 标记
  (见 docs/data-contract.md); 附存量迁移脚本 scripts/migrate_v2.py
- 可靠性: 心跳时间戳 + 启动离线间隔提示; 错过提醒的启动补偿 (每天至多一次)
- 开源配套: MIT LICENSE / requirements.txt / CI

## v1.x (2026-04 前)

单用户自用版: iLink 接入 / chat-diary 双模式状态机 / LLM 润色 /
22:00+23:00 提醒 / 撤回与封存 / 用户取名。
