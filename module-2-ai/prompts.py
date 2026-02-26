"""
prompts.py — Prompt 模板组装

负责将游戏状态数据组装成 OpenAI messages 格式，供 AIClient.call() 使用。

提供两个主要函数：
  - build_nav_prompt()   导航旁白 Prompt（玩家选择下一步方向时）
  - build_card_prompt()  卡片 NPC + 裁判合并 Prompt（玩家在卡片内对话时）

以及一个辅助函数：
  - format_stats_summary()  将 stats 字典格式化为简短文字
"""

# ──────────────────────────────────────────────
# 方向中文映射（英文方向名 → 中文显示）
# ──────────────────────────────────────────────

# 将代码中的英文方向名转为 Prompt 里的中文方向提示
DIRECTION_CN = {
    "right":    "右方",
    "down":     "下方",
    "diagonal": "右下方",
    # 兼容可能出现的其他写法
    "left":     "左方",
    "up":       "上方",
}


# ──────────────────────────────────────────────
# 辅助函数：stats 格式化
# ──────────────────────────────────────────────

def format_stats_summary(stats: dict) -> str:
    """
    将 stats 字典格式化为简短的文字摘要，注入 Prompt 时使用。

    规则（让 AI 能快速读懂玩家状态）：
      - 有 hp 和 hp_max 时，显示为 "HP: 80/100"
      - 有 hp 但无 hp_max 时，显示为 "HP: 80"
      - 其余字段直接显示 "字段名: 值"
      - 跳过 hp_max（已合并到 HP 显示中）
      - 值为 0 的字段也显示（方便 AI 感知玩家状态）

    示例输出：
      "HP: 80/100, 金币: 30, 面包: 2"
    """
    if not stats:
        return "（无状态数据）"

    parts = []

    # ── 优先处理 HP，合并 hp/hp_max ──
    if "hp" in stats:
        if "hp_max" in stats:
            parts.append(f"HP: {stats['hp']}/{stats['hp_max']}")
        else:
            parts.append(f"HP: {stats['hp']}")

    # ── 处理其余字段（跳过已处理的 hp 和 hp_max）──
    skip_keys = {"hp", "hp_max"}
    for key, value in stats.items():
        if key in skip_keys:
            continue
        # 将 key 直接显示（配置文件里的 key 就是业务名称，如 gold、bread、sword）
        parts.append(f"{key}: {value}")

    return ", ".join(parts) if parts else "（无状态数据）"


# ──────────────────────────────────────────────
# 导航旁白 Prompt
# ──────────────────────────────────────────────

def build_nav_prompt(
    meta: dict,
    chapter_name: str,
    position: tuple,
    stats: dict,
    directions: list[dict],
) -> list[dict]:
    """
    构建导航旁白 Prompt，返回 OpenAI messages 格式。

    导航旁白：玩家完成卡片后，准备选择下一步方向时触发。
    AI 根据相邻格子的卡片信息，生成不超过 80 字的环境描述，
    用感官语言（声音、气味、光线）暗示各方向情况，以问句结尾。

    参数：
        meta         — 故事包的 meta.json 内容
        chapter_name — 当前章节名称，例如 "第一章：黑暗森林"
        position     — 当前坐标 (row, col)，例如 (2, 3)
        stats        — 玩家当前 stats 字典
        directions   — 可选方向列表，格式如下：
                       [
                         {"direction": "right", "card_title": "神秘商人", "card_type": "npc"},
                         {"direction": "down",  "card_title": "哥布林斥候", "card_type": "monster"},
                       ]

    返回：
        OpenAI messages 格式的列表 [{"role": "system", "content": "..."}, ...]
    """
    # ── 从 meta 中读取基础信息 ──
    story_title = meta.get("title", "未知故事")
    ai_system_prompt = meta.get("ai_system_prompt", "")
    language = meta.get("language", "zh")

    # nav_hints：卡片类型 → 感官提示映射（由故事包配置，不硬编码）
    # 默认值兜底，防止 meta.json 未配置时报错
    nav_hints = meta.get("nav_hints", {
        "monster":      "前方隐约传来动静",
        "npc":          "远处似乎有人影晃动",
        "treasure":     "地面有什么东西在反光",
        "main_story":   "前路散发着异样的气息",
    })

    # ── 格式化场景情况（不含方向词）──
    # 将每个可选方向转换为"一件事/一个情况"，由 AI 融合进场景描述
    # 不暴露方向词（右/下/斜），玩家通过描述的事件来选择
    directions_text_lines = []
    for d in directions:
        card_title = d.get("card_title", "未知")
        card_type = d.get("card_type", "")
        hint = nav_hints.get(card_type, "那里有些不寻常")
        # 格式："- 神秘商人：远处似乎有人影晃动"
        directions_text_lines.append(f"- {card_title}：{hint}")

    directions_text = "\n".join(directions_text_lines) if directions_text_lines else "（周围没有可前进的方向）"

    # ── 格式化 stats 摘要 ──
    stats_summary = format_stats_summary(stats)

    # ── 格式化坐标 ──
    row, col = position if len(position) >= 2 else (0, 0)

    # ── 组装系统提示（System Prompt）──
    system_content = (
        f"你是《{story_title}》世界的旁白者。{ai_system_prompt}\n"
        f"语言：{language}，输出不超过80字。"
    )

    # ── 组装用户提示（User Prompt）──
    user_content = (
        f"[规则]\n"
        f"- 将下方列出的几件事自然地融合进一段场景描述，让玩家感受到不止一个选择\n"
        f"- 不提方向词（不说右/左/上/下/斜），不说出卡片类型\n"
        f"- 用感官细节（声音、气味、光影、温度、震动）暗示每件事的存在\n"
        f"- 场景描述后，必须严格按照以下格式列出 {len(directions)} 个选项（禁止使用加粗**、斜杠/、序号1.2.等其他任何格式）：\n"
        f"  A. 行动文字\n"
        f"  B. 行动文字\n"
        f"  C. 行动文字（如有第三项）\n"
        f"- 选项文字要简洁（5-10字），描述玩家的行动而非方向\n"
        f"\n"
        f"[上下文]\n"
        f"玩家当前位置：{chapter_name}，坐标 ({row}, {col})\n"
        f"玩家状态：{stats_summary}\n"
        f"\n"
        f"当前场景可以关注的事：\n"
        f"{directions_text}\n"
        f"\n"
        f"[任务]\n"
        f"生成场景描述 + 行动选项（总字数不超过120字）。"
    )

    # ── 返回 OpenAI messages 格式 ──
    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_content},
    ]


