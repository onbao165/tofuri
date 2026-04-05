import unittest

from tofuri import TofuriEngine, render_furigana, render_segment


class FuriganaRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = TofuriEngine()

    def test_split_kanji_nagareru(self) -> None:
        self.assertEqual(
            self.engine.split_kanji("流れる", "ながれる"),
            "<ruby>流<rt>なが</rt></ruby>れる",
        )

    def test_split_kanji_uriba(self) -> None:
        self.assertEqual(
            self.engine.split_kanji("売り場", "うりば"),
            "<ruby>売<rt>う</rt></ruby>り<ruby>場<rt>ば</rt></ruby>",
        )

    def test_split_kanji_tabemono(self) -> None:
        self.assertEqual(
            self.engine.split_kanji("食べ物", "たべもの"),
            "<ruby>食<rt>た</rt></ruby>べ<ruby>物<rt>もの</rt></ruby>",
        )

    def test_split_kanji_arukimawaru(self) -> None:
        self.assertEqual(
            self.engine.split_kanji("歩き回る", "あるきまわる"),
            "<ruby>歩<rt>ある</rt></ruby>き<ruby>回<rt>まわ</rt></ruby>る",
        )

    def test_preserve_existing_ruby_block(self) -> None:
        text = "<ruby>受賞<rt>じゅしょう</rt></ruby>した。"
        output = render_furigana(self.engine, text, dedupe_ruby=True)
        self.assertEqual(output, text)

    def test_segment_preserves_line_breaks(self) -> None:
        text = "日本語です。\n明日も勉強する。"
        output = render_segment(self.engine, text, json_mode=False)
        self.assertEqual(output.count("\n"), text.count("\n"))

    def test_furigana_preserves_line_breaks(self) -> None:
        text = "日本語です。\n明日も勉強する。"
        output = render_furigana(self.engine, text, dedupe_ruby=True)
        self.assertEqual(output.count("\n"), text.count("\n"))


if __name__ == "__main__":
    unittest.main()
