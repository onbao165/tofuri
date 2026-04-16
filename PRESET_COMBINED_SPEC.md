# Combined Preset Mode Specification (Segmentation + Furigana + Vocabulary + Translation)

## Document Metadata
- **Version**: 1.0-draft
- **Date**: 2026-04-13
- **Status**: Specification draft for implementation planning
- **Author**: Tofuri Project
- **Related Specs**: PROJECT_SPEC.md, DEEPL_TRANSLATION_SPEC.md, TRANSLATION_AI_SPEC.md

---

## 1. Problem Statement

### 1.1 Current State
Tofuri currently supports individual modes (`segment`, `furigana`, `annotate`, `lookup`, `translate`) that each perform a single operation on Japanese input text. Users who want comprehensive Japanese text analysis must run multiple modes separately and manually combine the results.

### 1.2 User Need
Language learners and readers often want a **single unified output** that provides:
1. **Original text with furigana** (ruby tags for kanji readings)
2. **Vocabulary breakdown** (token segmentation + dictionary definitions)
3. **Translation** (AI or DeepL-powered translation with grammar notes)

This requires running 3+ separate commands and manually merging outputs, which is error-prone and time-consuming.

### 1.3 Goal
Introduce a new **preset mode** (`preset` or `combined`) that executes segmentation + furigana + vocabulary lookup + translation in a single pass and outputs a **unified Markdown document** using Obsidian-style callout blocks for organized, readable output.

---

## 2. Functional Requirements

### 2.1 Core Operations
The preset mode must execute the following operations in sequence:

| # | Operation | Mode Equivalent | Purpose |
|---|-----------|-----------------|---------|
| 1 | **Segmentation + Furigana** | `annotate` | Tokenize input and render HTML ruby tags for kanji readings |
| 2 | **Vocabulary Lookup** | `lookup` (compact format) | Extract unique tokens with dictionary definitions |
| 3 | **Translation** | `translate` | Generate AI/DeepL translation of input text |

### 2.2 Output Format Requirements

#### 2.2.1 Markdown Callout Structure
Output must use Obsidian-compatible markdown callout syntax:

```markdown
>[!note]- Breakdown
>### **Furigana**
><ruby>百<rt>ひゃく</rt></ruby> <ruby>五十<rt>ごじゅう</rt></ruby> ...
>
>### **Vocabulary**
>賞「しょう」 giải thưởng
>コンビニ「こんびに」 cửa hàng tiện lợi
>...
>
>### **Translation**
>Natural translation text here...
```

#### 2.2.2 Section Specifications

**Furigana Section:**
- Contains annotated text with `<ruby>` tags for kanji-bearing tokens
- Preserves original line breaks from input
- Non-kanji tokens pass through unchanged
- Existing ruby blocks preserved (configurable via `--no-dedupe-ruby`)
- Rendered as a single blockquote continuation with `>` prefix

**Vocabulary Section:**
- Uses compact vocab format: `word「reading」 definition`
- Preferred definition source order: `definition_vi` → `definition` → `definition_en`
- Sino-Vietnamese uppercase prefix included when available: `word「reading」SINO_VI - definition`
- Rows without definitions are omitted
- Sorted by **first appearance order** in input text (not frequency)
- Rendered as a single blockquote continuation with `>` prefix

**Translation Section:**
- For **OpenAI provider** (cure-dolly style):
  - Natural translation text
  - Optional grammar notes (collapsible or indented)
- For **OpenAI provider** (standard style):
  - Natural translation text only
- For **DeepL provider**:
  - Natural translation text (sentence-by-sentence if needed)
- Rendered as a single blockquote continuation with `>` prefix

### 2.3 Configuration Requirements

#### 2.3.1 Inherited Options
Preset mode must support all relevant options from constituent modes:

| Option | Source Mode | Default | Description |
|--------|-------------|---------|-------------|
| `--no-dedupe-ruby` | furigana | false | Disable ruby block preservation |
| `--dict-source` | lookup | auto | Dictionary source preference |
| `--dict-lang` | lookup | both | Definition language preference |
| `--local-dict-en` | lookup | dictionaries/jmdict_en.tsv | English TSV path |
| `--local-dict-vi` | lookup | dictionaries/jmdict_vi.tsv | Vietnamese TSV path |
| `--exclude-token` | lookup | [] | Token exclusion list |
| `--exclude-pos` | lookup | [] | POS exclusion list |
| `--lookup-config` | lookup | lookup.yml | Lookup config path |
| `--language` | translate | en | Translation target language |
| `--style` | translate | cure-dolly | Translation style |
| `--model` | translate | from translation.yml | OpenAI model override |
| `--provider` | translate | from translation.yml | Provider override |
| `--translate-output` | translate | json | Output format (DeepL-only: simple/span) |

