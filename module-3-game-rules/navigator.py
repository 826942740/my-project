# navigator.py — 导航上下文计算
# 负责计算当前位置可以往哪些方向走，以及各方向的卡片信息
# 类比：地图导航 App，告诉玩家前方有什么（但只说隐晦提示，不直接说类型）

from __future__ import annotations  # 兼容 Python 3.9 的联合类型注解


def get_nav_context(state: dict, map_cards: dict, map_size: dict) -> dict:
    """
    计算当前位置的可选移动方向和各方向的卡片信息

    移动规则（只能向前，不能回头）：
        - 向右     → (行, 列+1)
        - 向下     → (行+1, 列)
        - 斜右下   → (行+1, 列+1)
        - 超出边界的方向不可选

    at_boundary 含义：当前位置已在最后一行或最后一列，说明主线应已触发，
    玩家此时不应再导航（引擎层面会拦截，这里只是信息字段）

    参数：
        state:     GameState 字典，含 position [row, col]
        map_cards: {"行,列": card_id} 格式的地图卡片分配
        map_size:  {"rows": 5, "cols": 5} 地图总大小

    返回 NavContext 字典，例如：
    {
        "current_pos": [2, 3],
        "options": [
            {"direction": "right",    "card_title": "神秘商人",   "card_type": "npc",      "card_id": "old_merchant"},
            {"direction": "down",     "card_title": "哥布林斥候", "card_type": "monster",  "card_id": "goblin_patrol"},
            {"direction": "diagonal", "card_title": "古老宝箱",   "card_type": "treasure", "card_id": "ancient_chest"}
        ],
        "at_boundary": False
    }
    """
    # 获取当前坐标
    row, col = state["position"]
    total_rows = map_size["rows"]
    total_cols = map_size["cols"]

    # 三个可能的移动方向及对应的坐标偏移
    candidate_directions = [
        ("right",    row,     col + 1),   # 向右
        ("down",     row + 1, col),       # 向下
        ("diagonal", row + 1, col + 1),   # 斜右下
    ]

    options = []

    for direction, new_row, new_col in candidate_directions:
        # 检查是否超出地图边界（坐标从 1 开始）
        if new_row > total_rows or new_col > total_cols:
            continue

        # 从地图卡片分配中查找该格子的 card_id
        pos_key = f"{new_row},{new_col}"
        card_id = map_cards.get(pos_key)

        # 如果该格子没有分配卡片（理论上不应发生，但做防御处理）
        if card_id is None:
            card_title = "未知区域"
            card_type = "unknown"
        else:
            # card_id 格式为 "card_id"，title 和 type 需要从外部传入
            # 这里只返回 card_id，由 engine 层补充 title 和 type
            card_title = card_id   # 占位，engine 会替换
            card_type = "unknown"  # 占位，engine 会替换

        options.append({
            "direction": direction,
            "card_title": card_title,
            "card_type": card_type,
            "card_id": card_id,
        })

    # 判断当前位置是否已在边界（已到最后一行或最后一列）
    at_boundary = (row >= total_rows or col >= total_cols)

    return {
        "current_pos": [row, col],
        "options": options,
        "at_boundary": at_boundary,
    }


def parse_direction(player_input: str, options: list) -> str | None:
    """
    从玩家自然语言输入中解析移动方向

    解析优先级：
        1. 关键词匹配（右/right/东、下/down/南、斜/diagonal/斜右/右下）
        2. 如果只有一个可选方向，默认选那个
        3. 无法解析返回 None

    类比：问"你往哪走"，玩家说"往右"或"走东边"，都能识别

    参数：
        player_input: 玩家输入的自然语言文字
        options:      当前可选方向列表（get_nav_context 返回的 options 字段）

    返回：
        "right" / "down" / "diagonal" / None
    """
    if not options:
        return None

    # 提取当前可用的方向集合（只从合法方向中匹配）
    available_directions = {opt["direction"] for opt in options}

    # 将输入转为小写，方便匹配
    text = player_input.lower().strip()

    # 关键词映射表：方向 → 匹配关键词列表
    direction_keywords = {
        "right":    ["右", "right", "东", "east", "向右", "往右", "右边", "右方"],
        "down":     ["下", "down", "南", "south", "向下", "往下", "下方", "下边"],
        "diagonal": ["斜", "diagonal", "右下", "斜右", "斜右下", "东南", "southeast", "斜向", "斜方"],
    }

    # 优先级1：关键词匹配
    for direction, keywords in direction_keywords.items():
        if direction not in available_directions:
            # 该方向在当前位置不可选，跳过
            continue
        for keyword in keywords:
            if keyword in text:
                return direction

    # 优先级2：只有一个选项时，默认选它
    if len(options) == 1:
        return options[0]["direction"]

    # 无法解析
    return None
