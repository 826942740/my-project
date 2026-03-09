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
- `card -> daily_life`：事件卡完成后，后端在 `/api/card_action` 的 `meta_builder` 内用 `ai_client.call(expect_json=True)` 生成首轮日常，附在 SSE `done` 事件的 `daily_life` 字段中返回。
- `daily_life -> navigation`：`POST /api/daily_life` SSE `done` 事件返回 `done=true`。当 `current_round > total_rounds` 时不调 AI，直接返回单条 SSE `done` 事件。

### 存档与会话
- 会话创建：`POST /api/session/new`。
- 会话恢复：`POST /api/session/resume`（短码）。
- 状态读取：`GET /api/state`。
- 代码签名：`SaveSystem.create_session(story_id, initial_state) -> (token, short_code)`。

## 对外接口/输入输出
当前路由（`backend/main.py`）：

| 路由 | 方法 | 返回类型 | 说明 |
|------|------|---------|------|
| `/api/session/new` | POST | JSON | 创建新游戏会话 |
| `/api/state` | GET | JSON | 获取当前游戏状态 |
| `/api/navigate` | POST | JSON | 导航移动（进入卡片） |
| `/api/card_action` | POST | **SSE** | 卡片对话（流式 `npc_response`） |
| `/api/daily_life` | POST | **SSE** | 日常生活叙事（流式 `narrative`） |
| `/api/nav` | GET | **SSE** | 导航旁白（流式 `narrative`） |
| `/api/card_entry` | GET | **SSE** | 卡片入场叙事（流式纯文本） |
| `/api/session/code` | GET | JSON | 获取存档短码 |
| `/api/session/resume` | POST | JSON | 通过短码恢复存档 |
| `/api/health` | GET | JSON | 健康检查 |

### SSE 端点返回约定
所有 SSE 端点返回 `text/event-stream`，事件格式：
```
data: {"type":"token","text":"字"}\n\n      # 逐字符流式输出
data: {"type":"done", ...结构化元数据}\n\n  # 流结束，携带完整业务数据
data: {"type":"error","message":"..."}\n\n  # 异常时返回
```

各端点 `done` 事件携带的元数据：
- `/api/nav`：`{narrative, options, directions}`
- `/api/card_action`：`{phase, npc_response, judge, card_done, effects_log, stats, chapter_info, game_over, options}`，若进日常还附带 `daily_life`
- `/api/daily_life`：`{phase, narrative, options, round, total, done, stats, chapter_info}`
- `/api/card_entry`：`{narrative}`

### JSON 端点返回约定
- `/api/navigate`：`{phase, moved_to, direction, entered_card: {card_id, title, scene_description, initial_actions, audio_url, video_url}, stats, chapter_info}`
- `/api/session/new`：`{session_token, short_code, story_id, state, chapter_info, prologue, prologue_card}`

## 流式输出架构（SSE）

### 后端（backend/main.py）
- **`_sse_event(data)`**：构造单条 SSE `data:` 行
- **`_stream_json_field_sse(messages, field_name, meta_builder)`**：状态机从 AI 流式 JSON 中提取指定字段值，逐字符 yield SSE token。状态：`SEARCH(0) → IN_VALUE(1) → DONE_VALUE(2)`。处理 JSON 转义（`\n`, `\"` 等）。流结束后清理 `<think>` 块，调用 `meta_builder(cleaned_text)` 构造 `done` 事件
- **`_stream_plain_sse(messages, meta_builder)`**：纯文本流式（不解析 JSON），用于 `card_entry`
- **`meta_builder` 模式**：每个 SSE 端点定义闭包 `meta_builder(full_text)`，负责：解析完整 JSON → 引擎结算/状态更新 → `save_game()` → 返回 `done` 事件 payload

### AI 客户端（module-2-ai/client.py）
- **`AIClient.call(messages, expect_json=False)`**：同步调用，带重试和 JSON 验证
- **`AIClient.stream_call(messages, force_json=False)`**：流式调用，`yield` 原始 chunk。`force_json=True` 时加 `response_format={"type":"json_object"}`，API 不支持时自动降级
- `stream_call` 被 `_stream_json_field_sse` 和 `_stream_plain_sse` 使用，JSON 端点传 `force_json=True`，纯文本端点不传

### 前端（module-1-frontend/game.js）
- **`apiSSE(path, method, body, onToken, onDone, onError, timeoutMs)`**：通用 SSE 读取，解析 `data:` 行，按 `type` 分发回调
- **`renderMessageStream(type, speakerName)`**：返回 `{appendText, getText, finish}` 对象。**懒创建 DOM**：首次 `appendText` 时才创建元素，避免空气泡
- **`renderMessageTypewriter(type, text, onDone, interval)`**：本地文本打字机效果（用于 `card_action` done 事件中首轮日常叙事的展示）
- 所有 SSE done 回调含兜底：`if (!stream.getText() && data.narrative) stream.appendText(data.narrative)`

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
  3. 失败再走 `build_direction_parse_prompt` + AI 解析（`AIClient.call()`，非流式）。
