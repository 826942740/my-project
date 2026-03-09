"""
client.py — OpenAI 兼容 API 客户端

负责与 AI 大模型通信，支持任意 OpenAI 格式 endpoint（DeepSeek / Claude / GPT / 本地模型）。
所有配置通过环境变量读取，不写入代码。

错误处理策略：
  - 网络超时：重试 1 次，再失败直接抛出异常
  - JSON 格式不正确：重试 1 次附加格式提示，再失败抛出 ValueError
  - Rate limit：等待 3 秒后重试 1 次，再失败直接抛出异常
  - 其他错误：直接抛出，由上层路由处理
"""

import os
import re
import time
import json
import logging
from openai import OpenAI, APITimeoutError, RateLimitError

# 配置日志，方便排查问题
logger = logging.getLogger(__name__)


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
        失败时直接抛出异常，由上层路由决定如何响应。

        参数：
            messages    — OpenAI 格式消息列表
            expect_json — True 时验证返回是否为合法 JSON，失败则重试一次

        重试策略：
            - 超时：重试 1 次
            - Rate limit：等待 3 秒重试 1 次
            - JSON 格式错误：附加格式要求重试 1 次
            - 重试仍失败：抛出异常
        """
        # ── 第一次调用 ──
        try:
            response_text = self._do_call(messages, force_json=expect_json)
        except APITimeoutError:
            logger.warning("API 请求超时，重试中（1/1）...")
            # 超时重试一次，再失败直接抛出
            response_text = self._do_call(messages, force_json=expect_json)
        except RateLimitError:
            logger.warning("触发 Rate limit，等待 3 秒后重试...")
            time.sleep(3)
            response_text = self._do_call(messages, force_json=expect_json)
        # 其他异常（APIError、网络错误等）直接抛出

        # ── 验证 JSON 格式 ──
        if expect_json:
            response_text = self._ensure_json(messages, response_text)

        return response_text

    # ──────────────────────────────────────────────
    # 流式调用方法
    # ──────────────────────────────────────────────

    def stream_call(self, messages: list[dict], force_json: bool = False):
        """
        调用 AI API（stream=True），逐块 yield 原始文本 chunk。
        不做 JSON 验证，由调用方负责解析。

        参数：
            force_json — True 时开启 response_format=json_object，
                         让模型强制输出合法 JSON。
        """
        kwargs = dict(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            timeout=self.timeout,
            stream=True,
        )
        if force_json:
            kwargs["response_format"] = {"type": "json_object"}
        logger.debug(
            f"[AI流式请求] model={self.model} | force_json={force_json} | messages数量={len(messages)}"
        )
        try:
            stream = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            # 如果 API 不支持 response_format + stream 组合，降级
            if force_json and ("response_format" in str(e) or "400" in str(e)):
                logger.warning("API 不支持流式 response_format，降级为普通流式")
                kwargs.pop("response_format", None)
                stream = self._client.chat.completions.create(**kwargs)
            else:
                raise
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ──────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────

    def _do_call(self, messages: list[dict], force_json: bool = False) -> str:
        """
        实际发起一次 API 请求，抛出异常由上层处理。
        force_json=True 时尝试开启 response_format=json_object，
        若 API 不支持该参数会自动降级为普通调用。
        """
        kwargs = dict(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            timeout=self.timeout,
        )
        if force_json:
            kwargs["response_format"] = {"type": "json_object"}

        logger.debug(
            f"[AI请求] model={self.model} | force_json={force_json} | "
            f"messages数量={len(messages)} | "
            f"最后一条user内容前60字：{next((m['content'][:60] for m in reversed(messages) if m['role']=='user'), '')!r}"
        )

        try:
            completion = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            # 如果是因为 response_format 不被 API 支持，降级为普通调用
            if force_json and ("response_format" in str(e) or "400" in str(e)):
                logger.warning("API 不支持 response_format，降级为普通调用")
                kwargs.pop("response_format")
                completion = self._client.chat.completions.create(**kwargs)
            else:
                raise

        result = completion.choices[0].message.content.strip()

        # 推理模型（如 MiniMax-M2.5）会在正文前输出 <think>...</think> 思考过程
        # 剔除后只保留真正的输出内容
        cleaned = re.sub(r'<think>.*?</think>\s*', '', result, flags=re.DOTALL).strip()
        if cleaned != result:
            logger.debug(f"[AI响应] 已剔除 <think> 块，剩余前100字：{cleaned[:100]!r}")
        else:
            logger.debug(f"[AI响应] 前100字：{result[:100]!r}")

        return cleaned

    def _ensure_json(self, original_messages: list[dict], response_text: str) -> str:
        """
        验证返回内容是否为合法 JSON。
        失败则附加格式要求重试一次。
        重试后仍不合法则抛出 ValueError，由上层路由处理。
        """
        # 直接解析
        if self._is_valid_json(response_text):
            return response_text

        # 尝试从第一次响应中提取 JSON
        extracted = self._extract_json(response_text)
        if extracted:
            logger.info("从第一次响应中成功提取 JSON")
            return extracted

        # 附加格式要求重试一次
        # 只保留 system 消息和 user 消息，过滤掉 assistant 消息
        # 避免把包含非 JSON 的 assistant 历史带入重试，导致 AI 再次混乱输出纯文本
        logger.warning("AI 返回内容不是合法 JSON，附加格式要求重试（过滤历史 assistant 消息）...")
        retry_messages = [
            m for m in original_messages if m.get("role") in ("system", "user")
        ] + [
            {
                "role": "user",
                "content": (
                    "注意：你必须只返回严格的 JSON 格式，不得包含任何多余文字、"
                    "代码块标记（```json）或注释。请重新输出符合格式要求的 JSON。"
                ),
            }
        ]

        retry_text = self._do_call(retry_messages)  # 失败则抛出

        if self._is_valid_json(retry_text):
            return retry_text

        extracted = self._extract_json(retry_text)
        if extracted:
            return extracted

        # 重试后仍无效，抛出异常
        raise ValueError(
            f"AI 返回内容无法解析为 JSON（已重试一次）。"
            f"内容前100字：{retry_text[:100]}"
        )

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
          2. JSON 合法但后面跟着多余文字
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
        start = text.find('{')
        if start != -1:
            end = text.rfind('}')
            if end > start:
                candidate = text[start:end + 1]
                if self._is_valid_json(candidate):
                    return candidate

        return ""
