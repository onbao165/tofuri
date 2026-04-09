# Tofuri Project Specification (Source of Truth)

## 1. Purpose
Tofuri is a command-line Japanese text utility that supports:
- Token segmentation
- Furigana rendering with HTML ruby tags
- Combined segmentation and furigana annotation
- Dictionary lookup (local TSV and/or Jisho fallback)
- AI-assisted translation with grammar-oriented explanation styles
- Offline dictionary download/build pipeline (English and Vietnamese)

This document defines the expected behavior of the tool and should be updated whenever code behavior changes.

## 2. Scope and Non-Goals
### In scope
- Command-line usage with stdin/file input and stdout/file output
- Interactive numbered menu mode
- Japanese tokenization via fugashi (UniDic)
- Local dictionary lookup in TSV format
- Optional online lookup via Jisho API
- Translation via OpenAI Responses API

### Out of scope
- GUI application
- Rich HTML rendering beyond ruby tags
- Full linguistic disambiguation guarantees
- Offline machine translation

## 3. Runtime Dependencies
Core imports used at runtime:
- argparse
- fugashi
- jaconv
- requests (optional but required for dictionary download and Jisho lookup)
- openai (required only for translate mode)
- pyyaml (required for translate mode configuration loading)

Dictionary parser and extraction dependencies:
- gzip
- io
- zipfile
- sqlite3
- xml.etree.ElementTree
- tempfile

Install baseline dependencies:
- pip install fugashi unidic jaconv requests openai pyyaml
- python -m unidic download

## 4. Project Structure
Current important files/folders:
- README.md: user-facing usage guide
- tofuri.py: single-file implementation and CLI entrypoint
- TRANSLATION_AI_SPEC.md: detailed AI translation configuration, guardrails, output schema, and audit contract
- dictionaries/: default location for local TSV dictionaries
- tests/test_furigana_regression.py: regression tests focused on furigana behavior
- input.txt and output.txt: common default examples for file-based workflows

## 5. Public CLI Contract
## 5.1 Command shape
- Primary entrypoint: python tofuri.py
- Optional positional mode argument:
  - segment
  - furigana
  - annotate
  - lookup
  - translate
  - dict-download

If mode is omitted, interactive menu mode starts.

## 5.2 Common options
- --input, -i: input file path (if omitted, reads stdin)
- --output, -o: output file path (if omitted, writes stdout)
- --json: JSON output when supported by mode
- --interactive: force interactive menu mode

## 5.3 Mode-specific options
### lookup
- --dict-source: auto | local | jisho | none (default auto)
- --dict-lang: en | vi | both (default both)
- --local-dict: backward-compatible alias for English local dictionary
- --local-dict-en: English TSV path (default dictionaries/jmdict_en.tsv)
- --local-dict-vi: Vietnamese TSV path (default dictionaries/jmdict_vi.tsv)
- --lookup-format: text | markdown (default text)
- --definition-wrap: integer width for markdown definition wrapping, 0 disables

### translate
- --language: en | vi (default en)
- --style: standard | cure-dolly (default cure-dolly)
- --model: optional OpenAI model name override (default comes from translation.yml api.model_default)

### furigana
- --no-dedupe-ruby: disable preservation of existing ruby blocks

### dict-download
- --dict-dir: output dictionary directory (default dictionaries)

## 6. Mode Behavior Specifications
## 6.1 segment
Input Japanese text is tokenized per line and output as space-separated token surfaces.
If --json is enabled, outputs an array of token objects with fields:
- surface
- reading
- pos

## 6.2 furigana
Outputs input text with kanji-bearing tokens converted to ruby tags:
- <ruby>surface-kanji<rt>reading-hiragana</rt></ruby>

Behavior details:
- Existing ruby blocks are preserved by default using placeholder protection.
- Ruby deduplication/preservation is disabled with --no-dedupe-ruby.
- Non-kanji tokens pass through unchanged.
- Reading extraction uses fugashi feature.kana converted to hiragana with jaconv.