- 卡片阶段：`build_card_prompt` → `_stream_json_field_sse` 提取 `npc_response` 字段流式输出 → `meta_builder` 内 `json.loads` 解析完整 JSON → `process_card_turn` 引擎结算。
- 日常阶段：`build_daily_life_prompt` → `_stream_json_field_sse` 提取 `narrative` 字段流式输出 → `meta_builder` 内 `json.loads` 解析选项。
- 导航旁白：`build_nav_prompt` → `_stream_json_field_sse` 提取 `narrative` 字段流式输出 → `meta_builder` 内 `json.loads` 解析 options + directions。
- 卡片入场：`build_card_entry_prompt` → `_stream_plain_sse` 纯文本流式输出。

## 已知限制与风险
### 其他说明
- options 无编号仅靠 prompt 约束，未做后端统一去前缀清洗。
- 前端按钮文本由 `_appendNavOptionButtons` 自动加 `A/B/C/D` 标签前缀。
- `generate_nav_narrative()` 函数仍存在（`AIClient.call` 非流式），但 `/api/nav` 端点已不使用它，改为 SSE 流式。该函数为遗留代码。

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

## 音视频系统
### 卡片音频（per-card audio）
- 每张卡片 JSON 中有 `"audio_url"` 字段，存储相对路径如 `/static/soundeffect/xxx.mp3`。
- 后端在 `/api/session/new`（prologue）和 `/api/navigate` 响应的 `entered_card` 中透传 `audio_url`。
- 前端 `playCardStartSfx(url)` 接收 URL，使用 `_audioCache`（Map）缓存 Audio 对象避免重复创建。
- 若 `audio_url` 为空，回退到 `CARD_START_SFX_URL` 常量（可为空）。

### 卡片视频（per-card video）
- 每张卡片 JSON 中有 `"video_url"` 字段，存储相对路径如 `/static/videoeffect/卡片标题.mp4`。
- 后端在 `/api/session/new`（prologue）和 `/api/navigate` 响应的 `entered_card` 中透传 `video_url`。
- 前端 `playCardVideo(url, callback)` 播放卡片专属视频，播完后执行回调。
- 有专属视频的卡片：饿鬼显形、井边的执念、竹林灵、夜里的访客、Jet在想办法。其余卡片使用 `sample.mp4` 占位。

### 静态资源目录约定
```
module-1-frontend/
├── startvideo.mp4          # 开场视频
├── soundeffect/
│   └── *.mp3               # 卡片音效，路径统一为 /static/soundeffect/文件名.mp3
└── videoeffect/
    ├── sample.mp4           # 默认占位视频
    └── *.mp4                # 卡片专属视频，路径统一为 /static/videoeffect/文件名.mp4
```
所有媒体文件均存放在 `module-1-frontend/` 内，打包后路径不变。

## 调试与排查
- 后端启动：`cd backend && uvicorn main:app --reload --port 8768`
- 健康检查：`GET /api/health`
- 常见排查点：
  - 导航选项异常：检查 `module-2-ai/prompts.py::build_nav_prompt` 与前端 `fetchNavNarrative` SSE done 回调中的 options 解析。
  - 流式输出无内容：检查 `_stream_json_field_sse` 状态机是否找到目标字段（`field_name` 拼写、AI 是否返回合法 JSON）。日志关键词：`[AI流式请求]`。
  - 卡片/日常 JSON 解析失败：检查 `meta_builder` 内 `json.loads` fallback 日志。流式端点不经过 `AIClient._ensure_json`。
  - AI 忽略玩家输入：检查对应 prompt 的【核心规则】和 player_input 包装格式是否完整。
  - SSE 前端卡住：检查后端是否返回了非 SSE 格式（如 `daily_life` 超轮时需返回 `StreamingResponse` 而非普通 dict）。
  - 视频黑屏：检查 `module-1-frontend/startvideo.mp4` 是否存在；浏览器缓存导致旧 game.js 运行时先强刷。
  - 卡片视频不播放：检查 `video_url` 字段对应文件是否在 `module-1-frontend/videoeffect/` 内；文件名含中文需确保编码一致。
  - 音频不播放：检查 `audio_url` 字段非空、文件是否在 `module-1-frontend/soundeffect/` 内；浏览器 autoplay 策略需用户手势后才可播放。
