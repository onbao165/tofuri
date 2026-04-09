import json
import unittest

from tofuri import (
    build_translation_request_payload,
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
        self.assertEqual(validated["api"]["provider"], "openai")

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


if __name__ == "__main__":
    unittest.main()
