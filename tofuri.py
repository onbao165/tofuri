import argparse
import gzip
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import textwrap
import zipfile
import xml.etree.ElementTree as ET
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
DICT_DIR_DEFAULT = "dictionaries"
LOCAL_DICT_EN_DEFAULT_PATH = os.path.join(DICT_DIR_DEFAULT, "jmdict_en.tsv")
LOCAL_DICT_VI_DEFAULT_PATH = os.path.join(DICT_DIR_DEFAULT, "jmdict_vi.tsv")
JMDICT_GZ_URL = "http://ftp.edrdg.org/pub/Nihongo/JMdict.gz"
JS_DICT_VI_ZIP_URL = "https://raw.githubusercontent.com/philongrobo/jsdict/main/assets/databases/nhat_viet.db.zip"


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

        def is_kana_char(ch: str) -> bool:
            return ("\u3040" <= ch <= "\u309f") or ("\u30a0" <= ch <= "\u30ff")

        def to_hira(text: str) -> str:
            return jaconv.kata2hira(text)

        segments: List[tuple[str, str]] = []
        cursor = 0
        for match in KANJI_REGEX.finditer(surface):
            start, end = match.span()
            if start > cursor:
                segments.append(("other", surface[cursor:start]))
            segments.append(("kanji", match.group(0)))
            cursor = end
        if cursor < len(surface):
            segments.append(("other", surface[cursor:]))

        def next_kana_anchor(from_index: int) -> str:
            for next_idx in range(from_index + 1, len(segments)):
                kind, segment_text = segments[next_idx]
                if kind != "other":
                    continue
                kana_chars = [to_hira(ch) for ch in segment_text if is_kana_char(ch)]
                if kana_chars:
                    return "".join(kana_chars)
            return ""

        rendered: List[str] = []
        read_cursor = 0

        for idx, (kind, segment_text) in enumerate(segments):
            if kind == "other":
                rendered.append(segment_text)
                for ch in segment_text:
                    if not is_kana_char(ch):
                        continue
                    hira = to_hira(ch)
                    if read_cursor < len(reading_hira) and reading_hira[read_cursor] == hira:
                        read_cursor += 1
                        continue
                    found = reading_hira.find(hira, read_cursor)
                    if found != -1:
                        read_cursor = found + 1
                continue

            anchor = next_kana_anchor(idx)
            anchor_pos = reading_hira.find(anchor, read_cursor) if anchor else -1

            if anchor_pos > read_cursor:
                ruby = reading_hira[read_cursor:anchor_pos]
                read_cursor = anchor_pos
            else:
                remaining_kanji_blocks = sum(1 for k, _ in segments[idx:] if k == "kanji")
                remaining_reading = len(reading_hira) - read_cursor
                if remaining_kanji_blocks <= 1:
                    ruby = reading_hira[read_cursor:]
                    read_cursor = len(reading_hira)
                else:
                    take = max(1, remaining_reading - (remaining_kanji_blocks - 1))
                    ruby = reading_hira[read_cursor : read_cursor + take]
                    read_cursor += take

            rendered.append(f"<ruby>{segment_text}<rt>{ruby}</rt></ruby>")

        return "".join(rendered)

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


def download_file(url: str, destination_path: str) -> None:
    if not requests:
        raise RuntimeError("requests package is required for dictionary download. Run: pip install requests")
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    with open(destination_path, "wb") as f:
        f.write(response.content)


