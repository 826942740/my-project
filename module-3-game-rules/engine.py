# engine.py — 游戏主引擎
# 负责加载故事、管理地图状态、处理移动和主线触发
# 引擎与内容完全分离：所有故事数据来自 stories/ 目录配置文件
# 更换故事只需换目录名，引擎代码零修改

from __future__ import annotations  # 兼容 Python 3.9 的联合类型注解
from pathlib import Path
import json
import random
import copy

# 导入子模块（使用相对导入，无论从哪里 import 都能正常工作）
from .navigator import get_nav_context as _get_nav_context
from .card_runner import process_card_turn, load_card
from .stats import apply_effects, is_dead, format_effects_log

# 故事包根目录（相对于本文件）
STORIES_DIR = Path(__file__).parent / "stories"


class GameEngine:
    """
    游戏主引擎类

    类比：这是游戏的"裁判兼主持人"，负责：
        - 读取故事配置（加载地图、卡片、规则）
        - 处理玩家移动（判断方向合法性、触发主线）
        - 调用卡片流程（处理副本内的每轮对话）
        - 更新玩家状态数值

    引擎本身不包含任何故事内容，内容全部来自 stories/ 配置文件
    """

    def __init__(self):
        # 当前加载的故事包数据（load_story 后填充）
        self.story = None

        # 所有卡片的合并字典，格式：{card_id: card 配置}
        # 包含 monsters、npcs、treasures、main_stories 的所有卡片
        self.cards_pool = {}

    # ─────────────────────────────────────────────────────────────────────────
    # 故事包加载
    # ─────────────────────────────────────────────────────────────────────────

    def load_story(self, story_id: str) -> None:
        """
        加载故事包，将所有配置读取到内存

        读取内容：
            meta.json       → 故事基本信息、AI 提示词模板、导航提示模板
            chapters.json   → 章节列表顺序
            chapters/*.json → 各章节配置（地图大小、卡片池、主线 ID）
            cards/*.json    → 各类卡片库（monsters、npcs、treasures）
            main_stories/*.json → 各章节主线卡片

        加载完成后：
            self.story["meta"]           = meta.json 内容
            self.story["chapters_list"]  = 章节 ID 列表
            self.story["chapters"]       = {chapter_id: chapter 配置}
            self.story["main_stories"]   = {story_id: main_story 配置}
            self.cards_pool              = {card_id: 卡片配置}（所有类型合并）

        参数：
            story_id: 故事目录名，对应 stories/<story_id>/
        """
        story_dir = STORIES_DIR / story_id

        if not story_dir.exists():
            raise FileNotFoundError(f"故事包目录不存在：{story_dir}")

        self.story = {}
        self.cards_pool = {}

        # ── 读取 meta.json ────────────────────────────────────────────────
        meta_path = story_dir / "meta.json"
        with open(meta_path, encoding="utf-8") as f:
            self.story["meta"] = json.load(f)

        # ── 读取 chapters.json ────────────────────────────────────────────
        chapters_path = story_dir / "chapters.json"
        with open(chapters_path, encoding="utf-8") as f:
            chapters_config = json.load(f)
        self.story["chapters_list"] = chapters_config["chapters"]

        # ── 逐一读取各章节配置 ────────────────────────────────────────────
        self.story["chapters"] = {}
        chapters_dir = story_dir / "chapters"

        for chapter_id in self.story["chapters_list"]:
            chapter_path = chapters_dir / f"{chapter_id}.json"
            with open(chapter_path, encoding="utf-8") as f:
                chapter_data = json.load(f)
            self.story["chapters"][chapter_id] = chapter_data

        # ── 读取所有卡片库（cards/ 目录下所有 json 文件）────────────────
        cards_dir = story_dir / "cards"

        if cards_dir.exists():
            for card_file in cards_dir.glob("*.json"):
                with open(card_file, encoding="utf-8") as f:
                    card_list = json.load(f)

                # 每个卡片文件是一个列表，将所有卡片按 id 存入 cards_pool
                for card in card_list:
                    self.cards_pool[card["id"]] = card

        # ── 读取所有主线故事（main_stories/ 目录下所有 json 文件）────────
        self.story["main_stories"] = {}
        main_stories_dir = story_dir / "main_stories"

        if main_stories_dir.exists():
            for story_file in main_stories_dir.glob("*.json"):
                with open(story_file, encoding="utf-8") as f:
                    main_story = json.load(f)

                story_key = main_story["id"]
                self.story["main_stories"][story_key] = main_story

                # 主线也加入 cards_pool（主线是特殊卡片）
                self.cards_pool[story_key] = main_story

    # ─────────────────────────────────────────────────────────────────────────
    # 创建新游戏
    # ─────────────────────────────────────────────────────────────────────────

    def new_game(self, story_id: str) -> dict:
        """
        创建新游戏，返回初始 GameState

        流程：
            1. 加载故事包（如果尚未加载或故事 ID 不同）
            2. 读取 meta.json 中的初始数值配置
            3. 生成第一章地图（随机分配卡片）
            4. 返回完整初始状态

        参数：
            story_id: 故事目录名

        返回：
            初始 GameState 字典
        """
        # 如果故事包尚未加载，或加载的是不同的故事，重新加载
        if self.story is None or self.story["meta"].get("id") != story_id:
            self.load_story(story_id)

        # 获取初始数值配置（来自 meta.json）
        initial_stats = copy.deepcopy(self.story["meta"].get("initial_stats", {"hp": 100}))

        # 加载第0章（chapters_list 的第一个）
        first_chapter_id = self.story["chapters_list"][0]
        first_chapter = self.story["chapters"][first_chapter_id]

        # 为第一章随机生成地图卡片分配
        map_cards = self.generate_map_cards(first_chapter)

        # 构建初始 GameState
        initial_state = {
            "story_id":        story_id,
            "chapter_idx":     0,                    # 当前章节索引
            "position":        [1, 1],               # 从左上角 (1,1) 出发
            "in_card":         None,                 # 当前所在卡片 ID（None 表示在导航阶段）
            "card_round":      0,                    # 当前卡片已进行的轮数
            "card_history":    [],                   # 当前卡片的对话历史
            "stats":           initial_stats,        # 玩家数值（HP、金币等）
            "map_cards":       map_cards,            # 地图卡片分配 {"行,列": card_id}
            "visited":         [[1, 1]],             # 已访问格子列表
            "main_story_done": [],                   # 已完成的主线索引列表
        }

        return initial_state

    # ─────────────────────────────────────────────────────────────────────────
    # 地图生成
    # ─────────────────────────────────────────────────────────────────────────

    def generate_map_cards(self, chapter: dict) -> dict:
        """
        为章节地图随机分配卡片

        规则：
            - 从 chapter["card_pool"] 指定的卡片类型中随机抽取卡片
            - 起始格 (1,1) 固定分配 "start_card"（一个空的起始标记）
            - 其他每个格子随机分配一张卡片

        卡片池说明：
            chapter["card_pool"] = ["monsters", "npcs", "treasures"]
            引擎从 cards_pool 中筛选对应类型的卡片，随机分配

        参数：
            chapter: 章节配置字典

        返回：
            {"行,列": "card_id"} 格式的地图卡片分配
        """
        map_size = chapter["map_size"]
        rows = map_size["rows"]
        cols = map_size["cols"]

        # 根据 card_pool 配置，收集可用卡片 ID 列表（排除主线类型）
        pool_types = set(chapter.get("card_pool", ["monsters", "npcs", "treasures"]))

        # 将 card_pool 类型名映射到卡片类型字段（文件名 → type 字段）
        type_name_map = {
            "monsters":  "monster",
            "npcs":      "npc",
            "treasures": "treasure",
        }

        # 收集可用卡片
        available_cards = []
        for pool_name in pool_types:
            card_type = type_name_map.get(pool_name, pool_name)
            for card_id, card in self.cards_pool.items():
                if card.get("type") == card_type:
                    available_cards.append(card_id)

        # 如果没有可用卡片，做防御处理
        if not available_cards:
            available_cards = ["unknown_card"]

        map_cards = {}

        for row in range(1, rows + 1):
            for col in range(1, cols + 1):
                pos_key = f"{row},{col}"

                if row == 1 and col == 1:
                    # 起始格固定标记
                    map_cards[pos_key] = "start_card"
                else:
                    # 随机分配一张卡片（允许重复）
                    map_cards[pos_key] = random.choice(available_cards)

        return map_cards

    # ─────────────────────────────────────────────────────────────────────────
    # 导航上下文
    # ─────────────────────────────────────────────────────────────────────────

    def get_nav_context(self, state: dict) -> dict:
        """
        获取当前位置的导航上下文

        在 navigator.get_nav_context 的基础上，补充各方向卡片的 title 和 type
        （navigator 模块只计算坐标和 card_id，title/type 从 cards_pool 获取）

        参数：
            state: 当前 GameState 字典

        返回：
            NavContext 字典，含当前坐标、可选方向列表（含卡片标题和类型）、是否在边界
        """
        chapter = self.get_current_chapter(state)
        map_size = chapter["map_size"]
        map_cards = state["map_cards"]

        # 调用 navigator 模块计算基础导航信息
        nav_ctx = _get_nav_context(state, map_cards, map_size)

        # 补充每个方向的 card_title 和 card_type
        for option in nav_ctx["options"]:
            card_id = option["card_id"]

            if card_id == "start_card":
                # 起始格（通常不会向起始格移动，但做防御处理）
                option["card_title"] = "出发点"
                option["card_type"] = "start"
            elif card_id and card_id in self.cards_pool:
                card = self.cards_pool[card_id]
                option["card_title"] = card.get("title", "未知")
                option["card_type"] = card.get("type", "unknown")
            else:
                option["card_title"] = "神秘区域"
                option["card_type"] = "unknown"

        return nav_ctx

    # ─────────────────────────────────────────────────────────────────────────
    # 玩家移动
    # ─────────────────────────────────────────────────────────────────────────

    def move_player(self, state: dict, direction: str) -> dict:
        """
        移动玩家到指定方向，返回移动结果

        流程：
            1. 根据 direction 计算新坐标
            2. 检查是否触发主线（新坐标在最后一行或最后一列）
            3. 触发主线 → 加载主线卡片，设置 in_card 为主线卡片 ID
            4. 普通格子 → 从 map_cards 获取卡片，设置 in_card，记录已访问

        direction 合法值："right" / "down" / "diagonal"

        参数：
            state:     当前 GameState 字典
            direction: 移动方向

        返回 MoveResult 字典：
        {
            "new_state":              更新后的 GameState,
            "card_scene":             "进入卡片时的场景描述",
            "triggered_main_story":   是否触发主线（bool）,
            "card_id":                进入的卡片 ID
        }
        """
        new_state = copy.deepcopy(state)

        row, col = new_state["position"]

        # ── 计算新坐标 ────────────────────────────────────────────────────
        if direction == "right":
            new_row, new_col = row, col + 1
        elif direction == "down":
            new_row, new_col = row + 1, col
        elif direction == "diagonal":
            new_row, new_col = row + 1, col + 1
        else:
            raise ValueError(f"非法移动方向：{direction}，合法值为 right/down/diagonal")

        # 更新位置
        new_state["position"] = [new_row, new_col]

        # 记录访问历史（如果未曾访问）
        if [new_row, new_col] not in new_state["visited"]:
            new_state["visited"].append([new_row, new_col])

        # ── 检查是否触发主线 ──────────────────────────────────────────────
        chapter = self.get_current_chapter(new_state)
        map_size = chapter["map_size"]
        total_rows = map_size["rows"]
        total_cols = map_size["cols"]

        # 到达最后一行或最后一列，触发主线
        triggered_main_story = (new_row >= total_rows or new_col >= total_cols)

        if triggered_main_story:
            # 加载本章主线卡片
            main_story_id = chapter.get("main_story_id")
            main_story_card = self.story["main_stories"].get(main_story_id)

            if main_story_card is None:
                raise ValueError(f"找不到主线配置：{main_story_id}")

            card_id = main_story_id
            card_scene = main_story_card.get("scene_description", "主线剧情开始了。")

        else:
            # 普通格子：从地图分配中获取卡片
            pos_key = f"{new_row},{new_col}"
            card_id = new_state["map_cards"].get(pos_key)

            if card_id and card_id in self.cards_pool:
                card = self.cards_pool[card_id]
                card_scene = card.get("scene_description", "你来到了这里。")
            else:
                card_id = None
                card_scene = "你来到了一片空旷的区域。"

        # ── 设置当前卡片状态 ──────────────────────────────────────────────
        new_state["in_card"] = card_id
        new_state["card_round"] = 0
        new_state["card_history"] = []

        return {
            "new_state":            new_state,
            "card_scene":           card_scene,
            "triggered_main_story": triggered_main_story,
            "card_id":              card_id,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 章节推进
    # ─────────────────────────────────────────────────────────────────────────

    def advance_chapter(self, state: dict) -> dict:
        """
        主线完成后推进到下一章

        流程：
            1. chapter_idx + 1
            2. 检查是否有下一章
            3. 没有下一章 → 游戏通关（返回 game_cleared 状态）
            4. 有下一章 → 生成新章节地图，重置位置为 (1,1)

        参数：
            state: 当前 GameState 字典

        返回：
            更新后的 GameState 字典（含 game_cleared 字段，True 表示通关）
        """
        new_state = copy.deepcopy(state)

        current_idx = new_state["chapter_idx"]

        # 记录当前章节主线已完成
        if current_idx not in new_state["main_story_done"]:
            new_state["main_story_done"].append(current_idx)

        next_idx = current_idx + 1
        chapters_list = self.story["chapters_list"]

        if next_idx >= len(chapters_list):
            # 没有下一章了，游戏通关
            new_state["game_cleared"] = True
            return new_state

        # 推进到下一章
        new_state["chapter_idx"] = next_idx

        # 获取下一章配置并生成新地图
        next_chapter_id = chapters_list[next_idx]
        next_chapter = self.story["chapters"][next_chapter_id]
        new_map_cards = self.generate_map_cards(next_chapter)

        # 重置地图和位置
        new_state["map_cards"] = new_map_cards
        new_state["position"] = [1, 1]
        new_state["visited"] = [[1, 1]]

        # 清空卡片状态（进入导航阶段）
        new_state["in_card"] = None
        new_state["card_round"] = 0
        new_state["card_history"] = []

        new_state["game_cleared"] = False

        return new_state

    # ─────────────────────────────────────────────────────────────────────────
    # 卡片输入处理（对外接口，转发给 card_runner）
    # ─────────────────────────────────────────────────────────────────────────

    def process_card_input(self, state: dict, player_input: str, ai_response: dict) -> dict:
        """
        处理玩家在卡片内的输入，返回本轮结果

        这是对 card_runner.process_card_turn 的封装，自动从 in_card 获取当前卡片配置

        参数：
            state:        当前 GameState
            player_input: 玩家本轮输入文字
            ai_response:  AI 模块返回的字典 {"npc_response": str, "judge": str, "judge_reason": str}

        返回 CardResult：
            {
                "new_state":   更新后的 GameState,
                "card_done":   是否结束卡片,
                "outcome":     "win" / "lose" / "continue",
                "effects_log": ["gold +3"],
                "game_over":   HP <= 0 时为 True
            }
        """
        card_id = state.get("in_card")

        if card_id is None:
            raise ValueError("当前玩家不在任何卡片中，无法处理卡片输入")

        card = load_card(card_id, self.cards_pool)

        if card is None:
            raise ValueError(f"找不到卡片配置：{card_id}")

        return process_card_turn(state, card, player_input, ai_response)

    # ─────────────────────────────────────────────────────────────────────────
    # 效果应用（对外接口，转发给 stats）
    # ─────────────────────────────────────────────────────────────────────────

    def apply_effects(self, state: dict, effects: list) -> dict:
        """
        执行 effects 列表，更新 stats，检查 HP 是否归零

        这是对 stats.apply_effects 的封装，操作整个 GameState 而非单独的 stats 字典

        参数：
            state:   当前 GameState
            effects: 效果列表

        返回：
            更新后的 GameState（stats 已更新）
        """
        new_state = copy.deepcopy(state)
        new_state["stats"] = apply_effects(new_state["stats"], effects)
        return new_state

    # ─────────────────────────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────────────────────────

    def get_current_chapter(self, state: dict) -> dict:
        """
        获取当前章节配置

        参数：
            state: 当前 GameState

        返回：
            当前章节的配置字典
        """
        chapter_idx = state["chapter_idx"]
        chapter_id = self.story["chapters_list"][chapter_idx]
        return self.story["chapters"][chapter_id]

    def get_current_card(self, state: dict) -> dict | None:
        """
        获取当前所在卡片的配置

        如果玩家不在任何卡片中（导航阶段），返回 None

        参数：
            state: 当前 GameState

        返回：
            卡片配置字典，或 None
        """
        card_id = state.get("in_card")

        if card_id is None:
            return None

        return self.cards_pool.get(card_id, None)
