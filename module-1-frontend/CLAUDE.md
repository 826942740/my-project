# 模块 1：前端界面

## 模块职责

负责玩家看到的所有页面和交互。通过 HTTP API 与后端通信，本身不包含任何游戏逻辑。

---

## 技术约束

- 纯原生 HTML + CSS + JavaScript，不使用 Vue/React 等框架
- 单页应用（SPA），不刷新页面切换状态
- 响应式，支持桌面和手机浏览器
- `session_token` 存储在浏览器 `localStorage`，每次请求自动带上

---

## 一、两种交互阶段

前端需要区分两种状态，UI 提示不同：

| 阶段 | 说明 | 玩家输入 |
|------|------|---------|
| **导航阶段** | 玩家在格子间移动，AI 给出方向提示 | 自然语言描述方向意图（"往有动静的地方走"） |
| **卡片阶段** | 玩家在卡片副本内与 NPC 对话 | 自由对话（"我大声呵斥它"） |

输入框下方显示当前阶段提示，让玩家知道自己在做什么。

---

## 二、界面布局

```
┌─────────────────────────────────────────────────────────┐
│  [游戏标题]                              [菜单] [存档码] │
├────────────────────────────────┬────────────────────────┤
│                                │  📍 第1章·黑暗森林      │
│   游戏文本输出区               │  位置：(2, 3)           │
│   （滚动，新内容追加到底部）   │  ─────────────────────  │
│                                │  ❤️  hp      80 / 100  │
│   > [旁白] 你走入昏暗的树林…  │  💰  gold    30        │
│   > [哥布林] 呲牙咧嘴地盯着你 │  🍞  bread   2         │
│   > [系统] 胜利！获得金币 +3  │  ⚔️  sword   1         │
│                                │  ─────────────────────  │
│                                │  [卡片中: 哥布林斥候]   │
│                                │  第 2 / 6 轮           │
├────────────────────────────────┴────────────────────────┤
│  当前：卡片对话中  >  [玩家输入框]            [发送]     │
└─────────────────────────────────────────────────────────┘
```

---

## 三、文本输出区

### 消息类型与颜色

| 类型 | 显示样式 | 示例 |
|------|---------|------|
| `narrative` | 白色，正文字体 | 旁白/场景描述 |
| `npc` | 浅黄色，带角色名前缀 | `[哥布林] 呲牙咧嘴…` |
| `player` | 灰色，右对齐 | `> 我大声呵斥它` |
| `system` | 浅绿色，小字 | `[系统] 胜利！gold +3` |
| `warning` | 橙色 | `[警告] HP 不足，注意！` |
| `main_story` | 金色加粗 | 主线剧情文字 |

### 显示策略

- 新消息追加到底部，自动滚动
- AI 生成时显示打字机动画（逐字显示）
- 历史消息保留全部（滚动查看），不截断
- AI 请求中显示加载动画，禁用输入框

---

## 四、状态侧边栏

### Stats 显示

侧边栏动态显示玩家所有 stats（来自后端 `stats` 字典）：

- **hp / hp_max**：显示为进度条 + 数字（`80 / 100`）
- **其他数值**：图标 + 名称 + 数字，逐行列出
- stats 字段完全由后端决定，前端动态渲染，不硬编码字段名

图标映射（在 `game.js` 中配置，可扩展）：
```js
const STAT_ICONS = {
  hp: "❤️", gold: "💰", bread: "🍞",
  sword: "⚔️", rope: "🪢", torch: "🔦"
  // 未知 stat 显示默认图标 📦
}
```

### 位置与进度显示

- 当前章节名 + 网格坐标 `(行, 列)`
- 卡片阶段显示：卡片名称 + 当前轮数/最大轮数

---

## 五、初始化流程

```
首次访问
  → 无 session_token
    → POST /api/session/new（可选：选择故事）
      → 存储 token 到 localStorage
        → 加载第1章地图，进入导航阶段

再次访问
  → 有 session_token
    → GET /api/state?token=xxx
      → 成功：恢复上次状态（导航或卡片中）
      → 失败（token 无效）：提示用户开始新游戏
```

### 换设备继续游戏

- 点击 [存档码] 按钮显示当前 token 的短码
- 新设备输入短码 → `POST /api/session/resume` → 恢复存档

---

## 六、与后端的 API 接口

### 导航阶段

```
POST /api/navigate
Body: { "session_token": "xxx", "player_input": "往有动静的地方走" }

Response: {
  "phase": "navigation",
  "narrative": "你小心地向前走去…",
  "moved_to": [2, 3],
  "entered_card": {
    "title": "哥布林斥候",
    "scene_description": "你走入昏暗的树林…"
  },
  "stats": { "hp": 80, "gold": 30, "bread": 2 },
  "triggered_main_story": false
}
```

### 卡片阶段

```
POST /api/card_action
Body: { "session_token": "xxx", "player_input": "我大声呵斥它离开" }

Response: {
  "phase": "card",
  "npc_response": "哥布林愣了一下，慢慢后退…",
  "judge": "continue",          // continue / win / lose
  "card_done": false,
  "effects_log": [],            // 结算时如 ["gold +3", "hp -10"]
  "stats": { "hp": 80, "gold": 30 }
}
```

### 其他接口

```
POST /api/session/new           → 创建新游戏，返回 session_token + 初始状态
GET  /api/state?token=xxx       → 获取当前完整状态（页面刷新时调用）
POST /api/session/resume        → Body: { "code": "短码" }，恢复存档
```

### 错误处理

- 网络超时（>30s）：显示提示，允许重试
- AI 生成失败：显示系统提示，不中断游戏
- token 无效：提示开始新游戏

---

## 七、文件结构

```
module-1-frontend/
├── CLAUDE.md          ← 本文件
├── index.html         # 主页面结构
├── style.css          # 样式（颜色、布局、消息类型样式）
└── game.js            # 前端逻辑：API通信、消息渲染、状态管理
```

### game.js 核心功能

- `initGame()` — 检查 localStorage，执行初始化流程
- `sendInput(text)` — 根据当前阶段（导航/卡片）调用对应 API
- `renderMessage(msg)` — 按消息类型渲染到文本区
- `updateSidebar(stats, position, cardInfo)` — 更新侧边栏状态
- `showLoading() / hideLoading()` — 加载动画控制
