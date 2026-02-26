# 模块 3：后端游戏规则引擎

## 模块职责

游戏的"大脑"。负责管理地图状态、驱动卡片事件、更新玩家数值。
所有数值变化（HP增减、物品增减、任意 stat 变化）都在这里发生，AI 无权直接修改。

**核心原则：引擎与内容完全分离。**
引擎只是规则机器，不包含任何故事内容。所有剧情、卡片、地图数据全部来自 `stories/` 目录的配置文件。

---

## 技术约束

- Python，作为 FastAPI 后端的核心子模块
- 游戏内容（地图、卡片、NPC、剧情）全部来自 JSON 配置文件
- 引擎读取配置运行逻辑，更换 `stories/` 下的文件夹即可切换完全不同的故事

---

## 一、整体游戏结构

游戏由多个**章节**组成，每个章节有独立的网格地图：

```
[第1章地图] → 走到最下行或最右列 → 触发本章主线剧情
     ↓ 完成主线
[第2章地图] → 走到最下行或最右列 → 触发本章主线剧情
     ↓ 完成主线
[第N章地图] → ... → 结局
```

每个章节地图完全独立，章节间通过主线剧情完成串联。

---

## 二、地图系统

### 网格结构

每章地图是一个 M×N 的网格，玩家从左上角 (1,1) 出发：

```
     列1   列2   列3   列4   列5
行1  [出发] [卡片] [卡片] [卡片] [卡片] ← 走到第5列触发主线
行2  [卡片] [卡片] [卡片] [卡片] [卡片]
行3  [卡片] [卡片] [卡片] [卡片] [卡片]
行4  [卡片] [卡片] [卡片] [卡片] [卡片]
行5  [卡片] [卡片] [卡片] [卡片] [卡片]
  ↑ 走到第5行也触发主线
```

- 每个格子必有一张卡片，没有空格
- 地图大小在章节配置中定义，可以每章不同

### 移动规则

```
当前位置 (行, 列)，合法移动方向：
  ✅ 向右     → (行,   列+1)
  ✅ 向下     → (行+1, 列  )
  ✅ 斜右下   → (行+1, 列+1)
  ❌ 向左/向上/任何让行或列减小的方向 → 禁止
```

类比：像走台阶，只能往前走，不能往回走。

### 主线触发条件

**玩家移动到最后一行（行号 = 地图总行数）或最后一列（列号 = 地图总列数）时，立即触发本章主线剧情。**

- 触发后进入主线卡片流程，完成前无法继续移动
- 完成主线后，加载下一章地图（从新地图 (1,1) 出发）

### 卡片生成时机

- 地图加载时，为所有格子从卡片池中**随机分配**一张卡片（类型 + 标题确定）
- 卡片详细内容（场景描述、NPC 对话）在玩家**进入该格子时**才完整加载
- 相邻格子的**标题和类型**对导航 Agent 可见（用于生成方向提示）

---

## 三、数值系统（统一 Stats）

所有玩家数值，包括 HP、物品、金币、任意自定义属性，全部用**同一套扁平字典**存储：

```json
{
  "stats": {
    "hp":       80,
    "hp_max":   100,
    "gold":     30,
    "bread":    2,
    "sword":    1,
    "rope":     0,
    "exp":      15
  }
}
```

- 1 个 hp 就是 1 点血，100 个 gold 就是 100 枚金币，1 个 sword 就是 1 把剑
- 数值为 0 时等同于"没有"，不需要特殊处理
- 新增任何数值/物品：直接在配置里加一个新 key，引擎无需改代码
- 没有背包容量限制（除非剧情配置里特别定义）

### 效果格式（卡片配置中使用）

```json
[
  { "stat": "hp",    "delta": -10 },
  { "stat": "gold",  "delta": 5  },
  { "stat": "sword", "delta": 1  }
]
```

- `delta` 为正数 = 增加，负数 = 减少
- 引擎会在结算时检查 hp 是否 ≤ 0（游戏结束判定）

---

## 四、卡片系统

### 卡片类型

| 类型 | 说明 |
|------|------|
| `monster`    | 怪物/敌对生物，需要对话/智斗击退或逃脱 |
| `npc`        | 友好或中立角色，可交易/获取情报/完成任务 |
| `treasure`   | 宝箱/机关/遗迹，需要解谜或承担陷阱风险 |
| `main_story` | 本章主线剧情卡片（由地图边界触发，非随机） |

