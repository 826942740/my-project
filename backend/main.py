"""
main.py — FastAPI 后端主入口

负责：
  - 定义所有 HTTP API 路由
  - 协调游戏引擎、AI 模块、存档系统三者的调用顺序
  - 处理请求/响应的格式转换和错误处理

数据流：
  玩家输入 → FastAPI 路由 → 存档系统读取状态
    → 游戏引擎处理逻辑 → AI 模块生成文字 → 存档系统保存状态
    → 返回 JSON 给前端
"""

import sys
import json
import random
import logging
from pathlib import Path

# ── 将项目根目录加入 Python 路径 ──
# 这一步必须在其他模块导入之前执行
# 类比：告诉 Python "去这个文件夹里找模块"
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 导入配置（会自动初始化数据库路径）──
import backend.config  # noqa: F401  导入即执行路径配置

# ── 导入 FastAPI 相关 ──
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import copy

# 前端目录路径
FRONTEND_DIR = Path(__file__).parent.parent / "module-1-frontend"

# ── 导入各模块（目录名中的 - 必须写成 _）──
from module_2_ai.client import AIClient
from module_2_ai.prompts import build_nav_prompt, build_card_prompt, build_direction_parse_prompt, build_card_entry_prompt, build_daily_life_prompt
from module_3_game_rules.engine import GameEngine
from module_3_game_rules.card_runner import process_card_turn, load_card
from module_3_game_rules.navigator import parse_direction
from module_4_save_system.session import SaveSystem

# ── 配置日志 ──
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
# httpx 的 DEBUG 日志太多（每次请求都打印 header），单独设为 INFO
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# FastAPI 应用初始化
# ──────────────────────────────────────────────

app = FastAPI(
    title="Fangame API",
    description="AI 驱动的文字冒险游戏后端 API",
    version="1.0.0",
)

# 允许前端跨域访问（开发阶段允许所有来源，生产环境需限制）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局单例（应用启动时创建一次，所有请求共用）──
# 类比：开店前准备好"引擎"、"AI助手"、"存档柜"，顾客来了直接用
engine = GameEngine()
save_system = SaveSystem()
ai_client = AIClient()

logger.info("Fangame 后端服务初始化完成")

# ── 挂载前端静态文件（css、js 等）──
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# ── 根路由：返回前端首页 ──
@app.get("/")
async def serve_index():
    """访问根路径时返回前端 index.html"""
    return FileResponse(FRONTEND_DIR / "index.html")


# ──────────────────────────────────────────────
# 请求/响应数据模型（Pydantic 自动验证格式）
# ──────────────────────────────────────────────

class NewGameRequest(BaseModel):
    """创建新游戏的请求体"""
    story_id: str = "dark_forest"  # 故事包 ID，默认黑暗森林


class NavigateRequest(BaseModel):
    """导航移动的请求体"""
    session_token: str                       # 玩家会话令牌
    player_input: str                        # 玩家的自然语言输入（如"我往右走"）
    hint_direction: Optional[str] = None     # 按钮点击时直接传入方向，跳过 AI 解析
    nav_option_hints: Optional[list] = None  # 旁白选项文字[{direction,text}]，辅助语义匹配


class CardActionRequest(BaseModel):
    """卡片内对话的请求体"""
    session_token: str           # 玩家会话令牌
    player_input: str            # 玩家的对话输入


class DailyLifeRequest(BaseModel):
    """日常生活阶段的请求体"""
    session_token: str           # 玩家会话令牌
    player_input: str            # 玩家的选择或自由输入


class ResumeRequest(BaseModel):
    """通过短码恢复存档的请求体"""
    code: str                    # 6 位存档短码（如 "A3X7KM"）


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def get_meta(story_id: str) -> dict:
    """
    获取故事包的 meta 配置。
    meta 包含 AI 提示词模板、导航提示映射等信息。
    """
    if engine.story is None:
        raise ValueError(f"故事包尚未加载：{story_id}")
    return engine.story["meta"]