# ──────────────────────────────────────────────
# 卡片 NPC + 裁判合并 Prompt
# ──────────────────────────────────────────────

def build_card_prompt(
    meta: dict,
    card: dict,
    stats: dict,
    dialogue_history: list[dict],
    player_input: str,
    current_round: int,
) -> list[dict]:
    """
    构建卡片 NPC + 裁判合并 Prompt，返回 OpenAI messages 格式。

    卡片阶段：玩家在卡片副本内自由对话时触发。
    AI 同时扮演 NPC 并做出胜负判断，返回严格 JSON 格式。

    参数：
        meta             — 故事包的 meta.json 内容
        card             — 当前卡片的完整配置（含 npc 字段）
                           card["npc"] 包含：name, personality, win_judge, lose_judge, max_rounds
        stats            — 玩家当前 stats 字典
        dialogue_history — 完整对话历史列表：
                           [{"role": "player"/"npc", "content": "..."}]
        player_input     — 玩家本轮输入文字
        current_round    — 当前轮数（从 1 开始）

    返回：
        OpenAI messages 格式的列表，包含：
          - system 消息：角色设定 + 胜负条件 + 输出格式要求
          - 历史对话（player → user, npc → assistant）
          - 最后一条 user 消息：玩家本轮输入

    AI 必须返回的 JSON 格式：
        {
          "npc_response": "角色的回应文字（1-3句）",
          "judge": "continue 或 win 或 lose",
          "judge_reason": "一句话说明判断理由（内部调试用）"
        }
    """
    # ── 从 meta 中读取基础信息 ──
    story_title = meta.get("title", "未知故事")
    ai_system_prompt = meta.get("ai_system_prompt", "")
    language = meta.get("language", "zh")

    # ── 从卡片配置中读取 NPC 信息 ──
    npc_config = card.get("npc", {})
    npc_name = npc_config.get("name", "未知角色")
    npc_personality = npc_config.get("personality", "")
    win_judge = npc_config.get("win_judge", "（未配置胜利条件）")
    lose_judge = npc_config.get("lose_judge", "（未配置失败条件）")
    max_rounds = npc_config.get("max_rounds", 10)

    # 卡片的场景描述（卡片进入时的场景文字）
    scene_description = card.get("scene_description", "")

    # ── 格式化 stats 摘要 ──
    stats_summary = format_stats_summary(stats)

    # ── 组装系统提示（System Prompt）──
    # 包含：世界背景 + 角色设定 + 胜负条件 + 轮数 + 输出格式要求
    system_content = (
        f"你是《{story_title}》世界中的角色扮演者和裁判。{ai_system_prompt}\n"
        f"语言：{language}\n"
        f"\n"
        f"你现在要同时扮演角色并判断结果，必须返回严格的 JSON 格式，不得有多余文字。\n"
        f"\n"
        f"[角色设定]\n"
        f"角色名：{npc_name}\n"
        f"性格：{npc_personality}\n"
        f"当前场景：{scene_description}\n"
        f"\n"
        f"[玩家状态]\n"
        f"{stats_summary}\n"
        f"\n"
        f"[胜利条件]：{win_judge}\n"
        f"[失败条件]：{lose_judge}\n"
        f"[最大轮数]：{max_rounds}，当前第 {current_round} 轮\n"
        f"\n"
        f"[规则]\n"
        f"- 以角色身份回应玩家，符合角色性格\n"
        f"- 根据玩家当前状态自然调整角色态度（详见系统提示中的数值影响说明）\n"
        f"- 同时判断当前局面是否达成胜利或失败条件\n"
        f"- 若已到最大轮数且未分胜负，根据当前局面偏向做出最终判断\n"
        f"- judge=continue 时，必须在 options 提供3个具体行动选项（5-8字，站在玩家视角描述可采取的行动）\n"
        f"- judge=win 或 lose 时，options 设为空数组 []\n"
        f"- 必须返回 JSON，格式如下（无多余文字，无代码块标记）：\n"
        f"\n"
        f'{{\n'
        f'  "npc_response": "角色的回应文字（1-3句）",\n'
        f'  "judge": "continue 或 win 或 lose",\n'
        f'  "judge_reason": "一句话说明判断理由（内部调试用，不显示给玩家）",\n'
        f'  "options": ["行动选项1（5-8字）", "行动选项2", "行动选项3"]\n'
        f'}}'
    )

    # ── 构建 messages 列表 ──
    messages = [{"role": "system", "content": system_content}]

    # ── Few-shot 示例：展示正确的 JSON 输出格式 ──
    # 帮助模型记住"必须返回 JSON"，避免只输出旁白文字
    messages.append({"role": "user", "content": "（示例输入）我大声呵斥它离开"})
    messages.append({
        "role": "assistant",
        "content": (
            '{"npc_response": "它愣了一下，慢慢向后退了一步，眼神中带着困惑。",'
            ' "judge": "continue",'
            ' "judge_reason": "玩家开始对抗但尚未达成胜利条件",'
            ' "options": ["继续保持气势逼近", "轻声安抚，转换策略", "退后一步观察反应"]}'
        ),
    })

    # ── 将对话历史转换为 OpenAI messages 格式 ──
    # player → user（玩家的输入）
    # npc    → assistant（NPC 的回应）
    for entry in dialogue_history:
        role = entry.get("role", "")
        content = entry.get("content", "")

        if role == "player":
            messages.append({"role": "user", "content": content})
        elif role == "npc":
            messages.append({"role": "assistant", "content": content})
        # 其他未知 role 跳过，避免 API 报错

    # ── 追加玩家本轮输入作为最后一条 user 消息 ──
    messages.append({"role": "user", "content": player_input})

    return messages


