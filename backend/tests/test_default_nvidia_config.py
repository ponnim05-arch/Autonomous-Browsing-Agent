import os
from unittest.mock import patch
from agent_framework.config import AgentConfig, DEFAULT_NVIDIA_API_KEY


def test_default_nvidia_api_key_fallback():
    # When no NVIDIA_API_KEY is in environment, fallback to DEFAULT_NVIDIA_API_KEY
    with patch.dict(os.environ, {}, clear=True):
        config = AgentConfig()
        assert config.nvidia_api_key == DEFAULT_NVIDIA_API_KEY
        assert config.nvidia_api_key.startswith("nvapi-")


def test_custom_nvidia_api_key_override():
    # When custom NVIDIA_API_KEY is provided, it overrides the default
    custom_key = "nvapi-custom-test-key-12345"
    with patch.dict(os.environ, {"NVIDIA_API_KEY": custom_key}, clear=True):
        config = AgentConfig()
        assert config.nvidia_api_key == custom_key