### 卡片生命周期（微型副本）

每张卡片是一个独立的**微型副本**，玩家进入后必须完成才能继续移动：

```
玩家进入格子
  → 显示场景描述
    → 玩家自由输入文字
      → AI 扮演卡片 NPC 回应
        → AI 同时判断结果：
            继续  → 下一轮对话（未超过 max_rounds）
            胜利  → 执行 win_effects，退出卡片
            失败  → 执行 lose_effects，退出卡片
            超轮  → 达到 max_rounds 仍未分胜负，强制失败结算
```

### 卡片配置格式（JSON）

```json
{
  "id": "goblin_patrol",
  "title": "哥布林斥候",
  "type": "monster",
  "scene_description": "你走入昏暗的树林，一个绿皮小怪蹲在石头上盯着你...",
  "npc": {
    "name": "哥布林斥候",
    "personality": "凶猛但胆小，见势不妙会逃跑",
    "win_judge":  "玩家成功吓走、击退或说服哥布林离开视为胜利",
    "lose_judge": "玩家被哥布林逼退、放弃抵抗或被吓跑视为失败"
  },
  "max_rounds": 6,
  "win_effects":  [{ "stat": "gold", "delta": 3 }],
  "lose_effects": [{ "stat": "hp",   "delta": -10 }]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识，同一故事包内不重复 |
| `title` | 卡片标题，导航 Agent 可见，用于生成方向提示 |
| `type` | 卡片类型（monster / npc / treasure / main_story） |
| `scene_description` | 玩家进入时看到的初始描述 |
| `npc.name` | NPC 名称 |
| `npc.personality` | NPC 性格，注入 AI prompt |
| `npc.win_judge` | AI 裁判的胜利判定标准（自然语言描述） |
| `npc.lose_judge` | AI 裁判的失败判定标准 |
| `max_rounds` | 最大对话轮数，超出后强制失败结算 |
| `win_effects` | 胜利时对玩家 stats 的影响 |
| `lose_effects` | 失败时对玩家 stats 的影响 |

---

## 五、导航 Agent

玩家完成一张卡片后，进入**导航阶段**，由 AI Agent 扮演旁白向导：

### 工作流程

```
1. 引擎计算当前位置的合法下一步（最多3个方向：右/下/斜）
2. 取各目标格子的卡片 title + type
3. Agent 根据类型生成隐晦的叙事提示（不直接说类型）：
     monster  → "前方隐约传来动静"
     npc      → "远处似乎有人影晃动"
     treasure → "你注意到地面有什么东西在反光"
4. 组合成一段旁白，询问玩家想往哪个方向走
5. 玩家回复方向意图（自然语言）
6. 引擎解析意图 → 移动玩家 → 进入对应卡片
```

### 提示生成规则（在 meta.json 中配置）

导航提示的措辞风格和类型→提示的对应关系，全部在 `meta.json` 中定义，不写死在引擎里。

---

## 六、AI 角色分工

| AI 角色 | 触发时机 | 职责 |
|---------|---------|------|
| **导航旁白** | 卡片完成后，玩家选路时 | 根据相邻卡片标题造句，问玩家走哪里 |
| **卡片 NPC** | 玩家在卡片内输入时 | 扮演卡片里的角色与玩家对话 |
| **卡片裁判** | 每轮对话结束后 | 判断本轮结果：继续/胜利/失败 |

**卡片 NPC 和裁判可以是同一次 AI 调用**，返回格式：
```json
{
  "npc_response": "哥布林龇牙咧嘴地后退了一步...",
  "judge": "continue"
}
```
`judge` 取值：`continue` / `win` / `lose`

---

## 七、玩家完整状态（GameState）

```json
{
  "story_id":    "dark_forest",
  "chapter_idx": 0,
  "position":    [2, 3],
  "in_card":     "goblin_patrol",
  "card_round":  2,
  "card_history": [
    { "role": "player", "content": "我大声呵斥它" },
    { "role": "npc",    "content": "哥布林愣了一下..." }
  ],
  "stats": {
    "hp":     80,
    "hp_max": 100,
    "gold":   30,
    "bread":  2
  },
  "map_cards": {
    "1,1": "village_start",
    "1,2": "old_merchant",
    "2,3": "goblin_patrol"
  },
  "visited": [[1,1],[1,2],[2,2],[2,3]],
  "main_story_done": [0]
}
```

---

## 八、故事包目录结构（内容与引擎完全分离）

```
stories/
└── dark_forest/               ← 一个完整的故事包（可随时替换）
    ├── meta.json              ← 故事名称、AI风格、导航提示模板
    ├── chapters.json          ← 章节列表与顺序
    ├── chapters/
    │   ├── chapter_1.json     ← 第1章：地图尺寸、卡片池引用、主线ID
    │   ├── chapter_2.json
    │   └── chapter_3.json
    ├── cards/
    │   ├── monsters.json      ← 怪物卡片库
    │   ├── npcs.json          ← NPC卡片库
    │   └── treasures.json     ← 宝箱卡片库
    └── main_stories/
        ├── act_1.json         ← 第1章主线（main_story 类型卡片）
        ├── act_2.json
        └── ending.json