def generate_nav_narrative(state: dict) -> str:
    """
    生成导航旁白文字（调用 AI）。
    失败时直接抛出异常，由上层路由处理。
    """
    nav_ctx = engine.get_nav_context(state)
    chapter = engine.get_current_chapter(state)

    messages = build_nav_prompt(
        meta=get_meta(state["story_id"]),
        chapter_name=chapter.get("name", "未知章节"),
        stats=state["stats"],
        directions=nav_ctx["options"],
        last_card_context=state.get("last_card_context"),
        last_daily_life_context=state.get("last_daily_life_context"),
    )
    return ai_client.call(messages)


# ──────────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────────

@app.post("/api/session/new")
async def new_session(req: NewGameRequest):
    """
    创建新游戏会话。

    流程：
      1. 加载故事包（如果尚未加载）
      2. 引擎生成初始游戏状态
      3. 存档系统创建新会话，返回 token 和短码
      4. AI 生成初始导航旁白
      5. 返回完整初始信息给前端

    前端收到 token 后存入 localStorage，后续每次请求都带上。
    """
    story_id = req.story_id
    logger.info(f"创建新游戏，故事ID：{story_id}")

    # 加载故事包（如果尚未加载或故事不同）
    try:
        if engine.story is None or engine.story["meta"].get("id") != story_id:
            engine.load_story(story_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"故事包不存在：{story_id}")

    # 引擎生成初始状态
    initial_state = engine.new_game(story_id)

    # 存档系统创建会话
    token, short_code = save_system.create_session(story_id, initial_state)
    logger.info(f"新会话已创建：token={token[:8]}...，short_code={short_code}")

    # 获取开场剧情文本和卡片信息（故事包可选配置）
    prologue = engine.story.get("prologue", "")
    prologue_card_id = initial_state.get("in_card")
    prologue_card_info = {}
    if prologue_card_id:
        card = engine.cards_pool.get(prologue_card_id)
        if card:
            prologue_card_info = {
                "title": card.get("title", ""),
                "initial_actions": card.get("initial_actions", []),
            }

    return {
        "session_token": token,
        "short_code": short_code,
        "story_id": story_id,
        "state": initial_state,
        "prologue": prologue,
        "prologue_card": prologue_card_info,
    }


@app.get("/api/state")
async def get_state(token: str = Query(..., description="会话令牌")):
    """
    获取当前游戏完整状态。

    前端可以用这个接口刷新页面后恢复显示。
    如果当前在导航阶段（in_card 为 None），同时返回导航旁白。
    """
    # 验证 token 是否存在
    state = save_system.load_game(token)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在，请开始新游戏")

    return {
        "valid": True,
        "state": state,
    }


