from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lecture_summary_pipeline.client import (
    OpenAICompatibleClient,
    _is_official_deepseek_base_url,
    _thinking_kwargs,
)


class ThinkingConfigTests(unittest.TestCase):
    def test_official_api_nests_max_effort_inside_thinking_object(self) -> None:
        self.assertEqual(
            _thinking_kwargs(official_deepseek=True, reasoning_effort="max"),
            {
                "extra_body": {
                    "thinking": {
                        "type": "enabled",
                        "reasoning_effort": "max",
                    }
                }
            },
        )

    def test_compatible_endpoint_uses_enable_thinking(self) -> None:
        self.assertEqual(
            _thinking_kwargs(official_deepseek=False, reasoning_effort="max"),
            {"extra_body": {"enable_thinking": True}},
        )

    def test_official_endpoint_detection_ignores_path_and_trailing_slash(self) -> None:
        self.assertTrue(_is_official_deepseek_base_url("https://api.deepseek.com/v1/"))
        self.assertFalse(
            _is_official_deepseek_base_url(
                "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
        )


class CredentialResolutionTests(unittest.TestCase):
    def test_missing_api_key_raises_error_naming_all_env_vars(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LLM_API_KEY") as ctx:
                OpenAICompatibleClient()
        self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_explicit_api_key_wins_over_env(self) -> None:
        with patch.dict("os.environ", {"LLM_API_KEY": "env-key"}, clear=True):
            client = OpenAICompatibleClient(api_key="explicit-key")
        self.assertEqual(client._sync_client.api_key, "explicit-key")

    def test_llm_api_key_takes_precedence_over_fallback_env_vars(self) -> None:
        env = {"LLM_API_KEY": "llm-key", "DEEPSEEK_API_KEY": "deepseek-key"}
        with patch.dict("os.environ", env, clear=True):
            client = OpenAICompatibleClient()
        self.assertEqual(client._sync_client.api_key, "llm-key")

    def test_deepseek_and_openai_env_vars_are_accepted_fallbacks(self) -> None:
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "deepseek-key"}, clear=True):
            client = OpenAICompatibleClient()
        self.assertEqual(client._sync_client.api_key, "deepseek-key")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key"}, clear=True):
            client = OpenAICompatibleClient()
        self.assertEqual(client._sync_client.api_key, "openai-key")

    def test_base_url_resolution_order_and_default(self) -> None:
        def resolved_base_url(client: OpenAICompatibleClient) -> str:
            return str(client._sync_client.base_url).rstrip("/")

        env = {"LLM_API_KEY": "key", "LLM_BASE_URL": "https://env.example/v1"}
        with patch.dict("os.environ", env, clear=True):
            client = OpenAICompatibleClient(base_url="https://explicit.example/v1")
            self.assertEqual(resolved_base_url(client), "https://explicit.example/v1")
            client = OpenAICompatibleClient()
            self.assertEqual(resolved_base_url(client), "https://env.example/v1")
        with patch.dict(
            "os.environ",
            {"LLM_API_KEY": "key", "DEEPSEEK_BASE_URL": "https://ds.example/v1"},
            clear=True,
        ):
            client = OpenAICompatibleClient()
            self.assertEqual(resolved_base_url(client), "https://ds.example/v1")
        with patch.dict("os.environ", {"LLM_API_KEY": "key"}, clear=True):
            client = OpenAICompatibleClient()
            self.assertEqual(resolved_base_url(client), "https://api.deepseek.com")

    def test_provider_specific_keys_are_not_silently_mixed(self) -> None:
        with patch.dict(
            "os.environ",
            {"ALI_API_KEY": "ali-key", "DASHSCOPE_API_KEY": "dashscope-key"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "LLM_API_KEY"):
                OpenAICompatibleClient()


class CacheUsageTests(unittest.TestCase):
    def _client(
        self, base_url: str = "https://api.deepseek.com"
    ) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(api_key="test-key", base_url=base_url)

    def test_deepseek_cache_fields_are_captured(self) -> None:
        client = self._client()
        client._record_cache_usage(
            SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_cache_hit_tokens=120,
                    prompt_cache_miss_tokens=30,
                )
            )
        )
        self.assertEqual(
            client.last_cache_usage(),
            {"prompt_cache_hit_tokens": 120, "prompt_cache_miss_tokens": 30},
        )

    def test_usage_without_cache_fields_yields_none(self) -> None:
        client = self._client()
        client._record_cache_usage(
            SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100))
        )
        self.assertIsNone(client.last_cache_usage())

    def test_openrouter_cached_tokens_are_normalised(self) -> None:
        client = self._client("https://openrouter.ai/api/v1")
        client._record_cache_usage(
            SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=1000,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=800),
                )
            )
        )
        self.assertEqual(
            client.last_cache_usage(),
            {"prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200},
        )

    def test_complete_text_records_usage_for_the_pipeline(self) -> None:
        client = self._client()
        client._sync_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[
                            SimpleNamespace(message=SimpleNamespace(content="hello"))
                        ],
                        usage=SimpleNamespace(
                            prompt_cache_hit_tokens=5,
                            prompt_cache_miss_tokens=7,
                        ),
                    )
                )
            )
        )
        self.assertEqual(
            client.complete_text(
                model="deepseek-v4-pro", messages=[], temperature=0.0
            ),
            "hello",
        )
        self.assertEqual(
            client.last_cache_usage(),
            {"prompt_cache_hit_tokens": 5, "prompt_cache_miss_tokens": 7},
        )


if __name__ == "__main__":
    unittest.main()