#### 2.3.2 New Preset-Specific Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--preset-format` | `markdown` \| `json` | markdown | Output format for combined result |
| `--preset-sections` | comma-separated | `furigana,vocabulary,translation` | Which sections to include |
| `--callout-title` | string | `Show Breakdown` | Callout block title |
| `--vocab-min-length` | int | 1 | Minimum token surface length for vocab inclusion |
| `--vocab-exclude-pos` | comma-separated | (inherits from lookup.yml) | Additional POS exclusions for vocab |

### 2.4 Error Handling Requirements

- If **any operation fails**, the mode must:
  1. Log the error to stderr
  2. Include an error placeholder in the affected section (e.g., `>### **Translation**\n>[!error] Translation failed: <reason>`)
  3. Continue rendering remaining sections if possible
  4. Exit with code 1 if critical failure (furigana/segmentation), code 0 if non-critical (translation/vocab fallback)

- If **translation config is missing** but user requests translation section:
  - Fail fast with clear message: `Error: translate section requires valid translation.yml`

- If **dictionaries are missing** but user requests vocab section:
  - With `--dict-source auto`: silently omit undefined words from vocab
  - With `--dict-source local`: fail fast with missing dictionary path

---

## 3. Proposed Solution

### 3.1 Architecture

```
┌─────────────────────────────────────────────┐
│              Preset Mode Entry               │
└─────────────────┬───────────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
┌────────┐  ┌──────────┐  ┌────────────┐
│Furigana│  │Vocabulary│  │Translation │
│Render  │  │Lookup    │  │Engine      │
└────┬───┘  └────┬─────┘  └─────┬──────┘
     │           │              │
     └───────────┼──────────────┘
                 ▼
    ┌────────────────────────┐
    │  Markdown Callout      │
    │  Assembly & Formatting │
    └────────────┬───────────┘
                 ▼
    ┌────────────────────────┐
    │     Output Writer      │
    └────────────────────────┘
```

### 3.2 Implementation Plan

#### 3.2.1 New Function: `render_preset_combined()`

```python
def render_preset_combined(
    engine: TofuriEngine,
    text: str,
    # Furigana options
    dedupe_ruby: bool = True,
    # Vocabulary options
    dict_source: str = "auto",
    dict_lang: str = "both",
    local_dict_en_path: str = LOCAL_DICT_EN_DEFAULT_PATH,
    local_dict_vi_path: str = LOCAL_DICT_VI_DEFAULT_PATH,
    exclude_tokens: Optional[List[str]] = None,
    exclude_pos: Optional[List[str]] = None,
    lookup_config_path: Optional[str] = "lookup.yml",
    vocab_min_length: int = 1,
    # Translation options
    translate_language: str = "en",
    translate_style: str = "cure-dolly",
    translate_model: Optional[str] = None,
    translate_provider: Optional[str] = None,
    translate_output_format: str = "json",
    # Output formatting
    callout_title: str = "Show Breakdown",
    sections: List[str] = None,
) -> str:
```

#### 3.2.2 Processing Pipeline

**Step 1: Furigana Generation**
```python
furigana_text = render_furigana(engine, text, dedupe_ruby=dedupe_ruby)
```

**Step 2: Vocabulary Lookup**
```python
# Use render_lookup with compact format, then parse result
vocab_raw = render_lookup(
    engine, text,
    source=dict_source,
    lookup_format="compact",
    local_dict_en_path=local_dict_en_path,
    local_dict_vi_path=local_dict_vi_path,
    dict_lang=dict_lang,
    exclude_tokens=exclude_tokens,
    exclude_pos=exclude_pos,
    lookup_config_path=lookup_config_path,
)
# Filter by min length if needed
vocab_lines = [
    line for line in vocab_raw.split("\n")
    if len(line.split("「")[0]) >= vocab_min_length
]
vocab_text = "\n".join(vocab_lines)
```

**Step 3: Translation**
```python
# Only if translation section requested
translation_json = render_translate(
    text, translate_language, translate_style,
    translate_model, translate_provider, translate_output_format
)
translation_data = json.loads(translation_json)
# Extract natural translation from response
natural_text = extract_natural_translation(translation_data, translate_provider)
```

