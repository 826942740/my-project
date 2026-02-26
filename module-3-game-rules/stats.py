# stats.py — 统一数值系统
# 负责处理玩家所有数值（HP、金币、物品等）的变化
# 所有数值用同一扁平字典存储，格式：{"hp": 80, "gold": 30, "bread": 2}
# 新增任意属性直接加 key，引擎无需改代码


def apply_effects(stats: dict, effects: list) -> dict:
    """
    执行 effects 列表，返回更新后的 stats 副本（不修改原始字典）

    effects 格式示例：
        [{"stat": "hp", "delta": -10}, {"stat": "gold", "delta": 5}]

    类比：把玩家背包/状态的变化清单逐条执行一遍

    参数：
        stats:   当前玩家数值字典
        effects: 效果列表，每项包含 stat（属性名）和 delta（变化量）

    返回：
        更新后的新数值字典（原字典不被修改）
    """
    # 复制一份，避免直接修改原始状态
    new_stats = dict(stats)

    for effect in effects:
        stat_key = effect.get("stat")
        delta = effect.get("delta", 0)

        if stat_key is None:
            # 忽略格式不对的效果项
            continue

        # 如果该属性还不存在，从 0 开始累加
        current_value = new_stats.get(stat_key, 0)
        new_stats[stat_key] = current_value + delta

    return new_stats


def is_dead(stats: dict) -> bool:
    """
    检查玩家是否死亡

    判定规则：hp 字段存在，且 hp <= 0

    如果故事没有 hp（比如纯文字冒险），永远返回 False，不会误判死亡

    参数：
        stats: 当前玩家数值字典

    返回：
        True 表示死亡，False 表示存活
    """
    if "hp" not in stats:
        # 没有 HP 字段，视为不死亡
        return False

    return stats["hp"] <= 0


def format_effects_log(effects: list) -> list:
    """
    将 effects 格式化为人类可读的字符串列表

    例如：
        [{"stat": "hp", "delta": -10}, {"stat": "gold", "delta": 3}]
        → ["hp -10", "gold +3"]

    正数加号显示，负数直接显示负号，方便玩家看结算信息

    参数：
        effects: 效果列表

    返回：
        可读字符串列表，如 ["hp -10", "gold +3", "sword +1"]
    """
    log_lines = []

    for effect in effects:
        stat_key = effect.get("stat")
        delta = effect.get("delta", 0)

        if stat_key is None:
            continue

        # 正数前加 "+"，负数自带 "-" 号
        if delta >= 0:
            log_lines.append(f"{stat_key} +{delta}")
        else:
            log_lines.append(f"{stat_key} {delta}")

    return log_lines
