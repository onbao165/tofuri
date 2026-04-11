import json
import unittest

from tofuri import (
    build_translation_request_payload,
    decode_piped_stdin_bytes,
    map_deepl_target_language,
    render_deepl_simple_output,
    render_deepl_span_output,
    validate_translation_config,
    validate_translation_json_payload,
)


def valid_config() -> dict:
    return {
        "api": {
            "provider": "openai",
            "api_key": "test-key",
            "model_default": "gpt-4.1-mini",
        },
        "prompt": {
            "system": "system prompt",
        },
        "response": {
            "schema_version": "1.0",
            "require_json_object": True,
            "required_sections": ["segmented", "literal", "natural", "grammar_notes"],
        },
        "guardrails": {
            "reject_non_japanese_dissection": True,
            "allow_mixed_reference_text": True,
        },
        "audit": {
            "enabled": True,
            "directory": "memory",
            "file_pattern": "translation_audit_{date}.jsonl",
            "timestamp_format": "iso8601_utc",
            "capture_raw_request": True,
            "capture_raw_response": True,
            "redact_api_key": True,
            "token_usage_on_missing": None,
        },
    }


class TranslationContractTests(unittest.TestCase):
    def test_validate_translation_config_accepts_valid_contract(self) -> None:
        config = valid_config()
        validated = validate_translation_config(config)
        self.assertEqual(validated["provider_active"], "openai")

    def test_validate_translation_config_requires_api_key(self) -> None:
        config = valid_config()
        config["api"]["api_key"] = ""
        with self.assertRaises(RuntimeError):
            validate_translation_config(config)

    def test_validate_translation_response_ok_schema(self) -> None:
        payload = {
            "schema_version": "1.0",
            "status": "ok",
            "language": "en",
            "style": "cure-dolly",
            "input": "猫が魚を食べる。",
            "sentences": [
                {
                    "index": 1,
                    "source": "猫が魚を食べる。",
                    "segmented": "猫 / が / 魚 / を / 食べる。",
                    "literal": "As for cat, fish object-marker eat.",
                    "natural": "The cat eats fish.",
                    "grammar_notes": [
                        {
                            "topic": "subject marking",
                            "explanation": "が marks 猫 as subject.",
                        }
                    ],
                }
            ],
        }

        validate_translation_json_payload(
            payload=payload,
            expected_schema_version="1.0",
            required_sections=["segmented", "literal", "natural", "grammar_notes"],
        )

    def test_validate_translation_response_rejected_schema(self) -> None:
        payload = {
            "schema_version": "1.0",
            "status": "rejected",
            "reason_code": "NON_JAPANESE_INPUT",
            "message": "Input is not valid Japanese text for dissection.",
            "input": "hello",
        }

        validate_translation_json_payload(
            payload=payload,
            expected_schema_version="1.0",
            required_sections=["segmented", "literal", "natural", "grammar_notes"],
        )

    def test_build_translation_request_payload_outputs_json(self) -> None:
        payload_text = build_translation_request_payload(
            text="猫が魚を食べる。",
            target_lang="en",
            style="cure-dolly",
            schema_version="1.0",
        )
        payload = json.loads(payload_text)
        self.assertEqual(payload["target_language_code"], "en")
        self.assertIn("security_rules", payload)

    def test_validate_translation_config_deepl_with_provider_blocks(self) -> None:
        config = {
            "provider": {"active": "deepl"},
            "providers": {
                "deepl": {
                    "auth_key": "deepl-key",
                    "api_url": "https://api-free.deepl.com/v2/translate",
                    "formality": "default",
                }
            },
            "prompt": {"system": "system prompt"},
            "response": {
                "schema_version": "1.0",
                "require_json_object": True,
                "required_sections": ["segmented", "literal", "natural", "grammar_notes"],
            },
            "guardrails": {
                "reject_non_japanese_dissection": True,
                "allow_mixed_reference_text": True,
            },
            "audit": {
                "enabled": True,
                "directory": "memory",
                "file_pattern": "translation_audit_{date}.jsonl",
                "timestamp_format": "iso8601_utc",
                "capture_raw_request": True,
                "capture_raw_response": True,
                "redact_api_key": True,
                "token_usage_on_missing": None,
            },
        }

        validated = validate_translation_config(config)
        self.assertEqual(validated["provider_active"], "deepl")
        self.assertEqual(validated["providers"]["deepl"]["auth_key"], "deepl-key")

    def test_deepl_language_mapping_is_en_only(self) -> None:
        self.assertEqual(map_deepl_target_language("en"), "EN")
        with self.assertRaises(RuntimeError):
            map_deepl_target_language("vi")

    def test_render_deepl_simple_output_success(self) -> None:
        payload = {
            "schema_version": "1.0",
            "status": "ok",
            "language": "en",
            "input": "コンビニエンスストアは、音で満ちている。",
            "mode": "translation_only",
            "translations": [
                {
                    "index": 1,
                    "source": "コンビニエンスストアは、音で満ちている。",
                    "natural": "Convenience stores are filled with noise.",
                    "provider": "deepl",
                },
                {
                    "index": 2,
                    "source": "客が入ってくるチャイムの音に、店内を流れる有線放送で新商品を宣伝するアイドルの声。",
                    "natural": "The sound of the doorbell ringing as customers enter.",
                    "provider": "deepl",
                },
            ],
        }

        expected = (
            "コンビニエンスストアは、音で満ちている。\n"
            "Convenience stores are filled with noise.\n\n"
            "客が入ってくるチャイムの音に、店内を流れる有線放送で新商品を宣伝するアイドルの声。\n"
            "The sound of the doorbell ringing as customers enter."
        )
        self.assertEqual(render_deepl_simple_output(payload), expected)

    def test_render_deepl_simple_output_rejected_falls_back_to_json(self) -> None:
        payload = {
            "schema_version": "1.0",
            "status": "rejected",
            "reason_code": "NON_JAPANESE_INPUT",
            "message": "Input is not valid Japanese text for dissection.",
            "input": "hello",
        }

        rendered = render_deepl_simple_output(payload)
        self.assertIn('"status": "rejected"', rendered)
        self.assertTrue(rendered.strip().startswith("{"))

    def test_decode_piped_stdin_bytes_prefers_utf8_for_japanese(self) -> None:
        text = "コンビニエンスストアは、音で満ちている。"
        raw = text.encode("utf-8")
        decoded = decode_piped_stdin_bytes(raw, preferred_encoding="cp1252")
        self.assertEqual(decoded, text)

    def test_decode_piped_stdin_bytes_handles_utf16le_without_bom(self) -> None:
        text = "日本語テスト"
        raw = text.encode("utf-16-le")
        decoded = decode_piped_stdin_bytes(raw)
        self.assertEqual(decoded, text)

    def test_render_deepl_span_output_preserves_line_breaks(self) -> None:
        source_text = "猫が魚を食べる。\n犬が走る。"
        payload = {
            "schema_version": "1.0",
            "status": "ok",
            "language": "en",
            "input": source_text,
            "mode": "translation_only",
            "translations": [
                {
                    "index": 1,
                    "source": "猫が魚を食べる。",
                    "natural": "The cat eats fish.",
                    "provider": "deepl",
                },
                {
                    "index": 2,
                    "source": "犬が走る。",
                    "natural": "The dog runs.",
                    "provider": "deepl",
                },
            ],
        }

        rendered = render_deepl_span_output(source_text, payload)
        expected = (
            '<span class="trans-hover" data-meaning="The cat eats fish.">猫が魚を食べる。</span>\n'
            '<span class="trans-hover" data-meaning="The dog runs.">犬が走る。</span>'
        )
        self.assertEqual(rendered, expected)

    def test_render_deepl_span_output_escapes_quotes(self) -> None:
        source_text = "猫。"
        payload = {
            "schema_version": "1.0",
            "status": "ok",
            "language": "en",
            "input": source_text,
            "mode": "translation_only",
            "translations": [
                {
                    "index": 1,
                    "source": "猫。",
                    "natural": 'A "cat" <pet>.',
                    "provider": "deepl",
                }
            ],
        }

        rendered = render_deepl_span_output(source_text, payload)
        self.assertIn('data-meaning="A &quot;cat&quot; &lt;pet&gt;."', rendered)


if __name__ == "__main__":
    unittest.main()
