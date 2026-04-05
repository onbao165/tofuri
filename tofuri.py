import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional

import fugashi
import jaconv

try:
    import requests
except ImportError:
    requests = None


KANJI_REGEX = re.compile(r"[\u4e00-\u9fff]+")
RUBY_BLOCK_REGEX = re.compile(r"<ruby\b[^>]*>.*?</ruby>", re.IGNORECASE | re.DOTALL)
PLACEHOLDER_PREFIX = "__TOFURI_RUBY_BLOCK_"


@dataclass
class TokenInfo:
    surface: str
    reading_hira: Optional[str]
    pos: Optional[str]


class TofuriEngine:
    def __init__(self) -> None:
        self.tagger = fugashi.Tagger()

    def tokenize(self, text: str) -> List[TokenInfo]:
        tokens: List[TokenInfo] = []
        for word in self.tagger(text):
            feature = getattr(word, "feature", None)
            kana = getattr(feature, "kana", None) if feature else None
            pos1 = getattr(feature, "pos1", None) if feature else None
            reading_hira = jaconv.kata2hira(kana) if kana else None
            tokens.append(TokenInfo(surface=word.surface, reading_hira=reading_hira, pos=pos1))
        return tokens

    def split_kanji(self, surface: str, reading_hira: str) -> str:
        if not reading_hira:
            return surface

        remaining = reading_hira
        parts: List[str] = []
        cursor = 0

        for match in KANJI_REGEX.finditer(surface):
            start, end = match.span()
            if start > cursor:
                parts.append(surface[cursor:start])

            kanji_block = surface[start:end]
            if len(surface) == 0:
                ruby = remaining
            else:
                proportion = max(1, int(len(reading_hira) * len(kanji_block) / len(surface)))
                ruby = remaining[:proportion] if len(remaining) >= proportion else remaining
                remaining = remaining[proportion:] if len(remaining) >= proportion else ""
            parts.append(f"<ruby>{kanji_block}<rt>{ruby}</rt></ruby>")
            cursor = end

        if cursor < len(surface):
            parts.append(surface[cursor:])
        return "".join(parts)

    def token_to_ruby(self, token: TokenInfo) -> str:
        surface = token.surface
        reading_hira = token.reading_hira
        if reading_hira and any("\u4e00" <= ch <= "\u9fff" for ch in surface):
            return self.split_kanji(surface, reading_hira)
        return surface


def protect_existing_ruby(text: str) -> (str, List[str]):
    saved_blocks: List[str] = []

    def replace(match: re.Match) -> str:
        saved_blocks.append(match.group(0))
        idx = len(saved_blocks) - 1
        return f"{PLACEHOLDER_PREFIX}{idx}__"

    protected = RUBY_BLOCK_REGEX.sub(replace, text)
    return protected, saved_blocks


def restore_existing_ruby(text: str, saved_blocks: List[str]) -> str:
    restored = text
    for idx, block in enumerate(saved_blocks):
        restored = restored.replace(f"{PLACEHOLDER_PREFIX}{idx}__", block)
    return restored


def render_furigana(engine: TofuriEngine, text: str, dedupe_ruby: bool = True) -> str:
    saved_blocks: List[str] = []
    working = text
    if dedupe_ruby:
        working, saved_blocks = protect_existing_ruby(working)

    rendered_lines: List[str] = []
    for line in working.split("\n"):
        rendered_lines.append("".join(engine.token_to_ruby(token) for token in engine.tokenize(line)))
    rendered = "\n".join(rendered_lines)

    if dedupe_ruby:
        rendered = restore_existing_ruby(rendered, saved_blocks)
    return rendered


def render_segment(engine: TofuriEngine, text: str, json_mode: bool = False) -> str:
    tokens = engine.tokenize(text)
    if json_mode:
        payload = [
            {
                "surface": t.surface,
                "reading": t.reading_hira,
                "pos": t.pos,
            }
            for t in tokens
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)
    segmented_lines: List[str] = []
    for line in text.split("\n"):
        line_tokens = engine.tokenize(line)
        segmented_lines.append(" ".join(t.surface for t in line_tokens))
    return "\n".join(segmented_lines)


def render_annotate(engine: TofuriEngine, text: str, json_mode: bool = False) -> str:
    tokens = engine.tokenize(text)
    if json_mode:
        payload = [
            {
                "surface": t.surface,
                "reading": t.reading_hira,
                "pos": t.pos,
                "ruby": engine.token_to_ruby(t),
            }
            for t in tokens
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)
    annotated_lines: List[str] = []
    for line in text.split("\n"):
        line_tokens = engine.tokenize(line)
        annotated_lines.append(" ".join(engine.token_to_ruby(t) for t in line_tokens))
    return "\n".join(annotated_lines)