@app.post("/api/navigate")
async def navigate(req: NavigateRequest):
    """
    导航阶段：玩家选择移动方向。

    流程：
      1. 加载并验证当前状态（必须在导航阶段）
      2. 从玩家自然语言中解析方向
      3. 引擎移动玩家，进入目标格子的卡片
      4. 保存新状态
      5. 如果触发主线，返回主线场景描述
         否则生成下一位置的导航旁白

    支持自然语言输入：
      - "我往右走" → right
      - "向下方前进" → down
      - "斜向右下" → diagonal
    """
    # 加载状态
    state = save_system.load_game(req.session_token)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在，请开始新游戏")

    logger.debug(
        f"[navigate] token={req.session_token[:8]}... | "
        f"位置={state['position']} | in_card={state.get('in_card')} | "
        f"input={req.player_input!r}"
    )

    # 验证当前阶段：必须是导航阶段（in_card 为 None 且不在日常生活阶段）
    if state.get("daily_life_phase"):
        raise HTTPException(
            status_code=400,
            detail="当前在日常生活阶段，请使用 /api/daily_life 进行互动"
        )
    if state.get("in_card") is not None:
        raise HTTPException(
            status_code=400,
            detail="当前在卡片副本中，请使用 /api/card_action 进行对话"
        )

    # 确保故事包已加载
    story_id = state.get("story_id", "dark_forest")
    if engine.story is None or engine.story["meta"].get("id") != story_id:
        try:
            engine.load_story(story_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"故事包不存在：{story_id}")

    # 获取当前可选方向
    nav_ctx = engine.get_nav_context(state)
    options = nav_ctx["options"]

    # 如果前端按钮直接提供了方向，跳过文字解析（最可靠）
    valid_directions = {opt["direction"] for opt in options}
    if req.hint_direction and req.hint_direction in valid_directions:
        direction = req.hint_direction
        logger.info(f"使用前端提供的方向：{direction}")
    else:
        # 解析玩家输入中的方向意图（关键词匹配）
        direction = parse_direction(req.player_input, options)

        if direction is None:
            # 关键词匹配失败，用 AI 理解玩家意图
            logger.info(f"关键词解析方向失败，启用 AI 解析：input={req.player_input!r}")
            try:
                # 传入旁白选项文字（如有），让 AI 能语义匹配（"我想离开"→"迅速离开此地"→方向）
                parse_messages = build_direction_parse_prompt(
                    req.player_input, options,
                    nav_option_hints=req.nav_option_hints or []
                )
                ai_direction = ai_client.call(parse_messages).strip().lower()
                if ai_direction in {"right", "down", "diagonal"}:
                    direction = ai_direction
                    logger.info(f"AI 解析方向成功：{direction}")
            except Exception as e:
                logger.error(f"AI 解析方向失败：{e}")

    if direction is None:
        # AI 也无法解析，随机选第一个可用方向（游戏设计上不允许停在原地）
        if options:
            direction = random.choice(options)["direction"]
            logger.info(f"方向解析全部失败，随机选择：{direction}")
        else:
            return {
                "phase": "navigation",
                "narrative": "（此处四面封闭，无路可走。）",
                "stats": state["stats"],
            }

    # 引擎移动玩家
    move_result = engine.move_player(state, direction)
    new_state = move_result["new_state"]
    card_scene = move_result["card_scene"]
    triggered_main_story = move_result["triggered_main_story"]
    card_id = move_result["card_id"]

    # 获取卡片配置，提取标题和初始行动选项（用于前端显示进入卡片时的选项按钮）
    card_config = engine.get_current_card(new_state)
    card_title = card_config.get("title", card_id) if card_config else card_id
    initial_actions = card_config.get("initial_actions", []) if card_config else []

    # 记录玩家本次导航选择文字，供卡片入场叙事 AI 使用（衔接导航情景）
    new_state["last_nav_input"] = req.player_input

    # 保存新状态
    save_system.save_game(req.session_token, new_state)
    logger.info(
        f"玩家移动：token={req.session_token[:8]}..., "
        f"方向={direction}, 新位置={new_state['position']}, "
        f"进入卡片={card_id}, 触发主线={triggered_main_story}"
    )

    # 构建返回数据
    response = {
        "phase": "navigation",
        "moved_to": new_state["position"],
        "direction": direction,
        "triggered_main_story": triggered_main_story,
        "entered_card": {
            "card_id": card_id,
            "title": card_title,
            "scene_description": card_scene,
            "initial_actions": initial_actions,
        },
        "stats": new_state["stats"],
    }

    if triggered_main_story:
        # 主线剧情：直接返回静态场景描述（主线开场是精心撰写的固定文字）
        response["narrative"] = card_scene
    # 普通卡片：不返回静态场景，由前端调 /api/card_entry 获取 AI 生成的入场叙事

    return response