# ──────────────────────────────────────────────
# 方向意图解析 Prompt（关键词匹配失败时的 AI 兜底）
# ──────────────────────────────────────────────

def build_direction_parse_prompt(player_input: str, options: list[dict]) -> list[dict]:
    """
    构建方向意图解析 Prompt，让 AI 理解玩家输入对应哪个方向。

    当关键词匹配失败时调用（例如玩家输入"往有动静的地方走"、"朝哭声的方向"等）。
    AI 只需返回一个单词：right / down / diagonal / unknown，不得有任何其他文字。

    参数：
        player_input — 玩家的自然语言输入
        options      — 当前可选方向列表，每项含 direction、card_title、card_type

    返回：
        OpenAI messages 格式
    """
    # 格式化可选选项（用事件标题对应方向，不显示方向词给 AI 解读）
    options_lines = []
    for o in options:
        title = o.get("card_title", "未知")
        options_lines.append(f"- [{o['direction']}] 对应事件：「{title}」")

    options_text = "\n".join(options_lines) if options_lines else "- （无可选方向）"

    return [
        {
            "role": "system",
            "content": (
                "你是一个游戏意图解析器，根据玩家描述的行动，判断玩家想去哪个事件。\n"
                "只能输出以下之一，不得有任何其他文字：\n"
                "right / down / diagonal / unknown"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前场景可选事件：\n{options_text}\n\n"
                f"玩家输入：{player_input!r}\n\n"
                "判断玩家最可能想去哪个事件，输出对应的方向标识（right/down/diagonal/unknown）："
            ),
        },
    ]
