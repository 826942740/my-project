"""
session.py — SaveSystem 类

职责：
  - 对外暴露存档系统的所有业务接口
  - 封装 models.py 的底层数据库操作
  - 管理 token 生成、短码生成与唯一性保障

调用方（FastAPI 路由）只需要导入并实例化 SaveSystem，无需直接接触数据库。
"""

import uuid
import random
import string
import json
import sqlite3
from typing import Optional, Tuple
from . import models


class SaveSystem:
    """存档系统：管理玩家会话和游戏进度持久化"""

    def __init__(self):
        # 实例化时确保数据库和表结构已就绪
        models.init_db()

    def create_session(self, story_id: str, initial_state: dict) -> Tuple[str, str]:
        """
        创建新会话。

        同时生成 token 和 short_code，两者一起写入数据库。
        这样玩家拿到 token 的同时也能立刻获取短码，无需第二次调用。

        返回：(token, short_code)
          - token：UUID4 格式字符串（如 "550e8400-e29b-41d4-a716-446655440000"）
          - short_code：6 位大写字母+数字（如 "A3X7KM"）
        """
        # 生成唯一 token（UUID4，几乎不可能碰撞）
        token = str(uuid.uuid4())

        # 先插入记录（short_code 此时为 NULL）
        models.insert_session(token, story_id, initial_state)

        # 生成唯一短码并写入
        short_code = self._generate_and_save_short_code(token)

        return token, short_code

    def load_game(self, token: str) -> Optional[dict]:
        """
        读取存档，返回 GameState 字典。
        token 不存在时返回 None。
        GameState 原样从 JSON 反序列化，不做任何字段处理。
        """
        row = models.get_session(token)
        if row is None:
            return None

        # game_state 字段是 JSON 字符串，反序列化为字典
        return json.loads(row["game_state"])

    def save_game(self, token: str, state: dict) -> None:
        """
        保存/更新存档。
        每次玩家行动（移动、卡片对话）完成后调用。
        会同时更新数据库里的 updated_at 时间戳。
        """
        models.update_game_state(token, state)

    def session_exists(self, token: str) -> bool:
        """
        检查 token 是否存在于数据库中。
        用于验证前端传来的 token 是否有效。
        """
        return models.get_session(token) is not None

    def get_token_by_code(self, short_code: str) -> Optional[str]:
        """
        通过 6 位短码查找对应的 token。
        用于换设备恢复游戏（玩家在新设备输入短码）。
        短码不存在时返回 None。
        """
        row = models.get_session_by_code(short_code)
        if row is None:
            return None
        return row["token"]

    def get_short_code(self, token: str) -> Optional[str]:
        """
        获取 token 对应的短码。
        采用懒加载策略：
          - 如果数据库中已有短码，直接返回
          - 如果还没有短码，现在生成并存入数据库
        token 不存在时返回 None。
        """
        row = models.get_session(token)
        if row is None:
            return None

        # 已有短码直接返回
        if row["short_code"]:
            return row["short_code"]

        # 懒加载：现在生成短码
        return self._generate_and_save_short_code(token)

    def _generate_and_save_short_code(self, token: str) -> str:
        """
        生成唯一短码并保存到数据库。
        如果生成的短码已被其他会话占用，则循环重试，直到找到不冲突的短码。
        （短码空间为 36^6 ≈ 2.1 亿，实际玩家量远低于此，碰撞极罕见）
        """
        while True:
            short_code = self._generate_short_code()
            try:
                models.set_short_code(token, short_code)
                return short_code
            except sqlite3.IntegrityError:
                # UNIQUE 约束冲突，短码已被占用，重新生成
                continue

    def _generate_short_code(self) -> str:
        """
        生成一个随机 6 位短码。
        字符集：大写字母 A-Z + 数字 0-9，共 36 种字符。
        示例："A3X7KM"、"Z9B2QW"
        """
        # 使用大写字母 + 数字，避免 0/O、1/I 视觉混淆问题可在此过滤
        chars = string.ascii_uppercase + string.digits
        return "".join(random.choices(chars, k=6))