**Step 4: Markdown Assembly**
```python
def assemble_callout(
    furigana: str,
    vocab: str,
    translation: str,
    sections: List[str],
    callout_title: str,
) -> str:
    lines = [f">[!note]- {callout_title}"]
    
    if "furigana" in sections:
        lines.append(">### **Furigana**")
        for line in furigana.split("\n"):
            lines.append(f">{line}" if line else ">")
        lines.append(">")  # Separator
    
    if "vocabulary" in sections:
        lines.append(">### **Vocabulary**")
        for line in vocab.split("\n"):
            lines.append(f">{line}" if line else ">")
        lines.append(">")  # Separator
    
    if "translation" in sections:
        lines.append(">### **Translation**")
        for line in translation.split("\n"):
            lines.append(f">{line}" if line else ">")
    
    return "\n".join(lines)
```

#### 3.2.3 Helper: Extract Natural Translation

```python
def extract_natural_translation(
    translation_data: Dict,
    provider: str
) -> str:
    """Extract natural translation text from standardized response."""
    if provider == "deepl":
        # DeepL uses translations[] array
        translations = translation_data.get("translations", [])
        return " ".join(
            item.get("natural", "")
            for item in translations
            if item.get("natural")
        )
    else:
        # OpenAI uses sentences[] array
        sentences = translation_data.get("sentences", [])
        return " ".join(
            sentence.get("natural", "")
            for sentence in sentences
            if sentence.get("natural")
        )
```

### 3.3 CLI Integration

#### 3.3.1 Mode Registration
Add `preset` to the mode choices in `build_parser()`:

```python
parser.add_argument(
    "mode",
    nargs="?",
    choices=[
        "segment", "furigana", "annotate", 
        "lookup", "translate", "dict-download",
        "preset"  # NEW
    ],
)
```

#### 3.3.2 New Arguments

```python
# Preset-specific options
parser.add_argument(
    "--preset-format",
    choices=["markdown", "json"],
    default="markdown",
    help="Output format for preset mode.",
)
parser.add_argument(
    "--preset-sections",
    default="furigana,vocabulary,translation",
    help="Comma-separated list of sections to include (default: all).",
)
parser.add_argument(
    "--callout-title",
    default="Show Breakdown",
    help="Title for the markdown callout block.",
)
parser.add_argument(
    "--vocab-min-length",
    type=int,
    default=1,
    help="Minimum token surface length for vocabulary inclusion.",
)
```

### 3.4 JSON Output Mode

When `--preset-format json` is specified, output should be:

```json
{
  "furigana": "<annotated text with ruby tags>",
  "vocabulary": [
    {
      "word": "賞",
      "reading": "しょう",
      "definition": "giải thưởng"
    }
  ],
  "translation": {
    "natural": "Natural translation text...",
    "provider": "deepl",
    "language": "en"
  }
}
```

---

## 4. Testing Plan

### 4.1 Unit Tests

| Test Category | Test Cases | Expected Outcome |
|---------------|------------|------------------|
| **Furigana Rendering** | Single kanji, multi-kanji compound, existing ruby blocks, katakana-only text | Correct ruby tag placement, no nested ruby |
| **Vocabulary Lookup** | Local dict hit, Jisho fallback, no definition, Sino-Vietnamese prefix | Correct compact format, proper source priority |
| **Translation Extraction** | OpenAI success, DeepL success, rejection payload, error response | Correct natural text extraction |
| **Markdown Assembly** | All sections, partial sections, empty sections | Valid callout syntax, correct `>` prefixing |
| **JSON Output** | All sections, malformed data | Valid JSON structure |

### 4.2 Integration Tests

| Test Scenario | Setup | Validation |
|---------------|-------|------------|
| **Full pipeline** | Japanese text input → preset mode | All 3 sections populated, valid markdown |
| **Missing translation.yml** | No config file → preset with translation section | Graceful error in translation section |
| **Missing dictionaries** | Empty dict files → preset with vocab section | Vocab rows without definitions omitted |
| **DeepL provider** | `--provider deepl --language en` | Translation-only output, no dissection |
| **OpenAI cure-dolly** | `--provider openai --style cure-dolly` | Natural + grammar notes extraction |

### 4.3 Regression Tests

- Existing `test_furigana_regression.py` must remain green
- Existing `test_translation_contract.py` must remain green
- New test file: `tests/test_preset_combined.py`

### 4.4 Edge Cases

| Case | Handling |
|------|----------|
| Empty input text | Exit code 2 (standard behavior) |
| Single-character tokens | Included in vocab if `--vocab-min-length` allows |
| Multi-line input with blank lines | Preserved in furigana section |
| Mixed Japanese/English text | Furigana on kanji only, English passes through |
| Translation API timeout | Error placeholder in translation section |
| Duplicate tokens in input | Vocab shows unique tokens only (first appearance order) |

