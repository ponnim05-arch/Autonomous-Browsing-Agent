import os
from unittest.mock import patch
from agent_framework.config import AgentConfig


def test_default_nvidia_api_key_fallback():
    # When no NVIDIA_API_KEY is in environment and no .env file, defaults securely to empty string
    with patch("agent_framework.config._reload_env"), patch.dict(os.environ, {}, clear=True):
        config = AgentConfig()
        assert config.nvidia_api_key == ""


def test_custom_nvidia_api_key_override():
    # When custom NVIDIA_API_KEY is provided, it overrides the default
    custom_key = "nvapi-custom-test-key-12345"
    with patch.dict(os.environ, {"NVIDIA_API_KEY": custom_key}, clear=True):
        config = AgentConfig()
        assert config.nvidia_api_key == custom_key