def extract_entries_from_jmdict(xml_content: bytes, lang: str) -> List[Dict[str, str]]:
    root = ET.fromstring(xml_content)
    entries: List[Dict[str, str]] = []

    lang_map = {"en": "eng", "vi": "vie"}
    target_lang = lang_map.get(lang, "eng")
    xml_lang_key = "{http://www.w3.org/XML/1998/namespace}lang"

    for entry in root.findall("entry"):
        keb_elems = entry.findall("k_ele/keb")
        reb_elems = entry.findall("r_ele/reb")
        if not reb_elems:
            continue

        words = [e.text for e in keb_elems if e.text] or [e.text for e in reb_elems if e.text]
        readings = [e.text for e in reb_elems if e.text]
        if not words or not readings:
            continue

        glosses: List[str] = []
        for sense in entry.findall("sense"):
            for gloss in sense.findall("gloss"):
                gloss_lang = gloss.attrib.get(xml_lang_key, "eng")
                if target_lang == "eng":
                    if gloss_lang in ("eng", "") and gloss.text:
                        glosses.append(gloss.text.strip())
                elif gloss_lang == target_lang and gloss.text:
                    glosses.append(gloss.text.strip())

        if not glosses:
            continue

        definition = "; ".join(dict.fromkeys(glosses[:8]))
        reading_hira = jaconv.kata2hira(readings[0])
        for word in words:
            entries.append(
                {
                    "word": word,
                    "reading": reading_hira,
                    "definition": definition,
                }
            )

    return entries


