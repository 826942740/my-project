"""
prompts.py — Prompt 模板组装

负责将游戏状态数据组装成 OpenAI messages 格式，供 AIClient.call() 使用。

提供两个主要函数：
  - build_nav_prompt()   导航旁白 Prompt（玩家选择下一步方向时）
  - build_card_prompt()  卡片 NPC + 裁判合并 Prompt（玩家在卡片内对话时）

以及一个辅助函数：
  - format_stats_summary()  将 stats 字典格式化为简短文字
"""

import json

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
    stats: dict,
    directions: list[dict],
    last_card_context: dict = None,
    last_daily_life_context: dict = None,
) -> list[dict]:
    """
    构建导航旁白 Prompt，返回 OpenAI messages 格式。

    导航旁白：玩家完成卡片后，准备选择下一步方向时触发。
    AI 根据相邻格子的卡片信息，生成旁白并给出可选行动。
    返回严格 JSON，避免前端再从自然语言里猜测选项格式。

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
    # 不暴露方向词（右/下/斜），不暴露卡片类型，玩家通过描述的事件来选择
    # NPC名字可以出现在旁白中（增加代入感），但不能出现数值/方向词
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

    # ── 组装系统提示（System Prompt）──
    system_content = (
        f"你是《{story_title}》世界的旁白者。{ai_system_prompt}\n"
        f"语言：{language}"
    )

    # ── 构建前情上下文段落（日常生活上下文优先于卡片上下文）──
    # 日常生活系统已经处理了时间过渡，导航只需从日常结尾衔接
    prev_section = ""
    has_daily_context = False

    if last_daily_life_context:
        # 日常阶段刚结束：从日常最后的不安预兆自然过渡
        has_daily_context = True
        daily_narrative = last_daily_life_context.get("last_narrative", "")
        daily_input = last_daily_life_context.get("last_player_input", "")
        prev_section = (
            f"[日常生活刚刚结束]\n"
            f"Khem最后做的事：{daily_input}\n"
            f"日常最后的叙事（以不安预兆收尾）：\n{daily_narrative}\n\n"
        )
    elif last_card_context:
        # 无日常上下文（游戏开头/主线后），用卡片上下文兜底
        prev_title   = last_card_context.get("card_title", "上一段遭遇")
        prev_outcome = "胜利" if last_card_context.get("outcome") == "win" else "失败"
        prev_section = (
            f"[刚刚结束的遭遇]\n"
            f"遭遇名称：{prev_title}，结果：{prev_outcome}\n\n"
        )

    # ── 根据是否有日常上下文，选择不同的第1段写作指示 ──
    if has_daily_context:
        para1_instruction = (
            f"  第1段：衔接过渡——参考[日常生活刚刚结束]的内容，"
            f"第一句必须从「Khem最后做的事」起笔，写出这个行动之后她的即时状态，"
            f"然后从日常最后的不安预兆自然延伸，"
            f"用1-2句写出我重新面对前方未知时的身体反应和心理转变\n"
        )
    else:
        para1_instruction = (
            f"  第1段：时间过渡——用2-3句带过上次遭遇后我这几天的普通生活细节"
            f"（上课、打工、吃路边摊、在宿舍发呆等曼谷学生日常），"
            f"让读者感受时间在流逝；如果有[刚刚结束的遭遇]，"
            f"第一句必须从那段经历的情绪余韵起笔，再过渡到日常\n"
        )

    # ── 组装用户提示（User Prompt）──
    user_content = (
        f"{prev_section}"
        f"[上下文]\n"
        f"当前位置：{chapter_name}\n"
        f"玩家状态：{stats_summary}\n"
        f"\n"
        f"当前场景中可以感知到的事：\n"
        f"{directions_text}\n"
        f"\n"
        f"[写作规则]\n"
        f"- 不提方向词（不说右/左/上/下/斜），不说出卡片类型\n"
        f"- 不得出现任何数值、数字或状态词（护符、现金、功德等）\n"
        f"- 全程使用第一人称叙事，只能使用「我/我的」作为主语\n"
        f"- 禁止使用「你/她/Khem」作为叙事主语\n"
        f"- 将场景中可感知的几件事融入描写，用感官细节（气味、声音、光影、温度、触感）暗示它们的存在，不直接点名\n"
        f"- 用我的身体反应表达情绪（后颈发凉、胃在下沉、手心出汗），不用「我感到恐惧」这类直白描述\n"
        f"- options 中每个行动选项必须是纯行动短句，禁止任何序号/编号/字母前缀（禁止 A. / B. / 1. / I. / 一、等）\n"
        f"- options 违规示例：\"A. 靠近查看\"、\"1) 立刻离开\"、\"I. keep moving\"、\"一、回头观察\"\n"
        f"- options 正确示例：\"靠近门口听动静\"、\"先停下观察四周\"、\"给Jet发消息确认\"\n"
        f"\n"
        f"[格式要求]\n"
        f"必须返回严格 JSON（无代码块、无额外说明），格式如下：\n"
        f'{{\n'
        f'  "narrative": "场景描述（分3段）",\n'
        f'  "options": ["放慢脚步听动静", "沿人群方向快步走", "给Jet发消息确认"]\n'
        f'}}\n'
        f"\n"
        f"其中 narrative 必须严格按以下结构展开：\n"
        f"{para1_instruction}"
        f"  第2段：环境铺陈——用多种感官描写我当前所在位置的具体氛围（街道名称、气温、声音层次、气味混合），写出当前环境的质感\n"
        f"  第3段：悬念引入——将场景中可感知的几件事自然呈现，以我某个细微的身体反应收尾，留悬念，不做解释\n"
        f"  每一段至少出现一次第一人称代词（我/我的）\n"
        f"  若出现「你/她/Khem」作为叙事主语，视为不合格输出\n"
        f"  务必结合之前发生的故事，与用户的输入进行内容生成。\n"
        f"options 数量必须为 {len(directions)} 个，且每项都不得带任何编号前缀。"
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
          "npc_response": "角色的回应文字",
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
        f"- 你是“剧情叙述者 + 裁判”，不是必须每轮都以角色台词回应\n"
        f"- npc_response 必须直接承接玩家本轮具体行动，先写“行动造成的可见结果”，再写局势变化；禁止无视玩家输入自行推进\n"
        f"- npc_response 以叙事为主：通过环境、身体反应、动作反馈推动剧情，不要求每轮出现对白\n"
        f"- 只有当该对象本身具备“可交流意图”（人类/可说话实体）时，才可加入简短对白；若是怪异现象/非言语实体，使用声音、痕迹、温度、气味、光影、触感等非对白反馈\n"
        f"- 感官细节为必选项：至少包含 2 种感官维度（声音/温度/气味/触感/视觉变化），且与玩家行动直接相关\n"
        f"- 胜利（judge=win）需要至少经过2轮有效互动，不在第1轮就判定胜利\n"
        f"- 根据玩家当前状态自然调整角色态度（详见系统提示中的数值影响说明）\n"
        f"- 同时判断当前局面是否达成胜利或失败条件\n"
        f"- 若已到最大轮数且未分胜负，根据当前局面偏向做出最终判断\n"
        f"- judge=continue 时，必须在 options 提供3个具体行动选项（5-8字，站在玩家视角描述可采取的行动）；选项必须紧扣当前 npc_response 的内容和局面，分别代表三个不同策略方向（如：对抗/安抚/回避，或进攻/谈判/逃跑），禁止给出与当前场景无关的通用选项\n"
        f"- options 每项必须是纯文本行动短句，禁止任何编号或序号前缀（A./B./C./1./I./一、等）\n"
        f"- options 违规示例：\"A. 继续压迫它\"、\"2. step back\"、\"I. ask again\"、\"一、先道歉\"\n"
        f"- options 正确示例：\"稳住呼吸继续对视\"、\"后撤半步观察反应\"、\"换方式试探它底线\"\n"
        f"- judge=win 或 lose 时，npc_response 必须是收尾性的最终反应（如灵体消散/离去/态度转变/事件终结），让玩家清楚感受到这段遭遇已经结束；不能仍是进行中的对话\n"
        f"- judge=win 或 lose 时，options 设为空数组 []\n"
        f"- 必须返回 JSON，格式如下（无多余文字，无代码块标记）：\n"
        f"\n"
        f'{{\n'
        f'  "npc_response": "角色的回应文字（必须包含感官细节和氛围渲染，通过身体动作、声音、环境变化体现角色性格）,必须结合交互历史，用户输出进行内容生成。",\n'
        f'  "judge": "continue 或 win 或 lose",\n'
        f'  "judge_reason": "一句话说明判断理由（内部调试用，不显示给玩家）",\n'
        f'  "options": ["稳住呼吸继续逼问", "后退半步重新观察", "改用安抚语气试探"]\n'
        f'}}'
    )

    # ── 构建 messages 列表 ──
    messages = [{"role": "system", "content": system_content}]

    # ── Few-shot 示例：展示正确的 JSON 输出格式 ──
    # 帮助模型记住"必须返回 JSON"，同时锚定有感官细节、有氛围层次的写作风格
    messages.append({"role": "user", "content": "（示例输入）我大声呵斥它离开"})
    messages.append({
        "role": "assistant",
        "content": (
            '{"npc_response": "空气骤然凝固，那团黑烟被你的声音激怒，边缘开始剧烈颤抖，'
            '发出低沉的嗡鸣，像是有什么东西在皮肤下拼命挣扎。'
            '温度骤然下降，你呼出的气在空气中凝成白雾，鼻腔里涌入一股焦糊的腐败气息。'
            '它没有后退，反而向你倾斜，两个空洞的眼窝中涌出更浓的黑烟，'
            '声音从四面八方同时传来，带着碎裂的回响——\'再说一次。\'",'
            ' "judge": "continue",'
            ' "judge_reason": "玩家展示了对抗意志，但尚未满足胜利条件",'
            ' "options": ["保持气势，再次呵斥", "退后一步，压制恐惧", "转移话题，观察它的反应"]}'
        ),
    })

    # ── 将对话历史转换为 OpenAI messages 格式 ──
    # player → user（玩家的输入）
    # npc    → assistant（包装为 JSON 格式，与 few-shot 示例保持一致）
    # 关键修复：历史中 NPC 回应是纯文本，但 few-shot 示例是 JSON 格式，
    # 格式不一致会导致 AI 忽略对话上下文，生成与玩家输入无关的内容
    for entry in dialogue_history:
        role = entry.get("role", "")
        content = entry.get("content", "")

        if role == "player":
            messages.append({"role": "user", "content": content})
        elif role == "npc":
            # 将纯文本 NPC 回应包装为 JSON 格式，与 few-shot 示例格式一致
            json_wrapped = json.dumps({
                "npc_response": content,
                "judge": "continue",
                "judge_reason": "对话继续中",
                "options": []
            }, ensure_ascii=False)
            messages.append({"role": "assistant", "content": json_wrapped})
        # 其他未知 role 跳过，避免 API 报错

    # ── 追加玩家本轮输入作为最后一条 user 消息（加强调包装）──
    messages.append({
        "role": "user",
        "content": (
            f"Khem的行动：{player_input}\n\n"
            f"请以角色身份直接回应这个行动。"
        ),
    })

    return messages


# ──────────────────────────────────────────────
# 卡片入场叙事 Prompt（进入卡片时的过渡描述）
# ──────────────────────────────────────────────

def build_card_entry_prompt(
    meta: dict,
    card: dict,
    stats: dict,
    player_choice_text: str,
    last_card_context: dict = None,
) -> list[dict]:
    """
    构建卡片入场叙事 Prompt。

    玩家选择了某个方向进入卡片后，AI 基于玩家的行动和遭遇内容，
    生成一段自然衔接的入场描述，将导航情景过渡到卡片遭遇。
    如果有上一张卡片的上下文，同时结合其结局和对话内容，确保故事逻辑连贯。

    参数：
        meta               — 故事包 meta.json 内容
        card               — 当前卡片完整配置
        stats              — 玩家当前状态
        player_choice_text — 玩家刚才选择的行动文字（如"靠近橙色灯光处"）
        last_card_context  — 上一张卡片的上下文（可选），格式：
                             {"card_title": str, "outcome": "win"/"lose", "history": [...]}

    返回：
        OpenAI messages 格式
    """
    story_title = meta.get("title", "未知故事")
    ai_system_prompt = meta.get("ai_system_prompt", "")
    language = meta.get("language", "zh")

    # 场景参考：提供给 AI 作为遭遇内容的参考，但不要求照搬
    scene_ref = card.get("scene_description", "")

    system_content = (
        f"你是《{story_title}》世界的旁白者。{ai_system_prompt}\n"
        f"语言：{language}"
    )

    # ── 构建上一张卡片的上下文段落（可选）──
    # 有上文时，引导 AI 从上一段遭遇的结局自然过渡到新场景
    prev_section = ""
    if last_card_context:
        prev_title   = last_card_context.get("card_title", "上一段遭遇")
        prev_outcome = "胜利" if last_card_context.get("outcome") == "win" else "失败"
        prev_history = last_card_context.get("history", [])
        history_lines = "\n".join(
            f"{'玩家' if m['role'] == 'player' else '对方'}：{m['content']}"
            for m in prev_history
        )
        prev_section = (
            f"[刚刚结束的遭遇]\n"
            f"遭遇名称：{prev_title}，结果：{prev_outcome}\n"
            f"最后几轮对话：\n{history_lines}\n\n"
        )

    user_content = (
        f"{prev_section}"
        f"[玩家的行动]\n"
        f"「{player_choice_text}」\n\n"
        f"[即将遭遇的场景（仅供参考，不要照搬文字）]\n"
        f"{scene_ref}\n\n"
        f"[规则]\n"
        f"- 写入场叙述，从玩家刚才的经历和行动自然过渡到当前遭遇场景\n"
        f"- 如果有刚结束的遭遇，必须让前后故事逻辑连贯（不能让刚发生的事凭空消失）\n"
        f"- 对环境、气味、温度等感知细节进行生动描写，体现故事氛围\n"
        f"- 不照搬场景参考的文字，用自己的语言重新呈现\n"
        f"- 只写纯叙事，不写行动选项，不用问句结尾\n"
        f"- 不提任何数值（护符值、功德、现金等）"
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_content},
    ]


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


# ──────────────────────────────────────────────
# 日常生活叙事 Prompt（事件卡间的互动式日常过渡）
# ──────────────────────────────────────────────

def build_daily_life_prompt(
    meta: dict,
    chapter_daily_prompt: str,
    stats: dict,
    last_card_context: dict = None,
    daily_history: list = None,
    player_input: str = None,
    current_round: int = 1,
    total_rounds: int = 3,
) -> list[dict]:
    """
    构建日常生活叙事 Prompt，返回 OpenAI messages 格式。

    事件卡结束后，玩家进入"日常生活阶段"，连续体验几轮日常叙事。
    每轮 AI 生成一段日常场景描写 + 3 个行动选项，玩家选择或自由输入。
    第一轮必须从刚结束的事件余韵起笔，最后一轮以不安预兆收尾。

    参数：
        meta                — 故事包 meta.json 内容（世界观 + 角色设定）
        chapter_daily_prompt — 当前章节的日常生活写作指导（场景、人物、基调）
        stats               — 玩家当前 stats 字典
        last_card_context   — 刚结束的卡片上下文（可选）：
                              {"card_title": str, "outcome": "win"/"lose", "history": [...]}
        daily_history       — 日常阶段已有的对话历史：
                              [{"role": "narrator"/"player", "content": "..."}]
        player_input        — 玩家本轮输入（第一轮为 None）
        current_round       — 当前轮数（从 1 开始）
        total_rounds        — 总轮数

    返回：
        OpenAI messages 格式

    AI 必须返回的 JSON 格式：
        {
          "narrative": "日常叙事文字",
          "options": ["行动选项1（5-10字）", "行动选项2", "行动选项3"]
        }
    """
    # ── 从 meta 中读取基础信息 ──
    story_title = meta.get("title", "未知故事")
    ai_system_prompt = meta.get("ai_system_prompt", "")
    language = meta.get("language", "zh")

    # ── 格式化 stats 摘要 ──
    stats_summary = format_stats_summary(stats)

    # ── 判断是否为最后一轮 ──
    is_last_round = (current_round >= total_rounds)

    # ── 组装系统提示 ──
    system_content = (
        f"你是《{story_title}》的叙事者，负责讲述主角 Khem 在超自然事件之间的日常生活。"
        f"{ai_system_prompt}\n"
        f"语言：{language}\n"
        f"\n"
        f"你必须返回严格的 JSON 格式，不得有多余文字。\n"
        f"\n"
        f"[本章日常生活指导]\n"
        f"{chapter_daily_prompt}\n"
        f"\n"
        f"[玩家状态]\n"
        f"{stats_summary}\n"
        f"\n"
        f"[规则]\n"
        f"- 第二人称「你」指代 Khem，叙事中自然提及她的身份细节\n"
        f"- 用身体反应表达情绪（后颈发凉、手心出汗、胃在下沉），不用「她感到恐惧」这类直白描述\n"
        f"- 根据玩家当前数值自然调整叙事基调（护符值低→夜里总醒、功德高→心态稍安），不直接说出数字\n"
        f"- 每轮写一个不同的日常场景，不要和前几轮重复\n"
        f"- 【核心规则】叙事必须直接回应玩家的最新行动。无论玩家选了预设选项还是自由输入（包括出格/荒谬的行为），叙事开头就要写这个行动的过程，然后展开后果和周围人的反应。禁止无视玩家输入而编造与之无关的场景\n"
        f"- [开场去模板规则（高优先级）]\n"
        f"- 叙事首句禁止使用固定“你+动作”模板开头（如：你点点头… / 你转头… / 你忽然站起…）\n"
        f"- 若首句与 recent history（最近3轮 narrator 首句）在句式或动词组合上高度相似，视为不合格输出，必须重写\n"
        f"- 首句必须在以下4类开场中轮换，且不能与上一轮同类：\n"
        f"  1) 环境先行（先写地点/声音/气味/光线，再落到人物）\n"
        f"  2) 感官先行（先写身体感受/生理反应，再落到行动）\n"
        f"  3) 对话先行（先给一句现场对话或提示音，再展开）\n"
        f"  4) 动作先行（人物动作起手，但不得用“你点点头/你转头/你忽然…”这类高频模板）\n"
        f"- 与最近2轮相比，首句不得复用相同动作词组（点头/转头/站起/摩挲护符/压低声音等）\n"
        f"- 若玩家输入是选项文本（短句），首句必须把该输入转化为“具体场景中的可见行为+即时后果”，而不是复述原句\n"
        f"- 如果玩家输入了不合理/出格的行为，在故事逻辑内合理处理（Khem可以尝试但不一定成功，周围人物按性格自然反应），不要假装没发生\n"
        f"- 日常场景素材列表仅供参考，不要直接照搬素材原文作为选项，narrative 叙事必须围绕玩家的实际输入展开，不要自行从列表中挑选场景来写\n"
        f"- narrative 中不要写行动选项，选项单独放在 options 字段\n"
        f"- options 必须紧扣刚生成的 narrative 内容，从当前叙事中自然延伸出三个不同方向的后续行动（如：社交/独处/探索，或面对/回避/求助），禁止给出与当前叙事无关的通用日常选项\n"
        f"- options 每项必须是纯文本行动短句，禁止任何编号或序号前缀（A./B./C./1./I./一、等）\n"
        f"- options 违规示例：\"A. 去便利店\"、\"1) call Jet\"、\"I.继续观察\"、\"一、回宿舍\"\n"
        f"- options 正确示例：\"去便利店买热饮\"、\"给Jet发语音说明\"、\"回宿舍先洗把脸\"\n"
        f"- 必须返回 JSON，格式如下（无多余文字，无代码块标记）：\n"
        f"\n"
        f'{{\n'
        f'  "narrative": "日常叙事文字（多用感官细节，分2-3段）",\n'
        f'  "options": ["去便利店买热饮", "给Jet发语音说明", "回宿舍先洗把脸"]\n'
        f'}}'
    )

    # ── 构建 messages 列表 ──
    messages = [{"role": "system", "content": system_content}]

    # ── 构建用户提示（上下文 + 当前轮数信息）──
    # 第一轮：包含刚结束的事件上下文
    context_parts = []

    if current_round == 1 and last_card_context:
        prev_title = last_card_context.get("card_title", "上一段遭遇")
        prev_outcome = "胜利" if last_card_context.get("outcome") == "win" else "失败"
        prev_history = last_card_context.get("history", [])
        # 取最后几轮对话作为参考
        history_lines = "\n".join(
            f"{'玩家' if m['role'] == 'player' else '对方'}：{m['content']}"
            for m in prev_history[-4:]  # 最多取最后4条
        )
        context_parts.append(
            f"[刚刚结束的遭遇]\n"
            f"遭遇名称：{prev_title}，结果：{prev_outcome}\n"
            f"最后几轮对话：\n{history_lines}\n"
        )

    context_parts.append(f"[当前进度] 日常生活第 {current_round} 轮 / 共 {total_rounds} 轮")

    if is_last_round:
        context_parts.append(
            "[特别指示] 这是日常阶段的最后一轮。"
            "开场优先使用“感官先行”。"
            "叙事结尾用一个微妙的不安细节收尾——某种不对劲的感觉、"
            "一个说不清楚的预兆，暗示平静即将被打破。"
            "仍然在 options 中提供3个行动选项（玩家还需要做最后一次选择）。"
        )
    elif current_round == 1 and last_card_context:
        context_parts.append(
            "[特别指示] 这是日常阶段的第一轮。"
            "开场优先使用“环境先行”或“感官先行”。"
            "叙事必须从刚结束的遭遇的情绪余韵起笔——"
            "那件事刚发生不久，Khem还没有完全从中走出来，"
            "然后自然过渡到日常生活的场景。"
        )
    else:
        context_parts.append(
            "[特别指示] 这是日常阶段的中间轮。"
            "优先“生活细节+关系互动”，避免连续两轮都以人物动作起手。"
        )

    initial_user_content = "\n\n".join(context_parts)
    messages.append({"role": "user", "content": initial_user_content})

    # ── 将日常对话历史转换为 messages 格式 ──
    # narrator → assistant（AI 的叙事）
    # player   → user（玩家的选择）
    for entry in (daily_history or []):
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role == "narrator":
            messages.append({"role": "assistant", "content": content})
        elif role == "player":
            messages.append({"role": "user", "content": content})

    # ── 玩家本轮输入：作为最后一条 user 消息，并强调 AI 必须回应 ──
    if player_input:
        messages.append({
            "role": "user",
            "content": (
                f"Khem的行动：{player_input}\n\n"
                f"请直接从这个行动展开叙事，描写具体过程和后果。"
            ),
        })

    return messages