```

**切换故事只需更改加载的目录名称，引擎代码零修改。**

### meta.json 格式

```json
{
  "id":    "dark_forest",
  "title": "黑暗森林",
  "ai_system_prompt": "你是一个黑暗奇幻世界的旁白者，风格阴郁神秘...",
  "language": "zh",
  "nav_hints": {
    "monster":  "前方隐约传来动静",
    "npc":      "远处似乎有人影晃动",
    "treasure": "地面有什么东西在反光"
  }
}
```

### chapters.json 格式

```json
{
  "story_id": "dark_forest",
  "chapters": ["chapter_1", "chapter_2", "chapter_3"]
}
```

### chapter_N.json 格式

```json
{
  "id":           "chapter_1",
  "name":         "迷失之林",
  "map_size":     { "rows": 5, "cols": 5 },
  "card_pool":    ["monsters", "npcs", "treasures"],
  "main_story_id":"act_1"
}
```

---

## 九、引擎对外接口（函数签名）

```python
class GameEngine:
    def load_story(self, story_id: str) -> None
    # 加载故事包，读取 meta、chapters、cards 到内存

    def new_game(self, story_id: str) -> GameState
    # 创建新游戏，生成第1章地图，返回初始状态

    def get_nav_context(self, state: GameState) -> NavContext
    # 返回导航上下文：当前位置、可选方向、各方向卡片 title+type

    def move_player(self, state: GameState, direction: str) -> MoveResult
    # direction: "right" / "down" / "diagonal"
    # 返回：新状态 + 进入卡片的场景描述（或触发主线）

    def process_card_input(self, state: GameState, player_input: str, ai_response: dict) -> CardResult
    # ai_response 由上层 AI 模块调用后传入，格式：{"npc_response": str, "judge": str}
    # 返回：新状态 + 是否卡片结束 + 结算信息

    def apply_effects(self, state: GameState, effects: list) -> GameState
    # 执行 effects 列表，更新 stats，检查 hp≤0 游戏结束

# NavContext 结构
{
  "current_pos": [2, 3],
  "options": [
    { "direction": "right",    "card_title": "神秘商人", "card_type": "npc" },
    { "direction": "down",     "card_title": "哥布林斥候", "card_type": "monster" },
    { "direction": "diagonal", "card_title": "古老宝箱", "card_type": "treasure" }
  ]
}

# MoveResult 结构
{
  "new_state":         GameState,
  "card_scene":        "你走入昏暗的树林...",
  "triggered_main_story": false
}

# CardResult 结构
{
  "new_state":    GameState,
  "card_done":    true,
  "outcome":      "win",
  "effects_log":  ["gold +3"],
  "game_over":    false
}
```

---

## 十、文件结构

```
module-3-game-rules/
├── CLAUDE.md              ← 本文件（设计文档）
├── engine.py              ← 主引擎：地图管理、移动、主线触发
├── card_runner.py         ← 卡片副本：对话流程、效果结算
├── navigator.py           ← 导航上下文：可选方向、卡片标题提取
├── stats.py               ← 统一数值系统：apply_effects、死亡判定
└── stories/
    └── dark_forest/       ← 示例故事包（用于测试，可完整替换）
        ├── meta.json
        ├── chapters.json
        ├── chapters/
        │   ├── chapter_1.json
        │   └── chapter_2.json
        ├── cards/
        │   ├── monsters.json
        │   ├── npcs.json
        │   └── treasures.json
        └── main_stories/
            ├── act_1.json
            └── ending.json
```
