"""
llm_client.py — Unified LLM interface for Gemini, OpenAI, and Anthropic.

Usage:
    client = LLMClient(config)
    response, tokens = await client.complete("Your prompt here")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import AgentConfig, default_config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when all LLM providers fail."""


class LLMClient:
    """Async LLM client with automatic provider selection, retry, and model routing."""

    def __init__(self, config: AgentConfig = default_config):
        self.config = config
        self._provider = config.llm_provider.lower()
        # Performance tracking
        self._call_count = 0
        self._fast_call_count = 0
        self._reasoning_call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    @property
    def call_stats(self) -> dict:
        """Return current call statistics."""
        return {
            "total_calls": self._call_count,
            "fast_calls": self._fast_call_count,
            "reasoning_calls": self._reasoning_call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
        }

    def reset_stats(self) -> None:
        """Reset call statistics for a new task."""
        self._call_count = 0
        self._fast_call_count = 0
        self._reasoning_call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    # ── Public API ────────────────────────────────────────────────

    async def complete(self, prompt: str, temperature: Optional[float] = None) -> tuple[str, int]:
        """
        Send a prompt and return (response_text, tokens_used).
        Retries up to 3 times with exponential backoff on transient errors.
        """
        self._call_count += 1
        temp = temperature if temperature is not None else self.config.llm_temperature
        try:
            if self._provider in ("nvidia", "deepseek"):
                return await self._call_nvidia(prompt, temp)
            elif self._provider == "gemini":
                return await self._call_gemini(prompt, temp)
            elif self._provider == "openai":
                return await self._call_openai(prompt, temp)
            elif self._provider == "anthropic":
                return await self._call_anthropic(prompt, temp)
            else:
                # Default fallback to NVIDIA
                return await self._call_nvidia(prompt, temp)
        except Exception as e:
            logger.error(f"LLM call failed ({self._provider}): {e}")
            raise LLMError(str(e)) from e

    async def complete_fast(self, prompt: str, temperature: float = 0.1) -> tuple[str, int]:
        """
        Use the fast/lightweight model for simple tasks.
        Lower max_tokens, faster response.
        """
        self._call_count += 1
        self._fast_call_count += 1
        logger.debug(f"[LLM] Fast model call ({self.config.fast_model})")
        try:
            return await self._call_nvidia_model(
                prompt, temperature,
                model=self.config.fast_model,
                max_tokens=self.config.fast_model_max_tokens,
                thinking=False,
            )
        except Exception as e:
            logger.warning(f"[LLM] Fast model failed: {e}. Falling back to default.")
            return await self.complete(prompt, temperature)

    async def complete_reasoning(self, prompt: str, temperature: float = 0.2) -> tuple[str, int]:
        """
        Use the strong reasoning model for complex tasks.
        Higher max_tokens, deeper reasoning.
        """
        self._call_count += 1
        self._reasoning_call_count += 1
        logger.debug(f"[LLM] Reasoning model call ({self.config.reasoning_model})")
        try:
            return await self._call_nvidia_model(
                prompt, temperature,
                model=self.config.reasoning_model,
                max_tokens=self.config.reasoning_model_max_tokens,
                thinking=self.config.llm_thinking,
            )
        except Exception as e:
            logger.warning(f"[LLM] Reasoning model failed: {e}. Falling back to default.")
            return await self.complete(prompt, temperature)

    # ── NVIDIA (DeepSeek & OpenAI-compatible) ─────────────────────

    def _get_nvidia_client(self):
        from openai import AsyncOpenAI

        api_key = self.config.nvidia_api_key or self.config.openai_api_key
        if not api_key:
            raise LLMError("NVIDIA_API_KEY is not set.")

        if not hasattr(self, "_nvidia_client") or self._nvidia_client is None:
            self._nvidia_client = AsyncOpenAI(
                base_url=self.config.nvidia_base_url,
                api_key=api_key,
                timeout=45.0,
            )
        return self._nvidia_client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call_nvidia_model(
        self, prompt: str, temperature: float, *,
        model: str, max_tokens: int, thinking: bool = False,
    ) -> tuple[str, int]:
        """Call NVIDIA API with explicit model and token limit."""
        client = self._get_nvidia_client()

        kwargs: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        if thinking:
            kwargs["extra_body"] = {
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": self.config.llm_reasoning_effort,
                }
            }
            kwargs["top_p"] = 0.95

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            if "extra_body" in kwargs and any(
                k in str(exc).lower()
                for k in ("extra_body", "chat_template_kwargs", "extra_fields", "validation")
            ):
                kwargs.pop("extra_body", None)
                resp = await client.chat.completions.create(**kwargs)
            else:
                raise

        message = resp.choices[0].message
        text = message.content or ""
        reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
        if reasoning:
            logger.debug(f"[LLM] Reasoning: {reasoning[:100]}")
        if not text and reasoning:
            text = reasoning

        tokens = resp.usage.total_tokens if resp.usage else len(text) // 4
        return text, int(tokens)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call_nvidia(self, prompt: str, temperature: float) -> tuple[str, int]:
        client = self._get_nvidia_client()
        model_name = self.config.llm_model

        kwargs: dict = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": self.config.max_tokens_per_call,
            "stream": False,
        }

        # If thinking/reasoning is explicitly enabled, pass chat_template_kwargs
        if self.config.llm_thinking:
            kwargs["extra_body"] = {
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": self.config.llm_reasoning_effort,
                }
            }
            kwargs["top_p"] = 0.95

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Fallback if extra_body is not supported by target model
            if "extra_body" in kwargs and any(k in str(exc).lower() for k in ("extra_body", "chat_template_kwargs", "extra_fields", "validation")):
                kwargs.pop("extra_body", None)
                resp = await client.chat.completions.create(**kwargs)
            else:
                raise

        message = resp.choices[0].message
        text = message.content or ""
        reasoning = getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)
        if reasoning:
            logger.debug(f"LLM Reasoning: {reasoning}")
        if not text and reasoning:
            text = reasoning

        tokens = resp.usage.total_tokens if resp.usage else len(text) // 4
        return text, int(tokens)

    # ── Gemini ────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call_gemini(self, prompt: str, temperature: float) -> tuple[str, int]:
        api_key = self.config.gemini_api_key
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set.")

        try:
            # New official Google GenAI SDK (google-genai)
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            gen_config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=self.config.max_tokens_per_call,
            )
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.config.llm_model,
                contents=prompt,
                config=gen_config,
            )
            text = response.text or ""
            tokens = getattr(response.usage_metadata, "total_token_count", len(text) // 4)
            return text, int(tokens)
        except (ImportError, AttributeError):
            # Fallback to google-generativeai
            import google.generativeai as legacy_genai

            legacy_genai.configure(api_key=api_key)
            model = legacy_genai.GenerativeModel(
                model_name=self.config.llm_model,
                generation_config=legacy_genai.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=self.config.max_tokens_per_call,
                ),
            )
            response = await asyncio.to_thread(model.generate_content, prompt)
            text = response.text or ""
            tokens = getattr(response.usage_metadata, "total_token_count", len(text) // 4)
            return text, int(tokens)

    # ── OpenAI ────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call_openai(self, prompt: str, temperature: float) -> tuple[str, int]:
        from openai import AsyncOpenAI  # lazy import

        api_key = self.config.openai_api_key
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set.")
        client = AsyncOpenAI(api_key=api_key)

        resp = await client.chat.completions.create(
            model=self.config.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=self.config.max_tokens_per_call,
        )
        text = resp.choices[0].message.content or ""
        tokens = resp.usage.total_tokens if resp.usage else len(text) // 4
        return text, tokens

    # ── Anthropic ─────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _call_anthropic(self, prompt: str, temperature: float) -> tuple[str, int]:
        import anthropic as ant  # lazy import

        api_key = self.config.anthropic_api_key
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.")
        client = ant.AsyncAnthropic(api_key=api_key)

        resp = await client.messages.create(
            model=self.config.llm_model,
            max_tokens=self.config.max_tokens_per_call,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        tokens = resp.usage.input_tokens + resp.usage.output_tokens
        return text, tokens