@app.post("/api/card_action")
async def card_action(req: CardActionRequest):
    """
    卡片阶段：玩家在卡片副本内对话。

    流程：
      1. 加载并验证当前状态（必须在卡片阶段）
      2. 获取当前卡片配置
      3. 构建卡片 Prompt，调用 AI（NPC 回应 + 裁判判断合并一次调用）
      4. 解析 AI 返回的 JSON
      5. 引擎处理本轮结果（更新 stats，判断卡片结束）
      6. 保存新状态
      7. 如果卡片结束，同时生成下一步导航旁白

    AI 返回格式（JSON）：
      {
        "npc_response": "NPC 的回应文字",
        "judge": "continue / win / lose",
        "judge_reason": "裁判理由（调试用）"
      }
    """
    # 加载状态
    state = save_system.load_game(req.session_token)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在，请开始新游戏")

    logger.debug(
        f"[card_action] token={req.session_token[:8]}... | "
        f"卡片={state.get('in_card')} | 轮数={state.get('card_round', 0)} | "
        f"input={req.player_input!r}"
    )

    # 验证当前阶段：必须是卡片阶段（in_card 不为 None）
    if state.get("in_card") is None:
        raise HTTPException(
            status_code=400,
            detail="当前在导航阶段，请使用 /api/navigate 选择移动方向"
        )

    # 确保故事包已加载
    story_id = state.get("story_id", "dark_forest")
    if engine.story is None or engine.story["meta"].get("id") != story_id:
        try:
            engine.load_story(story_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"故事包不存在：{story_id}")

    # 获取当前卡片配置
    card = engine.get_current_card(state)
    if card is None:
        raise HTTPException(
            status_code=500,
            detail=f"找不到卡片配置：{state.get('in_card')}"
        )

    # 构建卡片 Prompt（NPC + 裁判合并一次调用）
    messages = build_card_prompt(
        meta=get_meta(story_id),
        card=card,
        stats=state["stats"],
        dialogue_history=state.get("card_history", []),
        player_input=req.player_input,
        current_round=state.get("card_round", 0) + 1,  # 显示给 AI 的轮数从 1 开始
    )

    # 调用 AI（expect_json=True，自动重试保证格式正确）
    # 外层 try 捕获 AI 完全失败的情况（重试耗尽后抛出 ValueError）
    ai_response = None
    try:
        ai_resp_str = ai_client.call(messages, expect_json=True)
        try:
            ai_response = json.loads(ai_resp_str)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"AI 返回无法解析为 JSON：{e}，原始内容：{ai_resp_str[:200]}")
    except Exception as e:
        logger.error(f"AI 调用彻底失败（重试耗尽）：{e}")

    # 无论哪种失败，都用降级响应兜底，避免游戏卡死
    if ai_response is None:
        ai_response = {
            "npc_response": "（AI 响应异常，请重试）",
            "judge": "continue",
            "judge_reason": "AI调用失败，降级处理",
            "options": [],
        }

    # ── 引擎处理本轮（更新对话历史、数值结算、判断卡片结束）──
    # 外层 try 捕获引擎处理中的意外异常（如 state 字段缺失导致 KeyError），
    # 避免直接返回 500，改为降级响应让游戏继续
    try:
        card_result = process_card_turn(state, card, req.player_input, ai_response)
        new_state = card_result["new_state"]
        card_done = card_result["card_done"]
        outcome = card_result["outcome"]
        effects_log = card_result["effects_log"]
        game_over = card_result["game_over"]
    except Exception as e:
        # 引擎处理失败，降级为"继续对话"，不让游戏卡死
        logger.error(f"process_card_turn 异常，降级处理：{e}", exc_info=True)
        # 保留原 state 不做修改，返回降级响应
        return {
            "phase": "card",
            "npc_response": ai_response.get("npc_response", "（系统异常，请重试）"),
            "judge": "continue",
            "card_done": False,
            "effects_log": [],
            "stats": state["stats"],
            "game_over": False,
            "options": ai_response.get("options", []),
        }

    # 如果主线胜利且游戏未结束，推进到下一章节
    # 必须同时满足：卡片结束 + 胜利（outcome=win） + 未死亡 + 是主线卡片
    # 修复 Bug：之前缺少 outcome == "win" 检查，导致主线失败时也触发章节推进，
    #          advance_chapter 会重置 position=[1,1] 和 visited，引发位置重置 bug
    if card_done and outcome == "win" and not game_over and card.get("type") == "main_story":
        try:
            new_state = engine.advance_chapter(new_state)
            logger.info(f"主线完成，章节推进至：{new_state.get('chapter_idx')}")
        except Exception as e:
            # 章节推进失败，记录日志但不中断（卡片已结算成功）
            logger.error(f"advance_chapter 异常：{e}", exc_info=True)

    # ── 事件卡结束后启动日常生活阶段 ─────────────────────────────────────
    # monster/npc/treasure 结束后 → 进入日常阶段（AI 生成叙事，玩家互动式探索）
    daily_narrative = None
    daily_options = None
    if card_done and not game_over and not new_state.get("game_cleared"):
        card_type = card.get("type", "")

        if card_type in ("monster", "npc", "treasure", "prologue"):
            # 启动日常生活阶段（清除上一轮残留的日常上下文）
            new_state.pop("last_daily_life_context", None)
            dl_config = new_state.get("daily_life_config", {})
            total_rounds = random.randint(
                dl_config.get("min_rounds", 3),
                dl_config.get("max_rounds", 5),
            )
            new_state["daily_life_phase"] = True
            new_state["daily_life_round"] = 0
            new_state["daily_life_total"] = total_rounds
            new_state["daily_life_history"] = []

            # 生成第一轮日常叙事（结合刚结束的事件上下文）
            try:
                daily_prompt_text = engine.get_daily_life_prompt(new_state)
                dl_messages = build_daily_life_prompt(
                    meta=get_meta(story_id),
                    chapter_daily_prompt=daily_prompt_text,
                    stats=new_state["stats"],
                    last_card_context=new_state.get("last_card_context"),
                    daily_history=[],
                    player_input=None,  # 第一轮无玩家输入
                    current_round=1,
                    total_rounds=total_rounds,
                )
                dl_resp_str = ai_client.call(dl_messages, expect_json=True)
                dl_resp = json.loads(dl_resp_str)
                daily_narrative = dl_resp.get("narrative", "")
                daily_options = dl_resp.get("options", [])

                # 记录第一轮到日常对话历史
                new_state["daily_life_round"] = 1
                new_state["daily_life_history"].append({
                    "role": "narrator",
                    "content": daily_narrative,
                })
            except Exception as e:
                logger.error(f"日常叙事生成失败：{e}", exc_info=True)
                # 生成失败则跳过日常阶段，直接回导航
                new_state["daily_life_phase"] = False

    # 保存新状态
    save_system.save_game(req.session_token, new_state)
    logger.info(
        f"卡片对话：token={req.session_token[:8]}..., "
        f"卡片={state['in_card']}, 结果={outcome}, 卡片完成={card_done}"
    )

    # 构建返回数据
    response = {
        "phase": "card",
        "npc_response": ai_response.get("npc_response", ""),
        "judge": outcome,
        "card_done": card_done,
        "effects_log": effects_log,
        "stats": new_state["stats"],
        "game_over": game_over,
        # judge=continue 时返回 AI 给出的下一步行动选项，结束时返回空列表
        "options": ai_response.get("options", []) if not card_done else [],
    }

    # 卡片结束时，通知前端是否通关
    if card_done and not game_over:
        response["game_cleared"] = bool(new_state.get("game_cleared"))

    # 如果进入了日常生活阶段，附带第一轮叙事和选项
    if daily_narrative:
        response["daily_life"] = {
            "narrative": daily_narrative,
            "options": daily_options or [],
            "round": 1,
            "total": new_state["daily_life_total"],
        }

    return response


