# 模块 2：后端 AI 调用

## 模块职责

负责与 AI 大模型 API 通信。在游戏中扮演三个不同角色，生成叙事文字和处理对话。
**不负责**任何游戏逻辑判断——数值变化、胜负结算全部由模块3完成。

---

## 技术约束

- Python，作为 FastAPI 后端的一个子模块
- 使用 OpenAI 兼容格式 API（支持 DeepSeek / Claude / GPT / 本地模型，只改配置不改代码）
- API endpoint、model 名称、API key 全部通过**环境变量**配置，不写入代码
- 支持普通输出（先出完整结果再返回）

---

## 一、AI 的三个角色

游戏中 AI 负责三件事，每件事对应一套 Prompt 模板：

| 角色 | 触发时机 | 输入 | 输出 |
|------|---------|------|------|
| **导航旁白** | 玩家完成卡片，准备选择下一步 | 相邻格子的卡片 title + type | 一段叙事提示，暗示各方向情况 |
| **卡片 NPC** | 玩家在卡片内输入文字 | 玩家输入 + NPC 性格 + 对话历史 | NPC 的回应文字 |
| **卡片裁判** | 每轮对话后 | 当前对话 + 胜负判定标准 | `{"npc_response": "...", "judge": "continue/win/lose"}` |

> **卡片 NPC 和卡片裁判合并为同一次 API 调用**，AI 同时返回 NPC 回应文字和胜负判断。

---

## 二、Prompt 模板

所有 Prompt 模板从剧情包的 `meta.json` 中读取基础设定，由 `prompts.py` 动态组装。

### 2.1 导航旁白 Prompt

```
[系统]
你是《{story_title}》世界的旁白者。{ai_system_prompt}
语言：{language}，输出不超过80字。

[规则]
- 根据给定的相邻方向信息，生成一段简短的环境描述，暗示各方向的情况
- 不直接说出卡片类型（不说"前面有怪物"），而是用感官描述（声音、气味、光线）
- 在描述末尾用一句话询问玩家想往哪里走

[上下文]
玩家当前位置：第{chapter_name}，坐标 ({row}, {col})
玩家状态：{stats_summary}

相邻方向信息：
{directions}
（示例格式：右方 → 类型:monster 标题:哥布林斥候 / 下方 → 类型:npc 标题:神秘商人）

[任务]
生成导航旁白。
```

**卡片类型 → 感官提示映射**（来自 `meta.json` 的 `nav_hints`）：
```json
{
  "monster":  "前方隐约传来动静",
  "npc":      "远处似乎有人影晃动",
  "treasure": "地面有什么东西在反光"
}
```

---

### 2.2 卡片 NPC + 裁判 Prompt（合并调用）

```
[系统]
你是《{story_title}》世界中的角色扮演者和裁判。{ai_system_prompt}
语言：{language}

你现在要同时扮演角色并判断结果，必须返回严格的 JSON 格式，不得有多余文字。

[角色设定]
角色名：{npc_name}
性格：{npc_personality}
当前场景：{scene_description}

[胜利条件]：{win_judge}
[失败条件]：{lose_judge}
[最大轮数]：{max_rounds}，当前第 {current_round} 轮

[对话历史]
{dialogue_history}

[规则]
- 以角色身份回应玩家，符合角色性格
- 同时判断当前局面
- 必须返回 JSON，格式如下：

{
  "npc_response": "角色的回应文字（1-3句）",
  "judge": "continue 或 win 或 lose",
  "judge_reason": "一句话说明判断理由（内部调试用，不显示给玩家）"
}

[玩家输入]
{player_input}
```

---

## 三、输出格式规范

### 导航旁白

纯文本，80字以内，以问句结尾：
```
夜风中，右边的灌木丛传来细碎的脚步声，而下方的小径尽头隐约有橙色的火光。你打算往哪边走？
```

### 卡片 NPC + 裁判（必须是合法 JSON）

```json
{
  "npc_response": "哥布林愣了一下，手中的短刀微微颤抖，慢慢向后退了一步。",
  "judge": "continue",
  "judge_reason": "玩家的呵斥让哥布林动摇，但尚未完全离开"
}
```

`judge` 取值：
- `continue` — 继续对话，未分胜负
- `win` — 玩家达成胜利条件
- `lose` — 玩家触发失败条件

---

## 四、上下文管理

### 对话历史格式

```json
[
  { "role": "player", "content": "我大声呵斥它离开" },
  { "role": "npc",    "content": "哥布林愣了一下，慢慢后退…" },
  { "role": "player", "content": "我继续逼近，不给它机会" }
]
```

- 对话历史存储在 GameState 的 `card_history` 字段中（由模块4负责持久化）
- 每次调用将完整历史传入 Prompt
- 卡片结束后历史清空，不跨卡片保留

### Stats 摘要格式（注入 Prompt 用）

```python
# 示例："HP: 80/100, 金币: 30, 面包: 2"
def format_stats_summary(stats: dict) -> str
```

---

## 五、API 调用配置

通过环境变量配置，不写入代码：

```bash
# .env 文件（不提交到 git）
AI_API_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=sk-xxx
AI_MODEL=deepseek-chat
AI_MAX_TOKENS=500
AI_TEMPERATURE=0.8
AI_TIMEOUT_SECONDS=30
```

### 错误处理策略

| 错误类型 | 处理方式 |
|---------|---------|
| 网络超时 | 最多重试1次，失败返回降级文本 |
| JSON 解析失败（裁判返回格式错误） | 重试一次，附加"必须返回JSON"强调；再失败则默认 `continue` |
| Rate limit | 等待3秒后重试一次 |
| 其他错误 | 记录日志，返回降级静态文本，不中断游戏 |

### 降级文本（AI 完全失败时的兜底）

```python
FALLBACK_NARRATIVE = "（叙事加载失败，请重试）"
FALLBACK_NPC_RESPONSE = {"npc_response": "...", "judge": "continue"}
```

---

## 六、文件结构

```
module-2-ai/
├── CLAUDE.md          ← 本文件
├── client.py          # OpenAI 兼容 API 客户端封装，处理重试和错误
└── prompts.py         # Prompt 模板组装：build_nav_prompt / build_card_prompt
```

### client.py 接口

```python
class AIClient:
    def call(self, messages: list[dict], expect_json: bool = False) -> str
    # messages: OpenAI 格式的消息列表
    # expect_json=True 时，解析失败会自动重试并附加 JSON 要求
    # 返回：AI 生成的文本（已去除首尾空白）
```

### prompts.py 接口

```python
def build_nav_prompt(meta: dict, chapter_name: str, position: tuple,
                     stats: dict, directions: list[dict]) -> list[dict]
# 返回 OpenAI messages 格式

def build_card_prompt(meta: dict, card: dict, stats: dict,
                      dialogue_history: list[dict],
                      player_input: str, current_round: int) -> list[dict]
# 返回 OpenAI messages 格式
```
