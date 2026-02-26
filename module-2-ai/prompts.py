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
# 数值字段中文名映射（英文 key → 中文显示名）
# 注入 Prompt 时使用中文名，避免 AI 将英文字段名输出到旁白
# ──────────────────────────────────────────────

STAT_NAMES_CN = {
    "gold":   "金币",
    "bread":  "面包",
    "sword":  "利剑",
    "rope":   "绳索",
    "torch":  "火把",
    "key":    "钥匙",
    "amulet": "护符",
    "merit":  "功德",
    "cash":   "现金",
    "exp":    "经验",
}

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
        # 使用中文名显示（避免英文 key 被 AI 直接输出到旁白文字中）
        cn_name = STAT_NAMES_CN.get(key, key)
        parts.append(f"{cn_name}: {value}")

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

    # ── 格式化场景情况（不含方向词，不含人名）──
    # 将每个可选方向转换为"一件事/一个情况"，由 AI 融合进场景描述
    # 不暴露方向词（右/下/斜），不暴露 NPC 名字，玩家通过描述的事件来选择
    # 重要：card_title 可能包含 NPC 名字（如 "Pharan"），
    #       绝对不能传入 Prompt，否则 AI 会在旁白中复述该名字
    directions_text_lines = []
    for idx, d in enumerate(directions):
        card_type = d.get("card_type", "")
        hint = nav_hints.get(card_type, "那里有些不寻常")
        # 用匿名序号代替卡片标题，避免 AI 看到人名后复述
        directions_text_lines.append(f"- 事件{idx + 1}：{hint}")

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
        f"- 【严格禁止】旁白和选项中不得出现任何人物名字、角色名、NPC名、称呼（如'长老''商人''Pharan'等），"
        f"一律用感官描述代替（如'一个模糊的身影''某种低沉的声音'），违反此条即为错误输出\n"
        f"- 用感官细节（声音、气味、光影、温度、震动）暗示每件事的存在\n"
        f"- 不得在旁白文字中出现任何数值、数字或状态词（如护符、现金、功德等）\n"
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
        f"- 若玩家连续2轮或以上没有做出有意义的行动（沉默、无关输入、敷衍），应判定为失败\n"
        f"- 胜利（judge=win）需要至少经过2轮有效互动，不在第1轮就判定胜利\n"
        f"- 根据玩家当前状态自然调整角色态度（详见系统提示中的数值影响说明）\n"
        f"- 同时判断当前局面是否达成胜利或失败条件\n"
        f"- 若已到最大轮数且未分胜负，根据当前局面偏向做出最终判断\n"
        f"- judge=continue 时，必须在 options 提供3个具体行动选项（5-8字，站在玩家视角描述可采取的行动）\n"
        f"- judge=win 或 lose 时，npc_response 必须是收尾性的最终反应（如灵体消散/离去/态度转变/事件终结），让玩家清楚感受到这段遭遇已经结束；不能仍是进行中的对话\n"
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

def build_direction_parse_prompt(
    player_input: str,
    options: list[dict],
    nav_option_hints: list[dict] = None,
) -> list[dict]:
    """
    构建方向意图解析 Prompt，让 AI 理解玩家输入对应哪个方向。

    当关键词匹配失败时调用（玩家输入自然语言，如"我要回家"、"去找那个人"等）。
    AI 根据语义推断玩家最可能想去哪个场景，只返回方向标识。

    注意：游戏中没有"左右上下"等方向词，所有选项都是故事场景，
    玩家可能用情绪化语言或与选项语义相近但措辞不同的表达。
    有疑问时倾向于选最合理的选项，只有完全无法匹配才返回 unknown。

    参数：
        player_input      — 玩家的自然语言输入
        options           — 当前可选方向列表，每项含 direction、card_title、card_type
        nav_option_hints  — 旁白渲染的选项文字 [{direction, text}]，
                            有了这个 AI 能语义匹配（"我想离开"→"迅速离开此地"→方向）

    返回：
        OpenAI messages 格式
    """
    # 构建选项描述（显示旁白选项文字 + 事件标题）
    hint_map = {h["direction"]: h["text"] for h in (nav_option_hints or [])}
    options_lines = []
    for o in options:
        direction = o.get("direction", "")
        title = o.get("card_title", "未知")
        hint_text = hint_map.get(direction, "")
        if hint_text:
            options_lines.append(f"- [{direction}] 选项：「{hint_text}」")
        else:
            options_lines.append(f"- [{direction}] 场景：「{title}」")

    options_text = "\n".join(options_lines) if options_lines else "- （无可选方向）"

    return [
        {
            "role": "system",
            "content": (
                "你是一个游戏意图解析器。玩家用自然语言描述自己想做什么，"
                "你需要判断他最可能想去哪个场景。\n"
                "游戏里没有方向词（不存在左/右/上/下），只有故事场景可以前往。\n"
                "玩家可能用情绪、口语或与选项语义相近的表达，你要理解语义再匹配。\n"
                "特殊情况处理：\n"
                "- 玩家表示'随便'、'都行'、'无所谓'、'随意'时，选第一个场景\n"
                "- 玩家表示想'离开'、'走'、'回避'时，选逃离感最强的场景\n"
                "- 玩家表示想'靠近'、'查看'、'调查'某个事物时，选最相关的场景\n"
                "只能输出以下之一，不得有任何其他文字：\n"
                "right / down / diagonal\n"
                "（必须选一个，游戏不允许停在原地）"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前可前往的场景：\n{options_text}\n\n"
                f"玩家说：{player_input!r}\n\n"
                "玩家最可能想去哪个场景？必须输出一个对应标识（right/down/diagonal）："
            ),
        },
    ]