@app.post("/api/daily_life")
async def daily_life_action(req: DailyLifeRequest):
    """
    日常生活阶段：玩家在事件卡之间的互动式日常探索。

    流程：
      1. 验证当前处于日常阶段（daily_life_phase=True）
      2. 记录玩家输入到日常对话历史
      3. 推进轮数，调用 AI 生成下一段日常叙事 + 3 个选项
      4. 最后一轮：AI 以不安预兆收尾，日常阶段结束，回到导航

    AI 返回格式（JSON）：
      {
        "narrative": "日常叙事文字",
        "options": ["选项1", "选项2", "选项3"]   // 最后一轮为 []
      }
    """
    # 加载状态
    state = save_system.load_game(req.session_token)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在，请开始新游戏")

    # 验证当前处于日常生活阶段
    if not state.get("daily_life_phase"):
        raise HTTPException(
            status_code=400,
            detail="当前不在日常生活阶段"
        )

    # 确保故事包已加载
    story_id = state.get("story_id", "khemjira")
    if engine.story is None or engine.story["meta"].get("id") != story_id:
        try:
            engine.load_story(story_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"故事包不存在：{story_id}")

    # 推进轮数
    current_round = state.get("daily_life_round", 0) + 1
    total_rounds = state.get("daily_life_total", 3)

    logger.debug(
        f"[daily_life] token={req.session_token[:8]}... | "
        f"轮数={current_round}/{total_rounds} | input={req.player_input!r}"
    )

    # ── 用户回应最后一轮日常：不再生成新叙事，直接结束 ──
    # 最后一轮 AI 已经生成了叙事 + 选项，用户选了之后 current_round > total_rounds
    if current_round > total_rounds:
        # 从对话历史中取最后一条叙事作为上下文
        daily_history = state.get("daily_life_history", [])
        last_narrative = ""
        for entry in reversed(daily_history):
            if entry.get("role") == "narrator":
                last_narrative = entry.get("content", "")
                break

        # 保存日常结尾上下文，供导航 prompt 衔接
        state["last_daily_life_context"] = {
            "last_narrative": last_narrative,
            "last_player_input": req.player_input,
        }
        # 清理日常状态，回到导航
        state["daily_life_phase"] = False
        state["daily_life_round"] = 0
        state["daily_life_total"] = 0
        state["daily_life_history"] = []

        save_system.save_game(req.session_token, state)
        logger.info(
            f"日常生活结束：token={req.session_token[:8]}..., "
            f"最后输入={req.player_input!r}"
        )

        return {
            "phase": "daily_life",
            "narrative": "",
            "options": [],
            "round": current_round,
            "total": total_rounds,
            "done": True,
            "stats": state["stats"],
        }

    # ── 正常轮次：调用 AI 生成下一段叙事 ──
    daily_history = state.get("daily_life_history", [])

    # 构建日常叙事 Prompt
    # player_input 单独传入，让 prompt 在上下文中强调玩家行动
    # history 只包含之前轮次的完整记录，避免重复
    daily_prompt_text = engine.get_daily_life_prompt(state)
    dl_messages = build_daily_life_prompt(
        meta=get_meta(story_id),
        chapter_daily_prompt=daily_prompt_text,
        stats=state["stats"],
        last_card_context=state.get("last_card_context"),
        daily_history=daily_history,
        player_input=req.player_input,
        current_round=current_round,
        total_rounds=total_rounds,
    )

    # 调用 AI
    try:
        dl_resp_str = ai_client.call(dl_messages, expect_json=True)
        dl_resp = json.loads(dl_resp_str)
        narrative = dl_resp.get("narrative", "")
        options = dl_resp.get("options", [])
    except Exception as e:
        logger.error(f"日常叙事 AI 调用失败：{e}", exc_info=True)
        narrative = "（日常叙事生成失败，跳过本段日常。）"
        options = []

    # 记录玩家输入 + AI 叙事到对话历史
    daily_history.append({
        "role": "player",
        "content": req.player_input,
    })
    daily_history.append({
        "role": "narrator",
        "content": narrative,
    })

    # 更新状态
    state["daily_life_round"] = current_round
    state["daily_life_history"] = daily_history

    # 仅在 AI 返回空选项时提前结束（异常情况兜底）
    is_done = not options
    if is_done:
        state["last_daily_life_context"] = {
            "last_narrative": narrative,
            "last_player_input": req.player_input,
        }
        state["daily_life_phase"] = False
        state["daily_life_round"] = 0
        state["daily_life_total"] = 0
        state["daily_life_history"] = []

    # 保存状态
    save_system.save_game(req.session_token, state)
    logger.info(
        f"日常生活：token={req.session_token[:8]}..., "
        f"轮数={current_round}/{total_rounds}, 完成={is_done}"
    )

    return {
        "phase": "daily_life",
        "narrative": narrative,
        "options": options,
        "round": current_round,
        "total": total_rounds,
        "done": is_done,
        "stats": state["stats"],
    }


