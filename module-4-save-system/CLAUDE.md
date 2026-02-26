# 模块 4：存档系统

## 模块职责

负责玩家游戏进度的持久化存储。保证用户关闭浏览器后再回来，能从上次离开的地方继续游戏。
同时管理 session（会话身份），不需要用户注册账号。

---

## 技术约束

- Python，作为 FastAPI 后端的一个子模块
- 存储引擎：SQLite（单文件，零配置，方便部署）
- 不需要登录/注册，用 `session_token` 识别用户身份
- `session_token` 由后端生成，前端存在 `localStorage`

---

## 一、Session 机制

```
浏览器 localStorage["session_token"] = "abc123xyz"
         ↕ 每次 API 请求都带上这个 token
服务器 SQLite → sessions 表 → 找到对应的 GameState
```

- Token 格式：UUID4（32位随机字符串，服务器生成）
- Token 无有效期，永久有效（除非主动删除）
- 支持**换设备继续游戏**：通过存档码（6位短码）在新设备恢复 token

---

## 二、GameState 数据结构

存档就是 GameState 对象，序列化为 JSON 存入数据库。
结构由模块3定义，模块4负责原样保存和读取，不做任何修改：

```json
{
  "story_id":    "dark_forest",
  "chapter_idx": 0,
  "position":    [2, 3],
  "in_card":     "goblin_patrol",
  "card_round":  2,
  "card_history": [
    { "role": "player", "content": "我大声呵斥它离开" },
    { "role": "npc",    "content": "哥布林愣了一下…" }
  ],
  "stats": {
    "hp":     80,
    "hp_max": 100,
    "gold":   30,
    "bread":  2,
    "sword":  1
  },
  "map_cards": {
    "1,1": "village_start",
    "1,2": "old_merchant",
    "2,3": "goblin_patrol"
  },
  "visited":          [[1,1],[1,2],[2,2],[2,3]],
  "main_story_done":  [0]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `story_id` | 当前游玩的故事包 ID |
| `chapter_idx` | 当前章节索引（0开始） |
| `position` | 当前格子坐标 `[行, 列]` |
| `in_card` | 当前所在卡片的 ID，`null` 表示导航阶段 |
| `card_round` | 当前卡片已进行的对话轮数 |
| `card_history` | 当前卡片的对话历史（卡片结束后清空） |
| `stats` | 玩家所有数值（统一扁平字典） |
| `map_cards` | 本章地图各格子的卡片分配 `"行,列": "card_id"` |
| `visited` | 已访问的格子坐标列表 |
| `main_story_done` | 已完成的章节主线索引列表 |

---

## 三、数据库表结构

```sql
-- 会话表：每个玩家一条记录
CREATE TABLE sessions (
    token       TEXT     PRIMARY KEY,
    story_id    TEXT     NOT NULL,
    game_state  TEXT     NOT NULL,     -- JSON 格式的 GameState
    short_code  TEXT     UNIQUE,       -- 6位换设备用的短码
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_sessions_short_code ON sessions(short_code);
```

**设计说明：**
- 对话历史存储在 `game_state` 的 `card_history` 字段内，不单独建表
- 每次存档只需更新 `game_state` 和 `updated_at` 两个字段
- 表结构保持最简，降低维护成本

---

## 四、存档码（换设备用）

玩家需要在新设备继续游戏时使用：

```
生成：服务器为 session 生成一个 6位大写字母+数字的短码（如 "A3X7KM"）
      → 存入 sessions.short_code
      → 返回给前端显示

恢复：玩家在新设备输入短码
      → POST /api/session/resume { "code": "A3X7KM" }
      → 服务器查询 short_code 找到对应 token
      → 返回 token 给新设备，存入 localStorage
```

- 短码是 token 的别名，不替换 token 本身
- 短码只生成一次，不会变化（除非玩家主动刷新）

---

## 五、存档读写策略

- **自动保存**：每次玩家行动（导航移动 / 卡片对话）完成后自动保存
- **无手动存档槽位**：每个 token 只有一个存档（当前进度）
- **无存档版本迁移**：GameState 结构变化时，旧存档视为无效，提示开始新游戏

---

## 六、对外暴露的接口

```python
class SaveSystem:

    def create_session(self, story_id: str) -> tuple[str, str]
    # 创建新 session，返回 (token, short_code)

    def load_game(self, token: str) -> dict | None
    # 读取存档，返回 GameState 字典；token 不存在返回 None

    def save_game(self, token: str, state: dict) -> None
    # 保存/更新存档（自动更新 updated_at）

    def session_exists(self, token: str) -> bool
    # 检查 token 是否存在

    def get_token_by_code(self, short_code: str) -> str | None
    # 通过短码查询 token，不存在返回 None

    def get_short_code(self, token: str) -> str | None
    # 获取 token 对应的短码（没有则生成一个）
```

---

## 七、FastAPI 路由

```
POST /api/session/new
  Body: { "story_id": "dark_forest" }
  Response: { "token": "uuid...", "initial_state": GameState }

GET  /api/state?token=xxx
  Response: { "token_valid": true, "state": GameState }

POST /api/session/resume
  Body: { "code": "A3X7KM" }
  Response: { "token": "uuid...", "state": GameState }

GET  /api/session/code?token=xxx
  Response: { "short_code": "A3X7KM" }
```

---

## 八、文件结构

```
module-4-save-system/
├── CLAUDE.md          ← 本文件
├── session.py         # SaveSystem 类，存档读写逻辑
├── models.py          # 数据库连接和表操作
└── schema.sql         # 建表 SQL（用于初始化数据库）
```
