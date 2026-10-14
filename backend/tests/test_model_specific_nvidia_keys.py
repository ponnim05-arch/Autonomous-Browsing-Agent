import os
from unittest.mock import AsyncMock, patch

import pytest

from agent_framework.config import AgentConfig
from agent_framework.llm_client import LLMClient


@pytest.mark.asyncio
async def test_fast_model_uses_its_specific_nvidia_key():
    env = {
        "LLM_PROVIDER": "nvidia",
        "FAST_MODEL": "fast-model",
        "REASONING_MODEL": "reasoning-model",
        "NVIDIA_FAST_API_KEY": "fast-test-key",
        "NVIDIA_REASONING_API_KEY": "reasoning-test-key",
        "NVIDIA_API_KEY": "shared-test-key",
    }
    with patch.dict(os.environ, env, clear=True):
        client = LLMClient(AgentConfig())
        with patch.object(
            client, "_call_nvidia_model", AsyncMock(return_value=("ok", 1))
        ) as call:
            await client.complete_fast("prompt")

    assert call.await_args.kwargs["api_key"] == "fast-test-key"


@pytest.mark.asyncio
async def test_reasoning_model_uses_its_specific_nvidia_key():
    env = {
        "LLM_PROVIDER": "nvidia",
        "FAST_MODEL": "fast-model",
        "REASONING_MODEL": "reasoning-model",
        "NVIDIA_FAST_API_KEY": "fast-test-key",
        "NVIDIA_REASONING_API_KEY": "reasoning-test-key",
        "NVIDIA_API_KEY": "shared-test-key",
    }
    with patch.dict(os.environ, env, clear=True):
        client = LLMClient(AgentConfig())
        with patch.object(
            client, "_call_nvidia_model", AsyncMock(return_value=("ok", 1))
        ) as call:
            await client.complete_reasoning("prompt")

    assert call.await_args.kwargs["api_key"] == "reasoning-test-key"


@pytest.mark.asyncio
async def test_model_specific_nvidia_keys_fall_back_to_shared_key():
    env = {
        "LLM_PROVIDER": "nvidia",
        "FAST_MODEL": "fast-model",
        "NVIDIA_API_KEY": "shared-test-key",
    }
    with patch.dict(os.environ, env, clear=True):
        client = LLMClient(AgentConfig())
        with patch.object(
            client, "_call_nvidia_model", AsyncMock(return_value=("ok", 1))
        ) as call:
            await client.complete_fast("prompt")

    assert call.await_args.kwargs["api_key"] == "shared-test-key"