def lookup_jisho(word: str) -> Optional[Dict[str, str]]:
    if not requests:
        return None
    try:
        response = requests.get("https://jisho.org/api/v1/search/words", params={"keyword": word}, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            return None

        item = data[0]
        japanese = item.get("japanese", [{}])[0]
        senses = item.get("senses", [{}])[0]
        defs = senses.get("english_definitions", [])

        return {
            "word": japanese.get("word") or word,
            "reading": japanese.get("reading"),
            "definition": "; ".join(defs[:5]) if defs else None,
            "source": "jisho",
        }
    except Exception:
        return None


def render_lookup(engine: TofuriEngine, text: str, source: str = "auto", json_mode: bool = False) -> str:
    tokens = [t for t in engine.tokenize(text) if t.surface.strip()]
    word_counter = Counter(t.surface for t in tokens if t.surface.strip())
    unique_tokens = sorted(word_counter.keys(), key=lambda w: (-word_counter[w], w))

    rows = []
    token_index = {t.surface: t for t in tokens}

    for word in unique_tokens:
        row = {
            "word": word,
            "count": word_counter[word],
            "reading": token_index[word].reading_hira,
            "pos": token_index[word].pos,
            "definition": None,
            "source": "tokenizer",
        }

        if source in ("auto", "jisho"):
            jisho_hit = lookup_jisho(word)
            if jisho_hit:
                row["reading"] = jisho_hit.get("reading") or row["reading"]
                row["definition"] = jisho_hit.get("definition")
                row["source"] = jisho_hit.get("source")

        rows.append(row)

    if json_mode:
        return json.dumps(rows, ensure_ascii=False, indent=2)

    header = "word\tcount\treading\tpos\tdefinition\tsource"
    lines = [header]
    for row in rows:
        lines.append(
            f"{row['word']}\t{row['count']}\t{row['reading'] or ''}\t{row['pos'] or ''}\t{row['definition'] or ''}\t{row['source']}"
        )
    return "\n".join(lines)


def build_translation_prompt(text: str, target_lang: str, style: str) -> str:
    language = "English" if target_lang.lower() == "en" else "Vietnamese"
    if style == "cure-dolly":
        return (
            "You are a Japanese grammar explainer following Cure Dolly style.\n"
            "For each sentence, produce:\n"
            "1) segmented Japanese\n"
            "2) literal scaffold translation preserving Japanese structure\n"
            "3) natural translation in the target language\n"
            "4) short grammar notes focusing on subject marking, particles, and predicate engine\n"
            f"Target language: {language}.\n"
            "Input:\n"
            f"{text}"
        )
    return (
        f"Translate the following Japanese text to {language}."
        " Keep sentence-by-sentence alignment.\n"
        "Input:\n"
        f"{text}"
    )


def render_translate(text: str, target_lang: str, style: str, model: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI")
    if not api_key:
        raise RuntimeError("Missing API key. Set OPENAI_API_KEY (or OPENAI) in your environment.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is not installed. Run: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    prompt = build_translation_prompt(text=text, target_lang=target_lang, style=style)

    completion = client.responses.create(
        model=model,
        input=prompt,
    )

    return completion.output_text.strip()


def sanitize_text(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def read_input_text(input_file: Optional[str]) -> str:
    if input_file:
        if not os.path.exists(input_file):
            raise RuntimeError(f"Input file not found: {input_file}")
        with open(input_file, "r", encoding="utf-8") as f:
            return sanitize_text(f.read())

    if sys.stdin.isatty():
        print("Paste Japanese text. Press Ctrl+Z then Enter to submit on Windows.", file=sys.stderr)

    return sanitize_text(sys.stdin.read())


def write_output(content: str, output_file: Optional[str]) -> None:
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        return

    print(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tofuri Japanese CLI tool")
    parser.add_argument("mode", nargs="?", choices=["segment", "furigana", "annotate", "lookup", "translate"])
    parser.add_argument("--input", "-i", dest="input_file", help="Input file path. If omitted, reads stdin.")
    parser.add_argument("--output", "-o", dest="output_file", help="Output file path. If omitted, prints stdout.")
    parser.add_argument("--json", action="store_true", help="Use JSON output when available.")
    parser.add_argument(
        "--dict-source",
        choices=["auto", "jisho", "none"],
        default="auto",
        help="Dictionary source for lookup mode.",
    )
    parser.add_argument("--language", choices=["en", "vi"], default="en", help="Target language for translate mode.")
    parser.add_argument("--style", choices=["standard", "cure-dolly"], default="cure-dolly", help="Translation style.")
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI model name for translate mode.")
    parser.add_argument(
        "--no-dedupe-ruby",
        action="store_true",
        help="Do not preserve existing <ruby> blocks when generating furigana.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive numbered-menu mode.",
    )
    return parser


def prompt_choice(title: str, options: List[str]) -> int:
    while True:
        print(f"\n{title}")
        for idx, option in enumerate(options, 1):
            print(f"{idx}. {option}")

        raw = input("Enter option number: ").strip()
        if raw.isdigit():
            value = int(raw)
            if 1 <= value <= len(options):
                return value
        print("Invalid choice. Please enter a valid number.")


def prompt_yes_no(question: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        raw = input(f"{question} {suffix}: ").strip().lower()
        if not raw:
            return default_yes
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Please answer y or n.")


def read_multiline_interactive() -> str:
    print("\nPaste Japanese text below.")
    print("Type __END__ on a new line to finish input.\n")
    lines: List[str] = []
    while True:
        line = input()
        if line == "__END__":
            break
        lines.append(line)
    return sanitize_text("\n".join(lines))


def build_interactive_args() -> SimpleNamespace:
    mode_index = prompt_choice(
        "Choose mode:",
        [
            "Segmentation",
            "Furigana (HTML ruby)",
            "Segmentation + Furigana",
            "Dictionary lookup",
            "Translation (AI)",
        ],
    )
    mode_map = {
        1: "segment",
        2: "furigana",
        3: "annotate",
        4: "lookup",
        5: "translate",
    }
    mode = mode_map[mode_index]

    input_method = prompt_choice("Input source:", ["Paste multiline text", "Read from file path"])
    input_file = None
    interactive_text = None
    if input_method == 1:
        interactive_text = read_multiline_interactive()
        output_prompt = "Output file path (leave blank for stdout): "
        output_file = input(output_prompt).strip() or None
    else:
        input_file = input("Enter input file path (default: input.txt): ").strip() or "input.txt"
        output_file = input("Output file path (default: output.txt): ").strip() or "output.txt"

    json_mode = False
    if mode in ("segment", "annotate", "lookup"):
        json_mode = prompt_yes_no("Use JSON output? (default: no)", default_yes=False)

    dict_source = "auto"
    if mode == "lookup":
        dict_idx = prompt_choice("Dictionary source:", ["Auto", "Jisho", "None"])
        dict_source = {1: "auto", 2: "jisho", 3: "none"}[dict_idx]

    language = "en"
    style = "cure-dolly"
    model = "gpt-4.1-mini"
    if mode == "translate":
        lang_idx = prompt_choice("Target language:", ["English", "Vietnamese"])
        language = {1: "en", 2: "vi"}[lang_idx]
        style_idx = prompt_choice("Translation style:", ["Cure Dolly", "Standard"])
        style = {1: "cure-dolly", 2: "standard"}[style_idx]
        chosen_model = input("Model name (leave blank for gpt-4.1-mini): ").strip()
        if chosen_model:
            model = chosen_model

    no_dedupe_ruby = False
    if mode == "furigana":
        preserve = prompt_yes_no("Preserve existing <ruby> tags?", default_yes=True)
        no_dedupe_ruby = not preserve

    return SimpleNamespace(
        mode=mode,
        input_file=input_file,
        output_file=output_file,
        json=json_mode,
        dict_source=dict_source,
        language=language,
        style=style,
        model=model,
        no_dedupe_ruby=no_dedupe_ruby,
        interactive_text=interactive_text,
    )


def execute_mode(engine: TofuriEngine, args: SimpleNamespace, text: str) -> str:
    if args.mode == "segment":
        return render_segment(engine, text, json_mode=args.json)
    if args.mode == "furigana":
        return render_furigana(engine, text, dedupe_ruby=not args.no_dedupe_ruby)
    if args.mode == "annotate":
        return render_annotate(engine, text, json_mode=args.json)
    if args.mode == "lookup":
        return render_lookup(engine, text, source=args.dict_source, json_mode=args.json)
    return render_translate(text=text, target_lang=args.language, style=args.style, model=args.model)


def main() -> int:
    parser = build_parser()
    parsed = parser.parse_args()

    try:
        if parsed.interactive or not parsed.mode:
            args = build_interactive_args()
            text = args.interactive_text if args.interactive_text is not None else read_input_text(args.input_file)
        else:
            args = SimpleNamespace(**vars(parsed))
            text = read_input_text(args.input_file)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not text.strip():
        print("Error: no input text provided.", file=sys.stderr)
        return 2

    engine = TofuriEngine()

    try:
        output = execute_mode(engine, args, text)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    write_output(output, args.output_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())