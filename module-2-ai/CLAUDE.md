# 模块 2：AI（module-2-ai）

## 模块职责
- 组装各阶段 Prompt。
- 封装 OpenAI 兼容调用。
- 在 `expect_json=True` 时提供 JSON 输出兜底与重试。

## 当前实现（As-Is）
### Prompt 入口
- `build_nav_prompt()`：导航旁白生成。
- `build_card_prompt()`：卡片 NPC + 裁决（JSON）。
- `build_card_entry_prompt()`：入场叙事。
- `build_direction_parse_prompt()`：方向意图解析。
- `build_daily_life_prompt()`：日常叙事（JSON）。

代码位置：`module-2-ai/prompts.py`

### AIClient 行为
代码位置：`module-2-ai/client.py`
- `AIClient.call(messages, expect_json=False)`：基础调用。
- `expect_json=True` 时：
  1. 优先尝试 `response_format={"type":"json_object"}`。
  2. 非法 JSON 时 `_ensure_json()` 提取或重试一次。
  3. 仍失败抛出异常由上层兜底。

## 对外接口/输入输出
对 `backend/main.py` 暴露：
- `build_*_prompt` 一组函数。
- `AIClient.call()`。

JSON 约束链路（当前已生效）：
- 卡片：`/api/card_action` 使用 `expect_json=True` + `json.loads`。
- 日常：`/api/daily_life` 使用 `expect_json=True` + `json.loads`。

## 关键流程
1. 后端构建阶段 prompt。
2. `AIClient.call()` 调用模型。
3. 卡片/日常链路强制 JSON 校验。
4. 后端按结构字段继续规则处理。

## 已知限制与风险
### 导航协议不一致（重点）
- `build_nav_prompt()` 当前要求模型输出严格 JSON（`narrative + options`）。
- 但后端 `/api/nav` 未按 JSON 解析，前端导航也仍按文本正则取选项。
- 这会导致导航输出协议与下游实现不一致。

### 输出稳定性（当前策略）
- 已在 prompt 层约束：
  - `options` 禁止编号/序号前缀。
  - 导航叙事第一人称约束。
  - 日常开场去模板规则（首句轮换、历史去重指令）。
- 当前不做后端强制清洗，属于“软约束”。

## 调试与排查
- 首查 `module-2-ai/client.py` 日志：
  - 是否触发 `_ensure_json` 重试。
  - 是否因 provider 不支持 `response_format` 自动降级。
- 再查 `module-2-ai/prompts.py`：
  - 输出 schema 是否与后端消费字段一致。
  - 是否混入了与当前链路不兼容的格式要求。
- 若仅导航异常，优先对照：
  - `build_nav_prompt()` 与
  - `backend/main.py::generate_nav_narrative()` / `game.js::renderNavNarrative()`。