## 6.3 annotate
Line-wise output combining segmentation and ruby conversion in one pass.
If --json is enabled, each token object includes:
- surface
- reading
- pos
- ruby

## 6.4 lookup
Builds unique token rows and frequency counts, then enriches rows via dictionaries.
Each row tracks:
- word
- count
- reading
- pos
- definition
- definition_en
- definition_vi
- source

Lookup source behavior:
- auto: try local dictionaries first, then Jisho fallback if no local hit
- local: use only local dictionaries, raise runtime error if required local dictionaries are missing/empty
- jisho: use Jisho API only
- none: return tokenizer-derived rows without dictionary definitions

Language behavior:
- dict-lang en: prefer and emit English definitions
- dict-lang vi: prefer and emit Vietnamese definitions
- dict-lang both: aggregate EN and VI in combined definition text

Vietnamese filtering behavior:
- For specific POS categories, Vietnamese lookup candidates are skipped to reduce low-value matches:
  - 助詞
  - 助動詞
  - 補助記号
  - 接頭辞
  - 接尾辞

Output formats:
- text (tab-separated columns)
- markdown table
- JSON via --json

Markdown wrapping behavior:
- Enabled when --definition-wrap > 0
- Definitions are split primarily on semicolon segments
- Wrapped lines are joined with HTML <br>

## 6.5 translate
Requires translation configuration from root file translation.yml.

Configuration contract:
- System prompt is loaded from translation.yml only.
- API key is loaded from translation.yml only.
- If translation.yml is missing or required fields are missing/invalid, translate mode fails.
- YAML parsing should use pyyaml.

Prompt style behavior:
- cure-dolly style requests:
  1. segmented Japanese
  2. literal scaffold translation
  3. natural translation
  4. short grammar notes focused on particles/subject/predicate engine
- standard style requests sentence-aligned translation only

Guardrail behavior:
- Model is instructed to treat user input only as text to translate/dissect.
- Input instruction injection inside source text must be ignored.
- Non-Japanese dissection requests should be rejected by model policy.
- Mixed-language references inside otherwise Japanese text are allowed.

Standardized response behavior:
- Translation response must be a JSON object.
- Required success sections include segmented, literal, natural, grammar_notes.
- grammar_notes must be a list of objects.
- Rejections must use a standardized JSON rejection object.

API integration:
- Uses openai.OpenAI client
- Preferred path uses client.responses.create(model=..., input=...)
- Compatibility fallback uses client.chat.completions.create(..., response_format={"type": "json_object"}) for older SDKs
- Returns extracted text and validates against required JSON schema

Audit behavior:
- Each translation API call is logged in JSONL.
- Log directory is memory at repo root.
- Daily file pattern: translation_audit_YYYYMMDD.jsonl.
- Each record includes ISO 8601 UTC timestamp, request, response, and token usage.
- Token usage fields may be null if usage is unavailable.
- API key must be redacted in all audit records.

## 6.6 dict-download
Downloads and converts well-known dictionaries into local TSV files.

Sources:
- English JMdict gzip from EDRDG:
  - http://ftp.edrdg.org/pub/Nihongo/JMdict.gz
- Vietnamese database zip from philongrobo/jsdict:
  - https://raw.githubusercontent.com/philongrobo/jsdict/main/assets/databases/nhat_viet.db.zip

Outputs:
- dictionaries/jmdict_en.tsv
- dictionaries/jmdict_vi.tsv

Post-processing:
- Temporary archives are removed after TSV generation.
- Returns and prints entry counts for EN and VI.

## 7. Dictionary Data Specification
## 7.1 TSV format
One entry per line:
- word<TAB>reading_hiragana<TAB>definition

Rules:
- Lines beginning with # are comments
- Invalid or short rows are skipped during loading

## 7.2 English extraction from JMdict XML
- Uses language code filtering via xml:lang
- English target includes glosses tagged eng or empty
- Up to 8 glosses are used and de-duplicated
- Reading is derived from first reading element and normalized to hiragana

