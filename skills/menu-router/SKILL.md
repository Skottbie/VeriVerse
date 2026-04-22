---
name: menu-router
author: VeriVerse
version: 1.0.0
license: MIT
description: >
  VeriVerse TG Bot 入口路由。显示 inline keyboard 菜单，
  路由到 VeriVerse Agent 发射台功能或 VeriTask 链上验证。
  触发: /start, greeting, 你好, hello, menu, 菜单, /veritask, /veri
capabilities:
  - inline_keyboard_menu
  - gateway_config_patch_routing
  - message_tool
permissions:
  - message
  - gateway
examples:
  - input: "/start"
    output: "Use message tool to send Level 1 inline keyboard"
  - input: "/veritask"
    output: "gateway config.patch → bind veritask agent"
---

# menu-router

VeriVerse 统一 TG Bot 入口。显示 inline keyboard 菜单，
通过 `gateway` tool 的 `config.patch` 动态路由到子 agent。

## ⛔ CRITICAL: How to Send Inline Buttons

**Do NOT include buttons as JSON text in your reply.**

To display inline keyboard buttons in Telegram, you MUST use the `message` tool:
```json
{
  "action": "send",
  "channel": "telegram",
  "message": "menu text here",
  "buttons": [[{"text": "Button 1", "callback_data": "value1"}]]
}
```

⚠️ IMPORTANT: When `buttons` are included, use `action: "send"` with `buttons`.

## Menu Flow

### Level 1 Menu (on /start, greetings, or ambiguous input)

Call the `message` tool with:
- message: "🌐 欢迎来到 VeriVerse！请选择服务："
- buttons: `[[{"text": "🚀 VeriVerse Agent 发射台", "callback_data": "veriverse"}, {"text": "🔗 VeriTask 链上验证", "callback_data": "veritask"}]]`

### Callback Dispatch

**When you receive `callback_data: veriverse`:**
- Reply: "🚀 VeriVerse Agent 发射台已就绪！你可以使用以下命令：\n• 发射一个 Agent — 注册新 Agent\n• 投资 Agent #X — 投入 USDT\n• 挑战 Agent #X — 发起考证\n• /veri — 返回主菜单"
- Stay in current agent (veriverse). No config.patch needed.

**When you receive `callback_data: veritask`:**
1. Call `session_status` → extract `<USER_ID>` from session key
2. Send: "🔗 正在为您接入 VeriTask..."
3. Call `gateway` tool:
```json
{
  "action": "config.patch",
  "raw": "{ bindings: [ { agentId: \"veritask\", match: { channel: \"telegram\", peer: { kind: \"direct\", id: \"<USER_ID>\" } } }, { agentId: \"veriverse\", match: { channel: \"telegram\" } } ] }",
  "note": "已切换到 VeriTask 🔗 输入 /veri 可返回主菜单"
}
```

## Direct Command Dispatch (无需按钮也必须可用)

当用户直接发送以下命令意图时，不得只回复解释文本，必须调用对应技能流程：

- `挑战 Agent #<id>` / `challenge agent #<id>`
  - 直接进入 `challenge-orchestrator`。
  - 先执行 Step 1 上下文读取（prepare-only），再按 challenge-orchestrator 的既定流程继续。
  - **禁止**输出“你需要先定义任务/存入保证金/质押”等自由生成话术。

- `投资 Agent #<id>` / `invest agent #<id>`
  - 进入 `invest-agent`。

- `发射 Agent` / `launch agent`
  - 进入 `launch-agent`。

## /veri Command — Return to VeriVerse Menu

When user sends `/veri`, call `gateway` tool to remove peer binding:
```json
{
  "action": "config.patch",
  "raw": "{ bindings: [ { agentId: \"veriverse\", match: { channel: \"telegram\" } } ] }",
  "note": "已返回 VeriVerse 主菜单 🌐 发送任意消息查看菜单"
}
```

## Rules

1. On `/start`, greeting, or ambiguous input → ALWAYS use `message` tool with Level 1 buttons
2. On `callback_data: veriverse` → respond with VeriVerse commands, stay in current agent
3. On `callback_data: veritask` or `/veritask` → `session_status` then `gateway` config.patch
4. On `/veri` → `gateway` config.patch to remove peer binding, return to veriverse
5. **NEVER output buttons as JSON text — always use the message tool**
6. Do NOT fabricate data or skip tool calls
7. After gateway config.patch, gateway auto-restarts and sends `note` to user
8. For direct challenge/invest/launch intents, MUST dispatch to skills; do not output manual placeholder flows.
