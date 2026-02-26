# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目说明

**fangame** — AI 驱动的文字冒险游戏框架。

设计目标：输入任意剧情配置文件，自动生成完整可玩的文字冒险游戏。
- 游戏逻辑（地图移动、卡片事件、数值变化）由规则引擎控制，可靠且可预测
- 对话、叙事、NPC 交互由 AI 动态生成，体验丰富
- 存档保存在服务器，用户随时可从任意设备继续游戏
- 前端为现代网页，文字为主，侧边栏显示玩家状态

**核心原则：引擎与内容完全分离。** 所有剧情、卡片、地图数据在配置文件中，程序本身不包含任何故事内容。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python + FastAPI |
| AI 接口 | OpenAI 兼容格式（可配置任意 endpoint，如 DeepSeek/Claude/GPT） |
| 存档存储 | SQLite（单文件，便于部署） |
| 前端 | 原生 HTML + CSS + JavaScript（无框架，保持简单） |
| 剧情数据 | JSON 配置文件（stories/ 目录） |

---

## 整体游戏结构

游戏由多个**章节**组成，每个章节是一张独立的网格地图：

```
[第1章地图] → 走到最下行或最右列 → 触发本章主线剧情
     ↓ 完成主线
[第2章地图] → 走到最下行或最右列 → 触发本章主线剧情
     ↓ 完成主线
[第N章地图] → ... → 结局
```

### 地图与移动

- 每章地图为 M×N 网格，玩家从左上角 (1,1) 出发
- 移动规则：只能向右 / 向下 / 斜右下，不可回头
- 每个格子必有一张卡片（无空格）
- 走到最后一行或最后一列 → 强制触发本章主线

### 卡片（微型副本）

每张卡片是一个独立小副本，玩家进入后通过自由对话完成，分胜负结算奖惩：

| 卡片类型 | 说明 |
|---------|------|
| `monster` | 怪物/敌对生物，需要对话/智斗 |
| `npc` | 友好或中立角色，可交易/获情报 |
| `treasure` | 宝箱/机关，解谜或承担陷阱 |
| `main_story` | 本章主线剧情（边界触发，非随机） |

### 数值系统（统一 Stats）

所有数值（HP、物品、金币等）用同一扁平字典存储：

```json
{ "hp": 80, "hp_max": 100, "gold": 30, "bread": 2, "sword": 1 }
```

新增任何属性/物品：直接加 key，引擎无需改代码。

---

## 项目结构

```
fangame/
├── module-1-frontend/
│   ├── CLAUDE.md
│   ├── index.html          # 主页面（两种状态：导航中 / 卡片内）
│   ├── style.css
│   └── game.js             # 前端逻辑，与后端 API 通信
│
├── module-2-ai/
│   ├── CLAUDE.md
│   ├── client.py           # OpenAI 兼容 API 客户端
│   └── prompts.py          # 三种 Prompt 模板（导航/NPC/裁判）
│
├── module-3-game-rules/
│   ├── CLAUDE.md
│   ├── engine.py           # 主引擎：地图管理、移动、主线触发
│   ├── card_runner.py      # 卡片副本：对话流程、效果结算
│   ├── navigator.py        # 导航上下文：可选方向、卡片标题提取
│   ├── stats.py            # 统一数值系统：apply_effects、死亡判定
│   └── stories/            # 剧情配置文件（内容与引擎完全分离）
│       └── dark_forest/    # 示例故事包
│           ├── meta.json
│           ├── chapters.json
│           ├── chapters/
│           ├── cards/
│           └── main_stories/
│
├── module-4-save-system/
│   ├── CLAUDE.md
│   ├── session.py          # SaveSystem 类，存档读写
│   ├── models.py           # 数据库表结构
│   └── schema.sql          # 建表 SQL
│
└── backend/
    ├── main.py             # FastAPI 入口，路由定义
    └── config.py           # AI API 配置（从环境变量读取）
```

---

## 数据流

```
玩家输入（自然语言）
  → FastAPI 路由（main.py）
    → 存档系统（module-4）：读取当前 GameState
      → 游戏引擎（module-3）：
          [导航阶段] 解析方向意图 → 移动玩家 → 检测边界触发主线
          [卡片阶段] 传入玩家输入 + AI返回 → 判断胜负 → 结算 stats
      → AI 模块（module-2）：
          导航阶段 → 生成方向叙事提示
          卡片阶段 → NPC回应 + 裁判判断（同一次调用）
      → 存档系统（module-4）：保存新 GameState
    → 返回 JSON 给前端（module-1）
      → 前端渲染文字 + 更新状态栏
```

---

## 后端 API 接口

### 导航阶段（玩家在格子间移动）

```
POST /api/navigate
Body: {
  "session_token": "xxx",
  "player_input": "我往有动静的方向走"
}

Response: {
  "phase": "navigation",
  "narrative": "你小心地走向前方...",     // AI 导航旁白
  "moved_to": [2, 3],                     // 新坐标
  "entered_card": {                        // 进入的卡片信息
    "title": "哥布林斥候",
    "scene_description": "你走入昏暗的树林..."
  },
  "stats": { "hp": 80, "gold": 30, ... },
  "triggered_main_story": false
}
```

### 卡片阶段（玩家在卡片副本内对话）

```
POST /api/card_action
Body: {
  "session_token": "xxx",
  "player_input": "我大声呵斥它离开"
}

Response: {
  "phase": "card",
  "npc_response": "哥布林愣了一下，慢慢后退...",  // AI NPC 回应
  "judge": "continue",                              // continue / win / lose
  "card_done": false,
  "effects_log": [],
  "stats": { "hp": 80, "gold": 30, ... }
}
```

### 其他接口

```
POST /api/session/new          → 创建新游戏，返回 session_token
GET  /api/state?token=xxx      → 获取当前完整状态
POST /api/session/resume       → 通过存档码恢复游戏（换设备用）
```

---

## 剧情包格式（概览）

所有故事内容放在 `module-3-game-rules/stories/<故事名>/` 目录下：

```
dark_forest/
├── meta.json          # 故事名、AI风格、导航提示模板
├── chapters.json      # 章节列表顺序
├── chapters/
│   └── chapter_1.json # 地图尺寸、卡片池、主线ID
├── cards/
│   ├── monsters.json  # 怪物卡片库
│   ├── npcs.json      # NPC卡片库
│   └── treasures.json # 宝箱卡片库
└── main_stories/
    ├── act_1.json     # 第1章主线
    └── ending.json    # 结局
```

切换故事 = 只改加载的目录名，引擎代码零修改。

---

## 开发命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动后端（开发模式，支持热重载）
cd backend
uvicorn main:app --reload --port 8000

# 访问游戏
# 直接打开 module-1-frontend/index.html

# 查看 API 文档（FastAPI 自动生成）
# http://localhost:8000/docs
```

---

## 开发规则

- 一次只做一件事，改完一个功能确认运行正常再做下一个
- 所有代码加中文注释
- 不动与当前任务无关的代码
- 每次修改后 git commit，注释写清楚改了什么
- 新模块或架构变化先出方案让用户确认
- AI 配置（API key、endpoint）通过环境变量传入，不写入代码
- 故事内容（卡片、剧情、NPC）全部在 stories/ 配置文件，不写入程序逻辑
