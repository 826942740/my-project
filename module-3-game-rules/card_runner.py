# card_runner.py — 卡片副本流程管理
# 负责处理玩家进入卡片后的完整交互流程
# 类比：每张卡片是一个小关卡，玩家进去后要和 NPC 交谈直到分出胜负

from __future__ import annotations  # 兼容 Python 3.9 的联合类型注解
from stats import apply_effects, is_dead, format_effects_log


def start_card(card: dict) -> dict:
    """
    初始化一张卡片的运行状态

    类比：开始一个新关卡，一切从零开始（轮数归零，对话历史清空）

    参数：
        card: 卡片配置字典（来自 cards/*.json）

    返回：
        卡片初始运行状态字典
        {
            "card_id": "goblin_patrol",
            "round": 0,
            "history": []
        }
    """
    return {
        "card_id": card["id"],
        "round": 0,
        "history": [],
    }


def process_card_turn(state: dict, card: dict, player_input: str, ai_response: dict) -> dict:
    """
    处理卡片内的一轮对话，返回处理结果

    流程：
        1. 将玩家输入追加到 card_history（角色：player）
        2. 将 AI/NPC 回应追加到 card_history（角色：npc）
        3. card_round + 1
        4. 判断结果：
            - judge == "win"  → 执行 win_effects，结束卡片
            - judge == "lose" → 执行 lose_effects，结束卡片
            - card_round >= card.max_rounds 且 judge == "continue" → 强制 lose
            - 否则继续对话
        5. 结算时：apply_effects，清空 in_card / card_round / card_history

    ai_response 格式：
        {
            "npc_response": "哥布林龇牙咧嘴地后退了一步...",
            "judge": "continue",          # continue / win / lose
            "judge_reason": "玩家尚未..."  # 裁判理由（可选，供调试用）
        }

    参数：
        state:        当前 GameState 字典
        card:         卡片配置字典
        player_input: 玩家本轮输入
        ai_response:  AI 模块返回的字典

    返回 CardResult 字典：
        {
            "new_state":   GameState（更新后），
            "card_done":   True/False（卡片是否结束）,
            "outcome":     "win" / "lose" / "continue",
            "effects_log": ["gold +3"],  （仅结算时有值）
            "game_over":   True/False（HP <= 0 则游戏结束）
        }
    """
    # ── 第一步：深拷贝状态，避免修改原始数据 ──────────────────────────────
    import copy
    new_state = copy.deepcopy(state)

    # ── 第二步：追加本轮对话到历史记录 ────────────────────────────────────
    npc_response = ai_response.get("npc_response", "")
    judge = ai_response.get("judge", "continue")

    # 追加玩家输入
    new_state["card_history"].append({
        "role": "player",
        "content": player_input,
    })

    # 追加 NPC 回应
    new_state["card_history"].append({
        "role": "npc",
        "content": npc_response,
    })

    # ── 第三步：轮数 +1 ───────────────────────────────────────────────────
    new_state["card_round"] = new_state.get("card_round", 0) + 1
    current_round = new_state["card_round"]
    max_rounds = card.get("max_rounds", 5)

    # ── 第四步：判断是否需要强制失败（超出最大轮数）─────────────────────
    if judge == "continue" and current_round >= max_rounds:
        # 回合数耗尽，强制失败
        judge = "lose"

    # ── 第五步：根据判断结果决定是否结算 ─────────────────────────────────
    if judge in ("win", "lose"):
        # 选取对应的效果列表
        if judge == "win":
            effects = card.get("win_effects", [])
        else:
            effects = card.get("lose_effects", [])

        # 执行数值结算（更新 stats）
        new_state["stats"] = apply_effects(new_state["stats"], effects)

        # 生成结算日志（给玩家看的变化说明）
        effects_log = format_effects_log(effects)

        # 检查是否死亡
        game_over = is_dead(new_state["stats"])

        # 清空卡片状态（退出卡片副本）
        new_state["in_card"] = None
        new_state["card_round"] = 0
        new_state["card_history"] = []

        return {
            "new_state": new_state,
            "card_done": True,
            "outcome": judge,
            "effects_log": effects_log,
            "game_over": game_over,
        }

    else:
        # judge == "continue"，继续对话
        return {
            "new_state": new_state,
            "card_done": False,
            "outcome": "continue",
            "effects_log": [],
            "game_over": False,
        }


def load_card(card_id: str, cards_data: dict) -> dict | None:
    """
    从 cards_data 中查找并返回 card_id 对应的卡片配置

    cards_data 是引擎内存中所有卡片的合并字典，格式：
        {"goblin_patrol": {...}, "old_merchant": {...}, ...}

    参数：
        card_id:    要查找的卡片唯一标识
        cards_data: 全部卡片的字典（key 为 card_id）

    返回：
        卡片配置字典，找不到返回 None
    """
    return cards_data.get(card_id, None)
