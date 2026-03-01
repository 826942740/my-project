# 模块 3：规则引擎（module-3-game-rules）

## 模块职责
- 读取故事包配置并管理游戏状态。
- 管理章节地图、移动规则、卡牌进入与章节推进。
- 提供日常生活阶段所需章节提示词。

## 当前实现（As-Is）
### 核心引擎能力
代码位置：`module-3-game-rules/engine.py`
- `new_game(story_id)`：初始化 GameState。
- `generate_map_cards(chapter)`：按章节卡池生成地图卡牌。
- `get_nav_context(state)`：返回可走方向 + 目标卡信息。
- `move_player(state, direction)`：移动并进入卡牌。
- `advance_chapter(state)`：主线胜利后推进章节。
- `get_daily_life_prompt(state)`：读取章节 `daily_life_prompt`。

### 地图与移动
- 起点固定 `(1,1)`。
- 仅允许 `right/down/diagonal`。
- 到达最后一行或最后一列触发本章主线卡（`main_story_id`）。

### 章节卡池控制
- `chapter.card_pool`：决定可抽取类型。
- `chapter.card_blacklist`：章节级黑名单过滤（已实现）。

## 对外接口/输入输出
引擎对后端提供（由 `backend/main.py` 调用）：
- 新建状态、导航上下文、移动结果、章节推进、日常提示词。

关键状态字段（当前真实字段）：
- `daily_life_phase`
- `daily_life_round`
- `daily_life_total`
- `daily_life_history`
- `daily_life_config`

## 关键流程
1. `new_game` 读取 `meta/chapters/cards/main_stories`。
2. 进入地图后每次移动都会写入 `visited` 并设置 `in_card`。
3. 卡片结束后由后端决定是否进入日常；引擎提供章节级 `daily_life_prompt`。
4. 主线卡胜利后调用 `advance_chapter`：
- 有下一章：重置到新章 `(1,1)`。
- 无下一章：设置 `game_cleared=True`。

## 终章/通关条件（按现有配置）
- 每章最终关卡由 `chapters/chapter_N.json` 的 `main_story_id` 决定。
- khemjira 当前映射：
  - `chapter_1 -> act_1`
  - `chapter_2 -> act_2`
  - `chapter_3 -> act_3`
  - `chapter_4 -> ending`
- 通关前提：玩家触发并完成当前章主线卡（胜利裁决）后才推进下一章；最后一章推进后 `game_cleared=True`。

## 已知限制与风险
- 章节 JSON 若格式不规范，会影响启动加载或章节行为。
- `available_cards` 为空时使用 `unknown_card` 兜底，说明内容配置可能缺失。
- 本模块不负责 AI 文本格式稳定，文本协议问题需在 `module-2-ai` 与前后端接口层处理。

## 调试与排查
- 首查：`engine.py::new_game/generate_map_cards/move_player/advance_chapter`。
- 配置查验：
  - `stories/<story_id>/chapters/*.json`
  - `stories/<story_id>/cards/*.json`
  - `stories/<story_id>/main_stories/*.json`
- 常见问题：
  1. 不该出现的角色卡出现：检查 `card_blacklist` 与卡池类型。
  2. 章节不推进：检查主线卡 `judge` 与 `outcome==win` 是否成立。
