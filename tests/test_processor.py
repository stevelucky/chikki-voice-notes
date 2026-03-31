"""Tests for multi-provider LLM dispatch in processor."""
import json
from unittest.mock import MagicMock, patch
import pytest


def test_call_llm_gemini_dispatches_genai():
    """_call_llm with gemini provider calls google.genai."""
    from src.processor import _call_llm

    mock_response = MagicMock()
    mock_response.text = json.dumps({"title": "Test"})
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("src.processor.genai") as mock_genai:
        mock_genai.Client.return_value = mock_client
        result = _call_llm("gemini", "gemini-flash", "sys prompt", "user prompt", 0.3)

    assert result == json.dumps({"title": "Test"})
    mock_client.models.generate_content.assert_called_once()


def test_call_llm_openai_dispatches_chat_completions():
    """_call_llm with openai provider calls openai.chat.completions.create."""
    from src.processor import _call_llm

    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({"title": "OpenAI Test"})
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("src.processor.OpenAI") as mock_openai_cls:
        mock_openai_cls.return_value = mock_client
        result = _call_llm("openai", "gpt-4o", "sys prompt", "user prompt", 0.3)

    assert result == json.dumps({"title": "OpenAI Test"})
    mock_client.chat.completions.create.assert_called_once()


def test_call_llm_anthropic_dispatches_messages():
    """_call_llm with anthropic provider calls anthropic.messages.create."""
    from src.processor import _call_llm

    mock_response = MagicMock()
    mock_response.content[0].text = json.dumps({"title": "Anthropic Test"})
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch("src.processor.Anthropic") as mock_anthropic_cls:
        mock_anthropic_cls.return_value = mock_client
        result = _call_llm("anthropic", "claude-opus-4-6", "sys prompt", "user prompt", 0.3)

    assert result == json.dumps({"title": "Anthropic Test"})
    mock_client.messages.create.assert_called_once()


def test_call_llm_unknown_provider_raises():
    """_call_llm raises ValueError for unknown provider."""
    from src.processor import _call_llm

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        _call_llm("unknown_provider", "some-model", "sys", "prompt", 0.3)
