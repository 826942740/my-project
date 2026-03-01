# 模块 1：前端（module-1-frontend）

## 模块职责
- 渲染聊天式文本界面与侧边栏状态。
- 维护前端阶段状态：`navigation` / `card` / `daily_life`。
- 调用后端 API，不承载游戏规则判定逻辑。

## 当前实现（As-Is）
### 页面状态机
- 导航阶段：`fetchNavNarrative()` + `renderNavNarrative()`。
- 卡片阶段：`handleCardAction()`。
- 日常阶段：`handleDailyLifeAction()`。

代码位置：`module-1-frontend/game.js`
- `renderNavNarrative(content)`：解析导航旁白文本并生成按钮。
- `_appendNavOptionButtons(options)`：统一渲染选项按钮。
- `handleCardAction(playerInput)`：卡片 API 交互。
- `handleDailyLifeAction(playerInput)`：日常 API 交互。

### 选项按钮显示规则
- 当前按钮文案只显示模型原始 `text`。
- 不再由前端自动拼 `A./B./C.`。
- `label` 字段仅保留兼容，不参与展示。

### 导航解析机制
- 目前导航旁白解析依赖文本模式：
  - `A. ... / B. ... / C. ...`
  - `**选项**` 模式
- 不是 JSON 解包渲染。

## 对外接口/输入输出
前端调用的关键接口：
- `GET /api/state`
- `GET /api/nav`
- `POST /api/navigate`
- `POST /api/card_action`
- `POST /api/daily_life`
- `GET /api/card_entry`
- `POST /api/session/new`
- `POST /api/session/resume`
- `GET /api/session/code`

关键字段使用：
- 导航：`/api/nav -> narrative + directions`。
- 卡片：`/api/card_action -> npc_response/judge/card_done/options/daily_life`。
- 日常：`/api/daily_life -> narrative/options/done`。

## 关键流程
1. 页面初始化读取 `session_token`，无 token 则新建会话。
2. 若当前 `in_card` 存在则进卡片态，否则进入导航态并异步拉取旁白。
3. 卡片 `card_done=true` 时：
- 若含 `daily_life`，直接切到日常态。
- 否则回导航并拉新旁白。
4. 日常 `done=true` 时回导航并拉新旁白。

## 已知限制与风险
- 导航旁白若返回严格 JSON，前端正则解析可能失败。
- 模型若自行输出编号（如 `A ...`），前端会原样显示（不会二次加前缀）。
- `renderNavNarrative()` 对格式依赖较强，输出漂移时可退化成纯叙事显示而无按钮。

## 调试与排查
- 主要检查文件：`module-1-frontend/game.js`
- 排查顺序：
1. 控制台看 `apiPost` 返回结构是否完整。
2. 导航按钮异常先看 `renderNavNarrative` 两套正则是否命中。
3. 卡片/日常按钮异常看 `data.options` 是否数组。
4. 状态错乱看 `currentPhase` 切换点（`enterNavPhase/enterCardPhase/enterDailyLifePhase`）。