---

## 5. Implementation Checklist

- [ ] **Phase 1: Core Functions**
  - [ ] Implement `render_preset_combined()` in `tofuri.py`
  - [ ] Implement `extract_natural_translation()` helper
  - [ ] Implement `assemble_callout()` formatter
  - [ ] Add JSON output path for `--preset-format json`

- [ ] **Phase 2: CLI Integration**
  - [ ] Add `preset` to mode choices
  - [ ] Add preset-specific CLI arguments
  - [ ] Update `execute_mode()` to route to preset handler
  - [ ] Update interactive mode to include preset option

- [ ] **Phase 3: Testing**
  - [ ] Write `tests/test_preset_combined.py`
  - [ ] Add unit tests for furigana/vocab/translation extraction
  - [ ] Add integration tests for full pipeline
  - [ ] Run existing regression tests

- [ ] **Phase 4: Documentation**
  - [ ] Update `README.md` with preset mode usage examples
  - [ ] Update `PROJECT_SPEC.md` section 5.1 and 6
  - [ ] Add example output to spec document
  - [ ] Update `lookup.yml.example` if needed

- [ ] **Phase 5: Validation**
  - [ ] Test with real Japanese text (news article, novel excerpt)
  - [ ] Verify Obsidian rendering compatibility
  - [ ] Test all CLI option combinations
  - [ ] Verify error handling paths

---

## 6. Example Output

### 6.1 Input
```
第百五十五回芥川賞受賞作

コンビニ人間

村田 沙耶香

コンビニエンスストアは、音で満ちている。
```

### 6.2 Output (Markdown Callout)

```markdown
>[!note]- Show Breakdown
>### **Furigana**
><ruby>百<rt>ひゃく</rt></ruby> <ruby>五十<rt>ごじゅう</rt></ruby> <ruby>五<rt>ご</rt></ruby> <ruby>回<rt>かい</rt></ruby> <ruby>芥川<rt>あくたがわ</rt></ruby> <ruby>賞<rt>しょう</rt></ruby> <ruby>受賞<rt>じゅしょう</rt></ruby> <ruby>作<rt>さく</rt></ruby>
>
>コンビニ <ruby>人間<rt>にんげん</rt></ruby>
>
><ruby>村田<rt>むらた</rt></ruby> <ruby>沙耶香<rt>さやか</rt></ruby>
>
>コンビニエンス ストア は 、 <ruby>音<rt>おと</rt></ruby> で <ruby>満<rt>み</rt></ruby>ち て いる 。
>
>### **Vocabulary**
>賞「しょう」 giải thưởng
>コンビニ「こんびに」 cửa hàng tiện lợi
>人間「にんげん」 nhân gian; nhân loại; con người
>コンビニエンスストア cửa hàng tiện lợi (CONVENIENCE STORE)
>音「おと」 âm thanh; tiếng động
>満ちる 「みちる」đầy tràn, trưởng thành
>
>### **Translation**
>The 155th Akutagawa Prize-winning work
>
>Convenience Store Human
>
>by Sayaka Murata
>
>The convenience store is full of sounds.
```

---

## 7. Migration & Backward Compatibility

### 7.1 No Breaking Changes
- Existing modes (`segment`, `furigana`, `annotate`, `lookup`, `translate`) remain unchanged
- Existing CLI options retain current behavior
- `preset` mode is purely additive

### 7.2 Future Enhancements (Out of Scope for v1)
- Custom callout styling (color, icon)
- Section reordering via CLI
- Audio pronunciation links for vocab
- Anki card export preset
- PDF/HTML export formats

---

## 8. Change Management

When implementation is complete:
1. Update `PROJECT_SPEC.md`:
   - Section 5.1: Add `preset` to mode list
   - Section 5.3: Add preset-specific options
   - Section 6: Add new 6.7 Preset Mode subsection
2. Update `README.md` with usage examples
3. Add `tests/test_preset_combined.py`
4. Mark this spec as "Implemented" with date

---

## 9. Acceptance Criteria

The preset mode is considered complete when:
- ✅ All 3 operations (furigana, vocab, translation) execute in single command
- ✅ Output matches example callout format exactly
- ✅ Works with both OpenAI and DeepL providers
- ✅ Handles missing dictionaries gracefully (vocab section degrades)
- ✅ Handles missing translation config gracefully (error in translation section)
- ✅ JSON output mode produces valid structured data
- ✅ All tests pass (existing + new)
- ✅ Documentation updated (README + PROJECT_SPEC)

---

## 10. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0-draft | 2026-04-13 | Initial specification draft |
