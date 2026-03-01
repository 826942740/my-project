# 模块 4：存档系统（module-4-save-system）

## 模块职责
- 持久化保存/读取完整 GameState。
- 管理 `session_token` 与 `short_code`。
- 为后端提供会话存在性与恢复能力。

## 当前实现（As-Is）
### 关键类
代码位置：`module-4-save-system/session.py`
- `create_session(story_id, initial_state) -> (token, short_code)`
- `load_game(token) -> dict | None`
- `save_game(token, state) -> None`
- `session_exists(token) -> bool`
- `get_short_code(token) -> str | None`
- `get_token_by_code(short_code) -> str | None`

### 存储模型
- SQLite `sessions` 表（`token/story_id/game_state/short_code/created_at/updated_at`）。
- `game_state` 以 JSON 文本整包存储。

## 对外接口/输入输出
由 `backend/main.py` 对外暴露的相关 API：
- `POST /api/session/new`
- `GET /api/state`
- `GET /api/session/code`
- `POST /api/session/resume`

说明：当前代码中不存在 `/api/start`、`/api/load` 路由，统一使用以上 `session/* + state` 接口。

## 关键流程
1. 新游戏：后端生成初始 state 后调用 `create_session`。
2. 每次玩家动作后：后端调用 `save_game` 覆盖更新。
3. 刷新/重进：前端用 token 调 `GET /api/state` 恢复。
4. 跨设备恢复：短码换 token（`/api/session/resume`）。

## 状态兼容与衔接
当前存档包含完整运行态，含三阶段字段：
- 导航/卡片：`position/in_card/card_round/card_history/...`
- 日常：`daily_life_phase/daily_life_round/daily_life_total/daily_life_history`

兼容边界：
- 本系统不做 schema migration。
- 若未来 GameState 结构变化，旧存档是否可读取由上层业务兜底。

## 已知限制与风险
- 短码是 token 的别名，不具备额外权限隔离机制。
- 不支持多存档槽位（每 token 一份当前进度）。
- 无自动清理策略，历史会话会持续累积。

## 调试与排查
- 主要文件：
  - `module-4-save-system/session.py`
  - `module-4-save-system/models.py`
  - `module-4-save-system/schema.sql`
- 常见检查项：
  1. token 无效：`session_exists` 与 `get_session` 查询结果。
  2. 短码恢复失败：`get_token_by_code` 是否命中。
  3. 状态丢失：确认每条主流程路由是否都调用了 `save_game`。
