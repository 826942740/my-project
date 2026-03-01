# CLAUDE.md

本文件用于说明仓库当前实现（As-Is），以代码为准。

## 模块职责
- `backend/`：FastAPI 路由与流程编排。
- `module-1-frontend/`：前端渲染与交互状态管理。
- `module-2-ai/`：Prompt 组装与 AI 调用封装。
- `module-3-game-rules/`：地图、章节、卡牌与规则引擎。
- `module-4-save-system/`：会话与存档持久化（SQLite）。

## 当前实现（As-Is）
### 三阶段主流程
1. `navigation`：玩家移动，进入卡牌。
2. `card`：卡内互动与判定（`continue/win/lose`）。
3. `daily_life`：事件卡后进入 3-5 轮日常，再回导航。

阶段切换（代码事实）：
- `navigation -> card`：`POST /api/navigate` 成功后进入格子卡牌。
- `card -> card`：`judge=continue` 且 `card_done=false`。
- `card -> daily_life`：事件卡完成后，后端在 `/api/card_action` 内生成首轮日常并返回 `daily_life`。
- `daily_life -> navigation`：`POST /api/daily_life` 返回 `done=true`。

### 存档与会话
- 会话创建：`POST /api/session/new`。
- 会话恢复：`POST /api/session/resume`（短码）。
- 状态读取：`GET /api/state`。
- 代码签名：`SaveSystem.create_session(story_id, initial_state) -> (token, short_code)`。

## 对外接口/输入输出
当前路由（`backend/main.py`）：
- `POST /api/session/new`
- `GET /api/state`
- `POST /api/navigate`
- `POST /api/card_action`
- `POST /api/daily_life`
- `GET /api/session/code`
- `POST /api/session/resume`
- `GET /api/nav`
- `GET /api/card_entry`
- `GET /api/health`

关键返回约定：
- `/api/nav`：`{"narrative": string, "directions": [...]}`。
- `/api/card_action`：包含 `npc_response/judge/card_done/options/stats`，若进日常还会附带 `daily_life`。
- `/api/daily_life`：`{"narrative": string, "options": string[], "round": n, "total": n, "done": bool}`。

## 关键流程
- 导航方向优先级：
  1. 按钮携带 `hint_direction` 直传。
  2. `navigator.parse_direction` 关键词解析。
  3. 失败再走 `build_direction_parse_prompt` + AI 解析。
- 卡片阶段：`build_card_prompt` 生成 JSON 约束，`AIClient.call(expect_json=True)` 保证结构化输出。
- 日常阶段：`build_daily_life_prompt` 生成 JSON 约束，后端 `json.loads` 解析。

## 已知限制与风险
### Known Mismatch（已知不一致）
- `build_nav_prompt()` 当前要求导航模型“严格 JSON 输出”。
- 但导航链路当前实现仍是：
  - 后端 `generate_nav_narrative()` 返回纯文本（未 `expect_json=True`，未 `json.loads`）。
  - 前端 `renderNavNarrative()` 用文本正则提取选项（`A/B/C`、`**...**`）。
- 影响：当模型按 prompt 返回 JSON 时，可能出现 JSON 原文显示或选项解析失败。

### 其他说明
- 当前仅通过 prompt 约束 options 无编号；未做后端统一去前缀清洗。
- 前端按钮文本现为“原始文本直出”，不再自动加 `A./B./C.`。

## 调试与排查
- 后端启动：`cd backend && uvicorn main:app --reload --port 8768`
- 健康检查：`GET /api/health`
- 常见排查点：
  - 导航选项异常：检查 `module-2-ai/prompts.py::build_nav_prompt` 与 `module-1-frontend/game.js::renderNavNarrative`。
  - 卡片/日常 JSON 解析失败：检查 `AIClient._ensure_json` 日志与对应 prompt 的输出格式规则。