def write_tsv_dictionary(path: str, rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# word\treading_hiragana\tdefinition\n")
        for row in rows:
            word = row["word"].replace("\t", " ")
            reading = row["reading"].replace("\t", " ")
            definition = row["definition"].replace("\t", " ")
            f.write(f"{word}\t{reading}\t{definition}\n")


def extract_reading_from_vi_meaning(meaning: str) -> Optional[str]:
    match = re.search(r"「\s*([^」]+?)\s*」", meaning)
    if not match:
        return None
    reading = match.group(1).strip()
    reading = re.sub(r"\s+", "", reading)
    if not reading:
        return None
    if not re.fullmatch(r"[ぁ-んァ-ンー]+", reading):
        return None
    return jaconv.kata2hira(reading)


def clean_vi_definition(raw_meaning: str) -> str:
    text = raw_meaning.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Prefer concise gloss segments after "◆", and remove example blocks after "※".
    if "◆" in text:
        parts = [p.strip() for p in text.split("◆") if p.strip()]
        cleaned_parts: List[str] = []
        for p in parts:
            # Drop metadata chunk (often before the first gloss bullet).
            if "∴" in p and "」" in p and ("☆" in p or "VI" in p):
                continue
            p = p.split("※", 1)[0].strip()
            p = re.sub(r"^∴「.*?」\s*", "", p)
            p = re.sub(r"☆\s*[^◆]*", "", p)
            p = p.strip(" .;:")
            if p:
                cleaned_parts.append(p)
        if cleaned_parts:
            normalized = [re.sub(r"\s+", " ", v).strip() for v in cleaned_parts]
            return "; ".join(list(dict.fromkeys(normalized[:5])))

    text = text.split("※", 1)[0].strip()
    text = re.sub(r"^∴「.*?」\s*", "", text)
    return text.strip(" .")


def extract_vi_entries_from_jsdict_zip(zip_content: bytes) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    zf = zipfile.ZipFile(io.BytesIO(zip_content))
    db_names = [name for name in zf.namelist() if name.endswith(".db") or name.endswith(".db.db")]
    if not db_names:
        return rows

    with tempfile.TemporaryDirectory(prefix="tofuri_vi_dict_") as tmp:
        db_path = os.path.join(tmp, db_names[0])
        with open(db_path, "wb") as f:
            f.write(zf.read(db_names[0]))

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            # Table `jv` stores Japanese word -> Vietnamese meaning.
            data = cur.execute("SELECT word, meaning FROM jv").fetchall()
        except sqlite3.Error:
            data = []
        finally:
            conn.close()

        for word, meaning in data:
            if not word or not meaning:
                continue
            clean_word = str(word).strip()
            raw_meaning = str(meaning)
            clean_definition = clean_vi_definition(raw_meaning)
            reading = extract_reading_from_vi_meaning(raw_meaning)
            if not clean_word or not clean_definition:
                continue
            rows.append(
                {
                    "word": clean_word,
                    "reading": reading or "",
                    "definition": clean_definition,
                }
            )

    return rows


def download_well_known_dictionaries(
    output_dir: str = DICT_DIR_DEFAULT,
    source_url: str = JMDICT_GZ_URL,
) -> Dict[str, int]:
    os.makedirs(output_dir, exist_ok=True)
    gz_path = os.path.join(output_dir, "JMdict.gz")

    download_file(source_url, gz_path)
    with gzip.open(gz_path, "rb") as f:
        xml_content = f.read()

    en_rows = extract_entries_from_jmdict(xml_content, "en")

    vi_zip_path = os.path.join(output_dir, "nhat_viet.db.zip")
    download_file(JS_DICT_VI_ZIP_URL, vi_zip_path)
    with open(vi_zip_path, "rb") as f:
        vi_rows = extract_vi_entries_from_jsdict_zip(f.read())

    write_tsv_dictionary(os.path.join(output_dir, "jmdict_en.tsv"), en_rows)
    write_tsv_dictionary(os.path.join(output_dir, "jmdict_vi.tsv"), vi_rows)

    # Keep only final TSV dictionaries, remove temporary source archives.
    for artifact in (gz_path, vi_zip_path):
        try:
            if os.path.exists(artifact):
                os.remove(artifact)
        except OSError:
            pass

    return {"en_entries": len(en_rows), "vi_entries": len(vi_rows)}


def load_local_dictionary(path: str, lang: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    if not os.path.exists(path):
        return entries

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split("\t")]
            if len(parts) < 3:
                continue

            entries.append(
                {
                    "word": parts[0],
                    "reading": jaconv.kata2hira(parts[1]),
                    "definition": parts[2],
                    "source": "local",
                    "lang": lang,
                }
            )
    return entries


def lookup_local(word: str, reading_hira: Optional[str], entries: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    exact_word = [entry for entry in entries if entry["word"] == word]
    if exact_word:
        if reading_hira:
            reading_match = [entry for entry in exact_word if entry.get("reading") == reading_hira]
            if reading_match:
                return reading_match[0]
        return exact_word[0]
    return None


def lookup_local_multilang(
    word: str,
    reading_hira: Optional[str],
    en_entries: List[Dict[str, str]],
    vi_entries: List[Dict[str, str]],
    dict_lang: str,
) -> Dict[str, Optional[Dict[str, str]]]:
    result = {"en": None, "vi": None}
    if dict_lang in ("en", "both"):
        result["en"] = lookup_local(word, reading_hira, en_entries)
    if dict_lang in ("vi", "both"):
        result["vi"] = lookup_local(word, reading_hira, vi_entries)
    return result


def render_lookup(
    engine: TofuriEngine,
    text: str,
    source: str = "auto",
    json_mode: bool = False,
    lookup_format: str = "text",
    definition_wrap: int = 0,
    local_dict_en_path: str = LOCAL_DICT_EN_DEFAULT_PATH,
    local_dict_vi_path: str = LOCAL_DICT_VI_DEFAULT_PATH,
    dict_lang: str = "both",
) -> str:
    vi_skip_pos = {"助詞", "助動詞", "補助記号", "接頭辞", "接尾辞"}

    tokens = [t for t in engine.tokenize(text) if t.surface.strip()]
    word_counter = Counter(t.surface for t in tokens if t.surface.strip())
    unique_tokens = sorted(word_counter.keys(), key=lambda w: (-word_counter[w], w))

    local_entries_en: List[Dict[str, str]] = []
    local_entries_vi: List[Dict[str, str]] = []
    if source in ("auto", "local"):
        if dict_lang in ("en", "both"):
            local_entries_en = load_local_dictionary(local_dict_en_path, "en")
        if dict_lang in ("vi", "both"):
            local_entries_vi = load_local_dictionary(local_dict_vi_path, "vi")

        if source == "local":
            if dict_lang == "en" and not local_entries_en:
                raise RuntimeError(f"English local dictionary not found or empty: {local_dict_en_path}")
            if dict_lang == "vi" and not local_entries_vi:
                raise RuntimeError(f"Vietnamese local dictionary not found or empty: {local_dict_vi_path}")
            if dict_lang == "both" and not local_entries_en and not local_entries_vi:
                raise RuntimeError(
                    "Both local dictionaries missing or empty: "
                    f"{local_dict_en_path}, {local_dict_vi_path}"
                )

    rows = []
    token_index = {t.surface: t for t in tokens}

    for word in unique_tokens:
        row = {
            "word": word,
            "count": word_counter[word],
            "reading": token_index[word].reading_hira,
            "pos": token_index[word].pos,
            "definition": None,
            "definition_en": None,
            "definition_vi": None,
            "source": "tokenizer",
        }

        local_hit_any = False
        if source in ("auto", "local"):
            vi_candidates = local_entries_vi
            if row["pos"] in vi_skip_pos:
                vi_candidates = []

            local_hits = lookup_local_multilang(
                word,
                row["reading"],
                local_entries_en,
                vi_candidates,
                dict_lang,
            )
            en_hit = local_hits["en"]
            vi_hit = local_hits["vi"]

            if en_hit:
                row["definition_en"] = en_hit.get("definition")
                if en_hit.get("reading") and en_hit.get("reading") != "*":
                    row["reading"] = en_hit.get("reading")
                local_hit_any = True
            if vi_hit:
                row["definition_vi"] = vi_hit.get("definition")
                if vi_hit.get("reading") and vi_hit.get("reading") != "*":
                    row["reading"] = vi_hit.get("reading")
                local_hit_any = True

            if local_hit_any:
                if dict_lang == "en":
                    row["definition"] = row["definition_en"]
                elif dict_lang == "vi":
                    row["definition"] = row["definition_vi"]
                else:
                    joined = []
                    if row["definition_en"]:
                        joined.append(f"EN: {row['definition_en']}")
                    if row["definition_vi"]:
                        joined.append(f"VI: {row['definition_vi']}")
                    row["definition"] = " | ".join(joined) if joined else None
                row["source"] = "local"

        if source in ("auto", "jisho") and not local_hit_any:
            jisho_hit = lookup_jisho(word)
            if jisho_hit:
                row["reading"] = jisho_hit.get("reading") or row["reading"]
                row["definition"] = jisho_hit.get("definition")
                if dict_lang in ("en", "both"):
                    row["definition_en"] = jisho_hit.get("definition")
                row["source"] = jisho_hit.get("source")

        rows.append(row)

    if json_mode:
        return json.dumps(rows, ensure_ascii=False, indent=2)

    if lookup_format == "markdown":
        def wrap_definition_markdown(definition: Optional[str], width: int) -> str:
            if not definition:
                return ""
            if width <= 0:
                return str(definition)

            chunks = [chunk.strip() for chunk in str(definition).split(";") if chunk.strip()]
            if not chunks:
                return str(definition)

            lines: List[str] = []
            current = ""
            for chunk in chunks:
                candidate = chunk if not current else f"{current}; {chunk}"
                if len(candidate) <= width:
                    current = candidate
                    continue

                if current:
                    lines.append(current)
                    current = ""

                if len(chunk) <= width:
                    current = chunk
                    continue

                wrapped = textwrap.wrap(chunk, width=width, break_long_words=False, break_on_hyphens=False)
                if not wrapped:
                    continue
                lines.extend(wrapped[:-1])
                current = wrapped[-1]

            if current:
                lines.append(current)
            return "<br>".join(lines)

        def md_cell(value: Optional[str]) -> str:
            text_value = "" if value is None else str(value)
            text_value = text_value.replace("\n", " ").replace("\r", " ")
            return text_value.replace("|", "\\|")

        lines = [
            "| word | count | reading | pos | definition | source |",
            "|---|---|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(row.get("word")),
                        md_cell(row.get("count")),
                        md_cell(row.get("reading")),
                        md_cell(row.get("pos")),
                        md_cell(wrap_definition_markdown(row.get("definition"), definition_wrap)),
                        md_cell(row.get("source")),
                    ]
                )
                + " |"
            )
        return "\n".join(lines)

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
    content = content.rstrip("\n")

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        return

    sys.stdout.write(content)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tofuri Japanese CLI tool")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["segment", "furigana", "annotate", "lookup", "translate", "dict-download"],
    )
    parser.add_argument("--input", "-i", dest="input_file", help="Input file path. If omitted, reads stdin.")
    parser.add_argument("--output", "-o", dest="output_file", help="Output file path. If omitted, prints stdout.")
    parser.add_argument("--json", action="store_true", help="Use JSON output when available.")
    parser.add_argument(
        "--lookup-format",
        choices=["text", "markdown"],
        default="text",
        help="Output format for lookup mode when not using --json.",
    )
    parser.add_argument(
        "--definition-wrap",
        type=int,
        default=0,
        help="Wrap width for definition cell in markdown lookup output (0 disables wrapping).",
    )
    parser.add_argument(
        "--dict-source",
        choices=["auto", "local", "jisho", "none"],
        default="auto",
        help="Dictionary source for lookup mode.",
    )
    parser.add_argument(
        "--local-dict",
        default=LOCAL_DICT_EN_DEFAULT_PATH,
        help="Backward-compatible alias for English local TSV dictionary path.",
    )
    parser.add_argument(
        "--local-dict-en",
        default=LOCAL_DICT_EN_DEFAULT_PATH,
        help="Path to English local TSV dictionary (default: dictionaries/jmdict_en.tsv).",
    )
    parser.add_argument(
        "--local-dict-vi",
        default=LOCAL_DICT_VI_DEFAULT_PATH,
        help="Path to Vietnamese local TSV dictionary (default: dictionaries/jmdict_vi.tsv).",
    )
    parser.add_argument(
        "--dict-lang",
        choices=["en", "vi", "both"],
        default="both",
        help="Dictionary language preference in lookup mode.",
    )
    parser.add_argument(
        "--dict-dir",
        default=DICT_DIR_DEFAULT,
        help="Output directory used by dict-download mode.",
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
            "Download offline dictionaries",
        ],
    )
    mode_map = {
        1: "segment",
        2: "furigana",
        3: "annotate",
        4: "lookup",
        5: "translate",
        6: "dict-download",
    }
    mode = mode_map[mode_index]

    if mode == "dict-download":
        dict_dir = input(f"Dictionary output directory (default: {DICT_DIR_DEFAULT}): ").strip() or DICT_DIR_DEFAULT
        return SimpleNamespace(
            mode=mode,
            input_file=None,
            output_file=None,
            json=False,
            dict_source="local",
            dict_lang="both",
            lookup_format="text",
            definition_wrap=0,
            local_dict=LOCAL_DICT_EN_DEFAULT_PATH,
            local_dict_en=LOCAL_DICT_EN_DEFAULT_PATH,
            local_dict_vi=LOCAL_DICT_VI_DEFAULT_PATH,
            dict_dir=dict_dir,
            language="en",
            style="cure-dolly",
            model="gpt-4.1-mini",
            no_dedupe_ruby=False,
            interactive_text=None,
        )

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
    lookup_format = "text"
    definition_wrap = 0
    if mode in ("segment", "annotate", "lookup"):
        json_mode = prompt_yes_no("Use JSON output? (default: no)", default_yes=False)
    if mode == "lookup" and not json_mode:
        fmt_idx = prompt_choice("Lookup output format:", ["Text table", "Markdown table"])
        lookup_format = {1: "text", 2: "markdown"}[fmt_idx]
        if lookup_format == "markdown":
            wrap_raw = input("Definition wrap width for markdown (0 = no wrap, default: 120): ").strip()
            if wrap_raw:
                try:
                    definition_wrap = max(0, int(wrap_raw))
                except ValueError:
                    definition_wrap = 120

    dict_source = "auto"
    dict_lang = "both"
    local_dict = LOCAL_DICT_EN_DEFAULT_PATH
    local_dict_en = LOCAL_DICT_EN_DEFAULT_PATH
    local_dict_vi = LOCAL_DICT_VI_DEFAULT_PATH
    dict_dir = DICT_DIR_DEFAULT
    if mode == "lookup":
        dict_idx = prompt_choice("Dictionary source:", ["Auto", "Local", "Jisho (jisho.org)", "None"])
        dict_source = {1: "auto", 2: "local", 3: "jisho", 4: "none"}[dict_idx]
        lang_idx = prompt_choice("Dictionary language:", ["Both", "English", "Vietnamese"])
        dict_lang = {1: "both", 2: "en", 3: "vi"}[lang_idx]
        if dict_source in ("auto", "local"):
            if dict_lang in ("both", "en"):
                local_dict_en = input(
                    f"English dictionary path (default: {LOCAL_DICT_EN_DEFAULT_PATH}): "
                ).strip() or LOCAL_DICT_EN_DEFAULT_PATH
            if dict_lang in ("both", "vi"):
                local_dict_vi = input(
                    f"Vietnamese dictionary path (default: {LOCAL_DICT_VI_DEFAULT_PATH}): "
                ).strip() or LOCAL_DICT_VI_DEFAULT_PATH

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
        lookup_format=lookup_format,
        definition_wrap=definition_wrap,
        dict_source=dict_source,
        dict_lang=dict_lang,
        local_dict=local_dict,
        local_dict_en=local_dict_en,
        local_dict_vi=local_dict_vi,
        dict_dir=dict_dir,
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
        return render_lookup(
            engine,
            text,
            source=args.dict_source,
            json_mode=args.json,
            lookup_format=args.lookup_format,
            definition_wrap=args.definition_wrap,
            local_dict_en_path=args.local_dict_en,
            local_dict_vi_path=args.local_dict_vi,
            dict_lang=args.dict_lang,
        )
    return render_translate(text=text, target_lang=args.language, style=args.style, model=args.model)


