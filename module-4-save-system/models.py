"""
models.py — 数据库连接和底层表操作

职责：
  - 管理 SQLite 连接
  - 执行建表 SQL
  - 提供对 sessions 表的增删改查函数

所有函数都是无状态的，使用完立即关闭连接。
上层业务逻辑在 session.py 的 SaveSystem 类中实现。
"""

import sqlite3
import json
from pathlib import Path
from typing import Optional

# 数据库文件路径（可被外部配置覆盖）
# 默认放在项目根目录的 saves/ 目录下
DB_PATH = Path(__file__).parent.parent / "saves" / "game.db"


def get_connection() -> sqlite3.Connection:
    """
    获取数据库连接。
    如果 saves/ 目录不存在会自动创建（避免手动建目录的麻烦）。
    返回的连接使用 Row 工厂，查询结果可以用列名访问。
    """
    # 确保 saves 目录存在，不存在则创建
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    # 让查询结果支持字典风格访问，如 row["token"]
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    初始化数据库：读取 schema.sql 并执行建表语句。
    使用 IF NOT EXISTS，重复调用是安全的（不会清空数据）。
    """
    # 找到与本文件同目录的 schema.sql
    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with get_connection() as conn:
        conn.executescript(schema_sql)


def insert_session(token: str, story_id: str, game_state: dict) -> None:
    """
    插入一条新会话记录。
    game_state 字典会被序列化为 JSON 字符串存入数据库。
    """
    game_state_json = json.dumps(game_state, ensure_ascii=False)

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, story_id, game_state) VALUES (?, ?, ?)",
            (token, story_id, game_state_json),
        )


def update_game_state(token: str, game_state: dict) -> None:
    """
    更新指定 token 的存档内容，同时刷新 updated_at 为当前时间。
    每次玩家行动后调用此函数自动保存进度。
    """
    game_state_json = json.dumps(game_state, ensure_ascii=False)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE sessions
               SET game_state = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE token = ?
            """,
            (game_state_json, token),
        )


def get_session(token: str) -> Optional[dict]:
    """
    通过 token 查询会话，返回完整行数据（字典格式）。
    token 不存在时返回 None。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

    if row is None:
        return None

    # 将 sqlite3.Row 转为普通字典，方便上层使用
    return dict(row)


def get_session_by_code(short_code: str) -> Optional[dict]:
    """
    通过 6 位短码查询会话，返回完整行数据（字典格式）。
    短码不存在时返回 None。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE short_code = ?",
            (short_code,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def set_short_code(token: str, short_code: str) -> None:
    """
    为指定 token 的会话设置短码。
    短码在数据库中有 UNIQUE 约束，如果冲突会抛出 sqlite3.IntegrityError。
    上层 SaveSystem._generate_short_code 负责重试。
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET short_code = ? WHERE token = ?",
            (short_code, token),
        )