@app.get("/api/session/code")
async def get_session_code(token: str = Query(..., description="会话令牌")):
    """
    获取当前会话的存档短码（用于换设备继续游戏）。

    短码是 6 位大写字母+数字（如 "A3X7KM"）。
    玩家可以在新设备上通过短码恢复游戏。
    """
    if not save_system.session_exists(token):
        raise HTTPException(status_code=404, detail="会话不存在")

    short_code = save_system.get_short_code(token)
    if short_code is None:
        raise HTTPException(status_code=500, detail="获取短码失败")

    return {"short_code": short_code}


@app.post("/api/session/resume")
async def resume_session(req: ResumeRequest):
    """
    通过短码恢复游戏（换设备时使用）。

    玩家在新设备输入 6 位短码：
      → 服务器查询对应 token
      → 返回 token 和当前存档状态
      → 前端将 token 存入 localStorage

    恢复成功后，前端可直接继续上次的游戏进度。
    """
    code = req.code.upper().strip()  # 统一转大写，兼容大小写输入

    # 通过短码查找 token
    token = save_system.get_token_by_code(code)
    if token is None:
        raise HTTPException(status_code=404, detail=f"存档码不存在：{code}，请检查输入是否正确")

    # 加载存档状态
    state = save_system.load_game(token)
    if state is None:
        raise HTTPException(status_code=500, detail="存档数据损坏，无法恢复")

    logger.info(f"通过短码恢复游戏：code={code}, token={token[:8]}...")

    # 导航旁白由前端单独调用 /api/nav 异步获取，不在此处生成
    return {
        "session_token": token,
        "state": state,
    }