def main() -> int:
    parser = build_parser()
    parsed = parser.parse_args()

    try:
        if parsed.interactive or not parsed.mode:
            args = build_interactive_args()
            if args.mode == "dict-download":
                text = "__DICT_DOWNLOAD__"
            else:
                text = args.interactive_text if args.interactive_text is not None else read_input_text(args.input_file)
        else:
            args = SimpleNamespace(**vars(parsed))
            if args.mode == "dict-download":
                text = "__DICT_DOWNLOAD__"
                # Backward compatibility: --local-dict acts as --local-dict-en.
                args.local_dict_en = args.local_dict_en or args.local_dict
                args.local_dict_vi = args.local_dict_vi
            else:
                # Backward compatibility: --local-dict acts as --local-dict-en.
                args.local_dict_en = args.local_dict_en or args.local_dict
                args.local_dict_vi = args.local_dict_vi
                text = read_input_text(args.input_file)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.mode == "dict-download":
        try:
            stats = download_well_known_dictionaries(output_dir=args.dict_dir)
            message = (
                "Downloaded dictionaries successfully.\n"
                f"English entries: {stats['en_entries']}\n"
                f"Vietnamese entries: {stats['vi_entries']}\n"
                f"Path EN: {os.path.join(args.dict_dir, 'jmdict_en.tsv')}\n"
                f"Path VI: {os.path.join(args.dict_dir, 'jmdict_vi.tsv')}"
            )
            write_output(message, args.output_file)
            return 0
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