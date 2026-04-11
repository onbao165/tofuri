Installation
```bash
pip install fugashi unidic jaconv requests openai pyyaml
python -m unidic download
```

Specification
- Canonical project specification (source of truth): `PROJECT_SPEC.md`
- Detailed AI translation specification: `TRANSLATION_AI_SPEC.md`
- DeepL translation extension specification: `DEEPL_TRANSLATION_SPEC.md`

Quick Start
```bash
# Interactive numbered menu (recommended)
python tofuri.py

# Segmentation
Get-Content input.txt | python tofuri.py segment

# Furigana HTML ruby tags
Get-Content input.txt | python tofuri.py furigana

# Segmentation + furigana
Get-Content input.txt | python tofuri.py annotate

# Dictionary lookup for all tokens
Get-Content input.txt | python tofuri.py lookup --dict-source auto

# Download well-known offline dictionaries (JMdict)
python tofuri.py dict-download --dict-dir dictionaries

# Offline lookup from downloaded English + Vietnamese dictionaries
Get-Content input.txt | python tofuri.py lookup --dict-source local --dict-lang both --local-dict-en dictionaries/jmdict_en.tsv --local-dict-vi dictionaries/jmdict_vi.tsv

# Translation to English or Vietnamese
Get-Content input.txt | python tofuri.py translate --language en --style cure-dolly
Get-Content input.txt | python tofuri.py translate --language vi --style cure-dolly

# DeepL simple source/translation output (line-by-line)
Get-Content input.txt | python tofuri.py translate --provider deepl --language en --translate-output simple

# DeepL tooltip span output (preserves input line breaks)
Get-Content input.txt | python tofuri.py translate --provider deepl --language en --translate-output span

# Copy output directly to clipboard
Get-Content input.txt | python tofuri.py translate --provider deepl --language en --translate-output simple --clipboard
```

Translation Configuration
- Translate mode requires `translation.yml` in project root.
- API key is loaded from `translation.yml` (`api.api_key`) only.
- If `translation.yml` is missing or incomplete, translate mode fails fast.
- Audit logs are written to `memory/translation_audit_YYYYMMDD.jsonl`.
- Each audit record includes UTC timestamp, request, response, and token usage (or null when unavailable).
- Translation supports both OpenAI Responses API and legacy Chat Completions SDK paths.

Modes
- `segment`: token segmentation output.
- `furigana`: ruby-tag furigana output. Existing `<ruby>` blocks are preserved by default.
- `annotate`: segmentation + ruby in one pass.
- `lookup`: dictionary lookup table (or JSON with `--json`).
- `translate`: AI translation with grammar-oriented explanation style.

Common Options
- `--input, -i`: read from file path instead of stdin.
- `--output, -o`: write output to file path.
- `--clipboard`: copy output to clipboard instead of file/stdout.
- `--json`: use JSON output when available.
- `--no-dedupe-ruby`: disable ruby deduplication protection.
- `--interactive`: force numbered interactive mode.

Interactive Menu Flow
- Run `python tofuri.py`.
- Pick mode by number:
	- `1` Segmentation
	- `2` Furigana (HTML ruby)
	- `3` Segmentation + Furigana
	- `4` Dictionary lookup
	- `5` Translation (AI)
- Choose input source:
	- `1` Paste multiline text and finish with `__END__`
	- `2` Input file path (blank uses `input.txt`)
- In file-path mode, output path blank uses `output.txt`.
- Follow prompted options for JSON output, dictionary source, language, style, and model as needed.

Lookup Options
- `--dict-source auto|local|jisho|none`
- `--dict-lang en|vi|both` language preference for dictionary definitions
- `--local-dict-en <path>` English local TSV dictionary path (default: `dictionaries/jmdict_en.tsv`)
- `--local-dict-vi <path>` Vietnamese local TSV dictionary path (default: `dictionaries/jmdict_vi.tsv`)
- `--local-dict <path>` backward-compatible alias for English local dictionary path
- `--lookup-format text|markdown` output format for lookup mode when not using JSON
- `--definition-wrap <int>` wrap width for markdown definition cells using `<br>` (0 disables wrapping)

Markdown Lookup Example
```bash
python tofuri.py lookup --input input.txt --dict-source local --dict-lang both --lookup-format markdown

# Markdown with definition wrapping in table cells
python tofuri.py lookup --input input.txt --dict-source local --dict-lang both --lookup-format markdown --definition-wrap 100
```

Dictionary Download
- Run: `python tofuri.py dict-download --dict-dir dictionaries`
- Sources:
	- English: official JMdict from EDRDG (`http://ftp.edrdg.org/pub/Nihongo/JMdict.gz`)
	- Vietnamese: open Japanese-Vietnamese database from `philongrobo/jsdict` (`nhat_viet.db.zip`)
- Output files:
	- `dictionaries/jmdict_en.tsv`
	- `dictionaries/jmdict_vi.tsv`
- Notes:
	- Vietnamese definitions are cleaned into concise glosses for lookup readability.
	- Temporary downloaded archives are removed automatically after TSV generation.

Local Dictionary TSV Format
- One entry per line: `word<TAB>reading_hiragana<TAB>definition`
- Lines starting with `#` are comments.

Translate Options
- `--language en|vi`
- `--style standard|cure-dolly`
- `--provider openai|deepl` optional override (default uses `translation.yml` -> `provider.active`)
- `--model <openai-model-name>` optional override for OpenAI only (default uses `translation.yml` -> `providers.openai.model_default`)
- `--translate-output json|simple|span` translation output format.
	- `simple`: DeepL-only source/translation pairs line-by-line
	- `span`: DeepL-only tooltip span output as `<span class="trans-hover" data-meaning="...">...</span>` while preserving input line breaks

Translation Key Setup
Set provider config in `translation.yml`:
```yaml
provider:
	active: openai

providers:
	openai:
		api_key: "your-openai-key"
		model_default: "gpt-4.1-mini"

	deepl:
		auth_key: "your-deepl-key"
		api_url: "https://api-free.deepl.com/v2/translate"
		formality: "default"
```

Example With File Input
```bash
python tofuri.py lookup --input input.txt --json --output lookup.json
```