# ──────────────────────────────────────────────
# 健康检查接口
# ──────────────────────────────────────────────

@app.get("/api/nav")
async def get_nav_narrative(token: str = Query(..., description="会话令牌")):
    """
    单独获取当前位置的导航旁白（AI 生成，耗时较长）。
    与 /api/state 分离，让界面能先显示再异步加载旁白。
    """
    state = save_system.load_game(token)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    if state.get("in_card") is not None:
        raise HTTPException(status_code=400, detail="当前在卡片阶段，无需导航旁白")

    story_id = state.get("story_id", "dark_forest")
    if engine.story is None or engine.story["meta"].get("id") != story_id:
        engine.load_story(story_id)

    nav_ctx = engine.get_nav_context(state)
    narrative = generate_nav_narrative(state)
    # 同时返回方向列表，前端按钮可直接绑定方向，无需再做文字解析
    return {"narrative": narrative, "directions": nav_ctx["options"]}


@app.get("/api/card_entry")
async def get_card_entry_narrative(token: str = Query(..., description="会话令牌")):
    """
    获取卡片入场叙事（AI 动态生成）。

    玩家进入卡片后由前端异步调用，与 navigate 响应分离，不阻塞移动操作。
    AI 根据玩家的导航行动和卡片遭遇内容，生成自然衔接的入场描述，
    避免静态 scene_description 与导航旁白设定冲突。
    """
    state = save_system.load_game(token)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    if state.get("in_card") is None:
        raise HTTPException(status_code=400, detail="当前不在卡片中，无需入场叙事")

    story_id = state.get("story_id", "khemjira")
    if engine.story is None or engine.story["meta"].get("id") != story_id:
        engine.load_story(story_id)

    card = engine.get_current_card(state)
    if card is None:
        raise HTTPException(status_code=500, detail=f"找不到卡片配置：{state.get('in_card')}")

    # 读取玩家上次的导航选择文字（由 navigate 存入 state）
    player_choice = state.get("last_nav_input", "")

    # 读取上一张卡片的上下文（由 card_runner 在卡片结束时写入 state）
    # 用于让入场叙事 AI 了解前一段遭遇，保证故事逻辑连贯
    last_card_context = state.get("last_card_context")

    messages = build_card_entry_prompt(
        meta=get_meta(story_id),
        card=card,
        stats=state["stats"],
        player_choice_text=player_choice,
        last_card_context=last_card_context,
    )
    narrative = ai_client.call(messages)
    logger.info(f"卡片入场叙事生成：token={token[:8]}..., 卡片={state['in_card']}")
    return {"narrative": narrative}


@app.get("/api/health")
async def health_check():
    """健康检查，用于确认服务是否正常运行"""
    return {
        "status": "ok",
        "service": "Fangame API",
        "engine_loaded": engine.story is not None,
        "story_id": engine.story["meta"].get("id") if engine.story else None,
    }
