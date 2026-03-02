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
- `/api/nav`：`{"narrative": string, "directions": [...]}`。narrative 字段实际为 AI 返回的 JSON 字符串或纯文本（见已知不一致）。
- `/api/card_action`：包含 `npc_response/judge/card_done/options/stats`，若进日常还会附带 `daily_life`。
- `/api/daily_life`：`{"narrative": string, "options": string[], "round": n, "total": n, "done": bool}`。

## Prompt 架构（module-2-ai/prompts.py）

### build_nav_prompt() — 导航旁白
- **输出格式**：要求 AI 返回严格 JSON `{"narrative": "...", "options": [...]}`
- **叙事人称**：第一人称（我/我的），禁止使用你/她/Khem 作为叙事主语
- **上下文优先级**：`last_daily_life_context`（日常最后一轮叙事+玩家输入）> `last_card_context`（上一张卡片结果）
- **options**：数量与可选方向数一致，纯文本行动短句，禁止任何编号前缀

### build_card_prompt() — 卡片 NPC 对话 + 裁判
- **输出格式**：严格 JSON `{"npc_response": "...", "judge": "continue/win/lose", "judge_reason": "...", "options": [...]}`
- **【核心规则】**：npc_response 必须直接承接玩家本轮具体行动，先写行动造成的可见结果，禁止无视玩家输入自行推进剧情
- **叙事定位**：叙事者+裁判，不强制每轮出对白；非言语实体用声音/温度/气味/触感反馈而非台词
- **player_input 传入**：包装为 `"Khem的行动：{input}\n\n请以角色身份直接回应这个行动。"`
- **历史记录**：dialogue_history 中 npc 回应包装为 JSON 格式与 few-shot 示例格式保持一致
- **options 规则**：紧扣当前 npc_response 内容，三个选项代表不同策略方向（对抗/安抚/回避等），禁止通用选项

### build_daily_life_prompt() — 日常生活叙事
- **输出格式**：严格 JSON `{"narrative": "...", "options": [...]}`
- **叙事人称**：第二人称（你），指代 Khem
- **【核心规则】**：叙事必须直接回应玩家最新行动，叙事开头就写该行动的过程和后果，禁止编造无关场景
- **开场去模板规则**：首句在4类开场中轮换（环境先行/感官先行/对话先行/动作先行），不得复用相同动作词组
- **player_input 传入**：包装为 `"Khem的行动：{input}\n\n请直接从这个行动展开叙事，描写具体过程和后果。"`
- **options 规则**：紧扣刚生成的 narrative 内容，三个不同方向后续行动，禁止照搬素材列表原文
- **轮次特别指示**：第1轮从卡片情绪余韵起笔；最后一轮以不安预兆收尾；中间轮优先生活细节+关系互动

### build_card_entry_prompt() — 卡片入场叙事
- **触发时机**：玩家选择方向进入新卡片后，前端异步调用
- **player_choice_text**：玩家选择的行动文字直接注入为 `[玩家的行动]`
- **输出**：纯叙事，不含选项，不用问句结尾

### build_direction_parse_prompt() — 方向意图解析
- **触发时机**：关键词匹配失败时 AI 兜底
- **输出**：仅返回 `right/down/diagonal` 三者之一

## 关键流程
- 导航方向优先级：
  1. 按钮携带 `hint_direction` 直传。
  2. `navigator.parse_direction` 关键词解析。
  3. 失败再走 `build_direction_parse_prompt` + AI 解析。
- 卡片阶段：`build_card_prompt` 生成 JSON 约束，`AIClient.call(expect_json=True)` 保证结构化输出。
- 日常阶段：`build_daily_life_prompt` 生成 JSON 约束，后端 `json.loads` 解析。

## 已知限制与风险
### Known Mismatch（已知不一致）
- `build_nav_prompt()` 要求导航模型返回严格 JSON `{"narrative", "options"}`。
- 但导航链路当前实现：
  - 后端 `generate_nav_narrative()`：`return ai_client.call(messages)`，未加 `expect_json=True`，未做 `json.loads`。
  - 前端 `renderNavNarrative()` 做了三层兜底：① `JSON.parse()` ② `"options"` 正则提取 ③ `A./B./C.` 正则。
- 实际表现：模型返回 JSON → 后端原样传给前端 → 前端①兜底解析成功，功能正常，但链路不规范。
- **待修**：`generate_nav_narrative()` 加 `expect_json=True` 并 `json.loads`，后端直接返回结构化字段。

### 其他说明
- options 无编号仅靠 prompt 约束，未做后端统一去前缀清洗。
- 前端按钮文本原始文本直出，不自动加 `A./B./C.`。

## 前端页面流程
### 页面层级与切换顺序
```
start-screen → intro-screen → video-screen → game-screen
```
- `start-screen`：无 token 时显示，有存档可继续，或开始新游戏。
- `intro-screen`：新游戏时显示故事背景、角色说明、初始数值。
- `video-screen`：点击"开始冒险"后全屏播放开场视频 `/static/startvideo.mp4`，播完或跳过后进入游戏。
- `game-screen`：主游戏界面。

### 视频播放逻辑（game.js）
- `showVideoScreen()`：重置 `_videoEnded = false`，调用 `video.play()`；若 play 失败（autoplay 策略或文件缺失）直接 `endVideoAndStart()`。
- `endVideoAndStart()`：`_videoEnded` 互斥锁防止 `ended` 事件与 `play().catch` 双重触发；调用 `startNewGame()`。
- 视频文件路径：`module-1-frontend/startvideo.mp4`（由 `/static/startvideo.mp4` 访问）。

## 音频系统
### 卡片音频（per-card audio）
- 每张卡片 JSON 中有 `"audio_url"` 字段，存储相对路径如 `/static/soundeffect/xxx.mp3`。
- 后端在 `/api/session/new`（prologue）和 `/api/card_entry` 响应中透传 `audio_url`。
- 前端 `playCardStartSfx(url)` 接收 URL，使用 `_audioCache`（Map）缓存 Audio 对象避免重复创建。
- 若 `audio_url` 为空，回退到 `CARD_START_SFX_URL` 常量（可为空）。

### 静态资源目录约定
```
module-1-frontend/
├── startvideo.mp4          # 开场视频
└── soundeffect/
    └── *.mp3               # 卡片音效，路径统一为 /static/soundeffect/文件名.mp3
```
所有媒体文件均存放在 `module-1-frontend/` 内，打包后路径不变。

## 调试与排查
- 后端启动：`cd backend && uvicorn main:app --reload --port 8768`
- 健康检查：`GET /api/health`
- 常见排查点：
  - 导航选项异常：检查 `module-2-ai/prompts.py::build_nav_prompt` 与 `module-1-frontend/game.js::renderNavNarrative`。
  - 卡片/日常 JSON 解析失败：检查 `AIClient._ensure_json` 日志与对应 prompt 的输出格式规则。
  - AI 忽略玩家输入：检查对应 prompt 的【核心规则】和 player_input 包装格式是否完整。
  - 视频黑屏：检查 `module-1-frontend/startvideo.mp4` 是否存在；浏览器缓存导致旧 game.js 运行时先强刷。
  - 音频不播放：检查 `audio_url` 字段非空、文件是否在 `module-1-frontend/soundeffect/` 内；浏览器 autoplay 策略需用户手势后才可播放。
