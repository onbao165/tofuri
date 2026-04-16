"""Tests for preset combined mode (furigana + vocabulary + translation)."""
import json
import unittest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tofuri import (
    TofuriEngine,
    format_vocab_line,
    assemble_preset_callout,
    extract_translation_for_preset,
    extract_openai_full_dissection,
    extract_natural_translation,
    _render_vocab_for_preset,
)


class TestFormatVocabLine(unittest.TestCase):
    """Test vocabulary line formatting."""

    def test_with_vietnamese_definition(self):
        result = format_vocab_line(
            word="賞", reading="しょう",
            definition_vi="giải thưởng",
            definition=None, definition_en=None,
        )
        self.assertEqual(result, "賞「しょう」 giải thưởng")

    def test_with_sino_vietnamese(self):
        result = format_vocab_line(
            word="人間", reading="にんげん",
            definition_vi="CON NGƯỜI - nhân gian; nhân loại",
            definition=None, definition_en=None,
        )
        self.assertEqual(result, "人間「にんげん」CON NGƯỜI - nhân gian; nhân loại")

    def test_with_english_definition(self):
        result = format_vocab_line(
            word="便利店", reading="べんりてん",
            definition_vi=None, definition=None,
            definition_en="convenience store",
        )
        self.assertEqual(result, "便利店「べんりてん」 convenience store")

    def test_undefined_marker(self):
        result = format_vocab_line(
            word="村田", reading="むらた",
            definition_vi=None, definition=None, definition_en=None,
        )
        self.assertEqual(result, "村田「むらた」? (undefined)")

    def test_no_reading(self):
        result = format_vocab_line(
            word="便利店", reading=None,
            definition_vi=None, definition=None, definition_en=None,
        )
        self.assertEqual(result, "便利店? (undefined)")


class TestAssemblePresetCallout(unittest.TestCase):
    """Test markdown callout assembly."""

    def test_basic_callout(self):
        result = assemble_preset_callout(
            furigana="<ruby>百<rt>ひゃく</rt></ruby>",
            vocab="百「ひゃく」 number",
            translation="One hundred",
        )
        self.assertIn(">[!note]- Breakdown", result)
        self.assertIn(">### **Furigana**", result)
        self.assertIn(">### **Vocabulary**", result)
        self.assertIn(">### **Translation**", result)
        self.assertIn("><ruby>百<rt>ひゃく</rt></ruby>", result)
        self.assertIn(">百「ひゃく」 number", result)
        self.assertIn(">One hundred", result)

    def test_error_in_translation(self):
        result = assemble_preset_callout(
            furigana="<ruby>百<rt>ひゃく</rt></ruby>",
            vocab="百「ひゃく」 number",
            translation="",
            translation_error="API quota exceeded",
        )
        self.assertIn(">[!error] Translation failed: API quota exceeded", result)
        self.assertNotIn(">### **Translation**\n>", result.split(">### **Translation**")[1][:20])

    def test_multiline_furigana(self):
        furigana = "Line 1\nLine 2\n\nLine 3"
        result = assemble_preset_callout(
            furigana=furigana,
            vocab="",
            translation="",
        )
        self.assertIn(">Line 1", result)
        self.assertIn(">Line 2", result)
        self.assertIn(">", result)  # empty line
        self.assertIn(">Line 3", result)


