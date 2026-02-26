"""
client.py — OpenAI 兼容 API 客户端

负责与 AI 大模型通信，支持任意 OpenAI 格式 endpoint（DeepSeek / Claude / GPT / 本地模型）。
所有配置通过环境变量读取，不写入代码。

错误处理策略：
  - 网络超时：重试 1 次，再失败返回降级文本
  - JSON 解析失败：重试 1 次并附加 JSON 强调指令，再失败返回降级文本
  - Rate limit：等待 3 秒后重试 1 次
  - 其他错误：记录日志，返回降级文本，不中断游戏
"""

import os
import time
import json
import logging
from openai import OpenAI, APITimeoutError, RateLimitError, APIError

# 配置日志，方便排查问题
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 降级文本常量（AI 完全失败时的兜底，保证游戏不中断）
# ──────────────────────────────────────────────

# 导航旁白降级文本
FALLBACK_NARRATIVE = "（叙事加载失败，请重试）"

# 卡片 NPC + 裁判降级文本（合法 JSON，默认 continue 避免游戏卡死）
FALLBACK_CARD_RESPONSE = '{"npc_response": "...", "judge": "continue", "judge_reason": "AI调用失败"}'


class AIClient:
    """
    OpenAI 兼容 API 客户端，支持任意 endpoint。

    使用方式：
        client = AIClient()
        result = client.call(messages, expect_json=False)

    环境变量说明：
        AI_API_BASE_URL     — API 地址，例如 https://api.deepseek.com/v1
        AI_API_KEY          — API 密钥
        AI_MODEL            — 模型名称，例如 deepseek-chat
        AI_MAX_TOKENS       — 最大生成 token 数（默认 500）
        AI_TEMPERATURE      — 生成温度，越高越随机（默认 0.8）
        AI_TIMEOUT_SECONDS  — 请求超时秒数（默认 30）
    """

    def __init__(self):
        # ── 从环境变量读取所有配置 ──

        # API 访问地址（必须设置）
        base_url = os.environ.get("AI_API_BASE_URL")
        if not base_url:
            logger.warning("环境变量 AI_API_BASE_URL 未设置，将使用 OpenAI 官方地址")

        # API 密钥（必须设置）
        api_key = os.environ.get("AI_API_KEY", "")
        if not api_key:
            logger.warning("环境变量 AI_API_KEY 未设置")

        # 模型名称（必须设置）
        self.model = os.environ.get("AI_MODEL", "gpt-3.5-turbo")

        # 最大生成 token 数（默认 500）
        self.max_tokens = int(os.environ.get("AI_MAX_TOKENS", "500"))

        # 生成温度：0~2，越高越有创意/随机（默认 0.8）
        self.temperature = float(os.environ.get("AI_TEMPERATURE", "0.8"))

        # 请求超时秒数（默认 30）
        self.timeout = float(os.environ.get("AI_TIMEOUT_SECONDS", "30"))

        # ── 初始化 OpenAI 客户端 ──
        # openai>=1.0.0 支持直接传入 base_url，兼容任意 OpenAI 格式 endpoint
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = OpenAI(**client_kwargs)

        logger.info(
            f"AIClient 初始化完成 | endpoint={base_url or '官方'} | model={self.model} "
            f"| max_tokens={self.max_tokens} | temperature={self.temperature}"
        )

    # ──────────────────────────────────────────────
    # 核心调用方法
    # ──────────────────────────────────────────────

    def call(self, messages: list[dict], expect_json: bool = False) -> str:
        """
        调用 AI API，返回生成的文本字符串。

        参数：
            messages    — OpenAI 格式消息列表 [{"role": "system/user/assistant", "content": "..."}]
            expect_json — True 时要求返回合法 JSON；解析失败会自动重试一次

        返回：
            AI 生成的文本（已去除首尾空白）；失败时返回降级文本

        重试策略：
            - 超时：重试 1 次
            - Rate limit：等待 3 秒重试 1 次
            - JSON 解析失败：附加 JSON 格式要求后重试 1 次
            - 其他错误：直接返回降级文本
        """
        try:
            # ── 第一次调用 ──
            response_text = self._do_call(messages)
        except APITimeoutError:
            # 超时：等一下再重试一次
            logger.warning("API 请求超时，正在重试（1/1）...")
            try:
                response_text = self._do_call(messages)
            except Exception as e:
                logger.error(f"重试后仍然超时，返回降级文本。错误：{e}")
                return FALLBACK_NARRATIVE
        except RateLimitError:
            # Rate limit：等 3 秒后重试
            logger.warning("触发 Rate limit，等待 3 秒后重试...")
            time.sleep(3)
            try:
                response_text = self._do_call(messages)
            except Exception as e:
                logger.error(f"Rate limit 重试失败，返回降级文本。错误：{e}")
                return FALLBACK_NARRATIVE
        except APIError as e:
            # 其他 API 错误（认证失败、服务器错误等）
            logger.error(f"API 调用失败，返回降级文本。错误：{e}")
            return FALLBACK_NARRATIVE
        except Exception as e:
            # 兜底：其他未知错误
            logger.error(f"未知错误，返回降级文本。错误：{e}")
            return FALLBACK_NARRATIVE

        # ── 如果需要 JSON，验证格式 ──
        if expect_json:
            response_text = self._ensure_json(messages, response_text)

        return response_text

    # ──────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────

    def _do_call(self, messages: list[dict]) -> str:
        """
        实际发起一次 API 请求。
        抛出异常由上层 call() 处理，不在这里捕获。
        """
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            timeout=self.timeout,
        )
        # 取出第一个 choice 的文本内容，去除首尾空白
        return completion.choices[0].message.content.strip()

    def _ensure_json(self, original_messages: list[dict], response_text: str) -> str:
        """
        验证返回内容是否为合法 JSON。
        策略：
          1. 直接解析
          2. 尝试从第一次响应中提取 JSON（处理 JSON 后跟额外文字的情况）
          3. 附加 JSON 强调指令重试一次
          4. 再次失败则返回 FALLBACK_CARD_RESPONSE
        """
        # 先尝试解析当前返回
        if self._is_valid_json(response_text):
            return response_text

        # 尝试直接从第一次响应提取 JSON（省一次 API 调用）
        extracted = self._extract_json(response_text)
        if extracted:
            logger.info("从第一次响应中成功提取 JSON")
            return extracted

        # JSON 解析失败，附加强调指令重试
        logger.warning(f"AI 返回内容不是合法 JSON，正在重试并附加格式要求...")

        # 构造带有 JSON 强调的消息列表（在最后追加一条 user 消息）
        retry_messages = list(original_messages) + [
            {
                "role": "user",
                "content": (
                    "注意：你必须只返回严格的 JSON 格式，不得包含任何多余文字、"
                    "代码块标记（```json）或注释。请重新输出符合格式要求的 JSON。"
                ),
            }
        ]

        try:
            retry_text = self._do_call(retry_messages)
            if self._is_valid_json(retry_text):
                return retry_text
            # 重试后仍然不是合法 JSON，尝试从内容中提取 JSON
            extracted = self._extract_json(retry_text)
            if extracted:
                return extracted
            logger.error(f"重试后仍非合法 JSON，返回降级文本。内容：{retry_text[:200]}")
            return FALLBACK_CARD_RESPONSE
        except Exception as e:
            logger.error(f"JSON 重试调用失败，返回降级文本。错误：{e}")
            return FALLBACK_CARD_RESPONSE

    def _is_valid_json(self, text: str) -> bool:
        """检查字符串是否为合法 JSON"""
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    def _extract_json(self, text: str) -> str:
        """
        尝试从文本中提取 JSON 内容。
        处理两种常见情况：
          1. JSON 被包在 ```json ... ``` 代码块中
          2. JSON 合法但后面跟着多余文字（如解释说明）
        """
        text = text.strip()

        # ── 情况1：markdown 代码块 ──
        if text.startswith("```"):
            lines = text.split("\n")
            inner_lines = []
            for line in lines[1:]:
                if line.strip() == "```":
                    break
                inner_lines.append(line)
            candidate = "\n".join(inner_lines).strip()
            if self._is_valid_json(candidate):
                return candidate

        # ── 情况2：JSON 后面跟着多余文字 ──
        # 找第一个 { 到最后一个 } 之间的内容，尝试解析
        start = text.find('{')
        if start != -1:
            end = text.rfind('}')
            if end > start:
                candidate = text[start:end + 1]
                if self._is_valid_json(candidate):
                    return candidate

        return ""