## 7.3 Vietnamese extraction from jsdict SQLite
- Reads table jv with columns word, meaning
- Attempts reading extraction from quoted bracket pattern 「...」
- Reading is accepted only for kana-only matches and normalized to hiragana
- Definition cleaning strips noisy metadata/examples and keeps concise glosses

## 8. Furigana Rendering Algorithm Notes
Token ruby rendering pipeline:
1. Detect kanji spans in token surface
2. Build alternating segment list (kanji vs other)
3. Advance reading cursor through kana anchors and surrounding kana text
4. Assign ruby segments heuristically across remaining kanji blocks
5. Emit ruby tags around kanji segments only

Safety behavior:
- If reading is missing, token is returned unchanged
- Placeholder strategy prevents nested/redundant ruby around pre-existing ruby blocks

## 9. Input and Output Behavior
Input behavior:
- If input file path is provided, file must exist
- Otherwise stdin is consumed
- If stdin is tty, a Windows hint is printed to stderr for multiline paste submission

Output behavior:
- Output text is stripped of trailing newline before final write
- File output overwrites target file
- Stdout output adds a final newline

Text sanitization behavior:
- sanitize_text uses UTF-8 encode/decode with replace for robustness

## 10. Interactive Mode Specification
Interactive flow:
1. Choose mode from numbered list
2. For all modes except dict-download, choose input source:
   - Paste multiline text ending with __END__
   - File path (default input.txt)
3. Choose output path:
   - Paste mode: blank means stdout
   - File mode: blank defaults to output.txt
4. Prompt mode-specific options (JSON, lookup source/language, translate options, ruby preservation)

Defaults in interactive mode:
- translate model: translation.yml api.model_default (unless user provides override)
- translate style: cure-dolly
- lookup markdown wrap fallback on invalid numeric input: 120

## 11. Exit Codes and Error Contract
Expected exit code behavior from main():
- 0 on success
- 1 on runtime/processing errors (input failures, missing dependencies, API errors, dictionary failures)
- 2 when input text is empty after trimming

Errors are printed to stderr in the form:
- Error: <message>

## 12. Backward Compatibility Rules
- --local-dict remains accepted as alias for English dictionary path
- In non-interactive mode, --local-dict-en is resolved with fallback to --local-dict

Compatibility expectation:
- Existing scripts using --local-dict should continue to work

## 13. External Service Contracts
### Jisho API
- Endpoint: https://jisho.org/api/v1/search/words
- Query param: keyword=<word>
- Timeout: 10 seconds
- On network/API/data failure, silently returns no hit for that word

### OpenAI API
- Requires valid API key from translation.yml
- Supports both Responses API and legacy Chat Completions API for SDK compatibility

## 14. Performance and Reliability Notes
- Tokenization is run per line for human-readable text outputs
- lookup mode tokenizes once for counting and metadata map
- Local dictionary loads entire TSV into memory lists
- Missing requests package disables online lookup/download features

## 15. Testing Status and Gaps
Known tests:
- tests/test_furigana_regression.py exists and should remain green for furigana changes

Current gaps to consider for future test expansion:
- lookup markdown wrapping edge cases
- dictionary language fallback combinations
- interactive mode argument synthesis
- dict-download integration behavior with unavailable network
- translate mode API error handling branches

## 16. Change Management for This Spec
When implementation changes in tofuri.py or behavior docs change in README.md:
1. Update this file in the same change set.
2. Keep sections 5 through 13 strictly aligned with implemented behavior.
3. If behavior intentionally diverges from this spec, mark the section as Pending Update with date and rationale until resolved.

Suggested update checklist:
- CLI options updated
- Defaults updated
- Error and exit code behavior updated
- Data format updated
- External URL/source changes updated
- README consistency verified

## 17. Versioning Note
This specification reflects repository state as of 2026-04-09 and should be treated as the canonical project contract until superseded by a later revision.