class TestExtractTranslation(unittest.TestCase):
    """Test translation extraction for preset mode."""

    def test_deepl_natural_only(self):
        deepl_response = {
            "status": "ok",
            "translations": [
                {"index": 1, "source": "こんにちは", "natural": "Hello", "provider": "deepl"}
            ]
        }
        result = extract_natural_translation(deepl_response, "deepl")
        self.assertEqual(result, "Hello")

    def test_openai_full_dissection(self):
        openai_response = {
            "status": "ok",
            "sentences": [
                {
                    "index": 1,
                    "source": "こんにちは",
                    "segmented": "こんにちは",
                    "literal": "Hello",
                    "natural": "Hello there",
                    "grammar_notes": [
                        {"topic": "Greeting", "explanation": "Standard greeting"}
                    ],
                }
            ]
        }
        result = extract_openai_full_dissection(openai_response["sentences"])
        self.assertIn("Source: こんにちは", result)
        self.assertIn("Natural: Hello there", result)
        self.assertIn("Greeting: Standard greeting", result)

    def test_extract_translation_for_preset_deepl(self):
        deepl_json = json.dumps({
            "status": "ok",
            "translations": [
                {"index": 1, "source": "こんにちは", "natural": "Hello", "provider": "deepl"}
            ]
        })
        result = extract_translation_for_preset(deepl_json, "deepl")
        self.assertEqual(result, "Hello")

    def test_extract_translation_for_preset_openai(self):
        openai_json = json.dumps({
            "status": "ok",
            "sentences": [
                {
                    "index": 1,
                    "source": "こんにちは",
                    "segmented": "こんにちは",
                    "literal": "Hello",
                    "natural": "Hello there",
                    "grammar_notes": [],
                }
            ]
        })
        result = extract_translation_for_preset(openai_json, "openai")
        self.assertIn("Natural: Hello there", result)

    def test_rejected_translation(self):
        rejected_json = json.dumps({
            "status": "rejected",
            "reason_code": "NON_JAPANESE_INPUT",
            "message": "Input is not Japanese",
            "input": "Hello world",
        })
        with self.assertRaises(RuntimeError) as ctx:
            extract_translation_for_preset(rejected_json, "deepl")
        self.assertIn("Translation rejected", str(ctx.exception))


class TestRenderVocabForPreset(unittest.TestCase):
    """Test vocabulary rendering for preset mode."""

    @patch("tofuri.TofuriEngine")
    @patch("tofuri.load_lookup_config")
    @patch("tofuri.load_local_dictionary")
    def test_includes_undefined_tokens(self, mock_load_local, mock_load_config, mock_engine):
        """Test that tokens without definitions are included with ? (undefined) marker."""
        from tofuri import TokenInfo
        
        mock_load_config.return_value = {"exclude_tokens": [], "exclude_pos": []}
        mock_load_local.return_value = []
        
        # Mock engine to return specific tokens
        mock_engine.tokenize.return_value = [
            TokenInfo(surface="音", reading_hira="おと", pos="名詞"),
            TokenInfo(surface="を", reading_hira="を", pos="助詞"),
        ]
        
        result = _render_vocab_for_preset(
            mock_engine, "音",
            dict_source="none",
            dict_lang="en",
            lookup_config_path="",
        )
        
        # Should include the token even without definition
        self.assertIn("音「おと」? (undefined)", result)


class TestPresetCalloutStructure(unittest.TestCase):
    """Test that preset callout has correct structure."""

    def test_section_order(self):
        result = assemble_preset_callout(
            furigana="F",
            vocab="V",
            translation="T",
        )
        lines = result.split("\n")
        
        furigana_idx = next(i for i, l in enumerate(lines) if "**Furigana**" in l)
        vocab_idx = next(i for i, l in enumerate(lines) if "**Vocabulary**" in l)
        translation_idx = next(i for i, l in enumerate(lines) if "**Translation**" in l)
        
        self.assertLess(furigana_idx, vocab_idx)
        self.assertLess(vocab_idx, translation_idx)

    def test_all_sections_have_blockquote_prefix(self):
        result = assemble_preset_callout(
            furigana="Kanji text",
            vocab="Word definition",
            translation="Translated text",
        )
        for line in result.split("\n")[1:]:  # Skip first line (callout header)
            if line:  # Non-empty lines should have > prefix
                self.assertTrue(line.startswith(">"), f"Line missing > prefix: {line}")


if __name__ == "__main__":
    unittest.main()
