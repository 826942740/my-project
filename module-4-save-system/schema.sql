-- 存档系统数据库建表脚本
-- 所有玩家存档都存在这一张表里，结构极简

-- 会话表：每个玩家一条记录
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT     PRIMARY KEY,           -- 玩家身份标识，UUID4 格式，由后端生成
    story_id    TEXT     NOT NULL,              -- 当前游玩的故事包 ID（如 "dark_forest"）
    game_state  TEXT     NOT NULL,              -- JSON 格式的完整 GameState，原样存储
    short_code  TEXT     UNIQUE,                -- 6位换设备用的短码（懒加载，用时才生成）
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 会话创建时间
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP   -- 最后存档时间（每次 save_game 更新）
);

-- 索引：加速通过短码查询 token 的操作
CREATE INDEX IF NOT EXISTS idx_sessions_short_code ON sessions(short_code);
