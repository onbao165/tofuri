# DeepL Translation Extension Specification

## 1. Purpose
This document defines the specification for adding DeepL-based translation support to Tofuri.
It extends existing translation contracts while preserving:
- YAML-driven configuration
- JSON standardized output
- Audit logging in JSONL
- Guardrail behavior for Japanese dissection scope

Status:
- Specification only (implementation pending)
- Effective date for planning: 2026-04-10

## 2. Scope
In scope:
- Add DeepL as an alternative translation provider
- Keep current translate command UX unchanged
- Preserve standardized output schema used by current translation flow
- Preserve audit logging and timestamp rules

Out of scope:
- Replacing existing OpenAI provider
- Removing current schema validation
- Automatic provider failover unless explicitly configured

## 3. Provider Modes
Supported provider values in translation.yml:
- openai
- deepl

Optional future mode:
- hybrid (DeepL for natural translation plus local/AI structural notes)

Provider selection rules:
- translate mode must read provider selection and route accordingly
- unknown provider value must fail fast
- only the selected provider configuration block is required

## 4. translation.yml Contract Extension
## 4.1 Shared keys (all providers)
Required:
- provider.active
- prompt.system
- response.schema_version
- response.require_json_object
- guardrails.reject_non_japanese_dissection
- guardrails.allow_mixed_reference_text
- audit.enabled
- audit.directory
- audit.file_pattern
- audit.timestamp_format
- audit.capture_raw_request
- audit.capture_raw_response
- audit.redact_api_key
- audit.token_usage_on_missing

## 4.2 OpenAI provider keys (existing)
Required when provider.active is openai:
- providers.openai.api_key
- providers.openai.model_default

## 4.3 DeepL provider keys (new)
Required when provider.active is deepl:
- providers.deepl.auth_key: non-empty string
- providers.deepl.api_url: non-empty string
- providers.deepl.formality: default | more | less | prefer_more | prefer_less

Optional when provider.active is deepl:
- providers.deepl.model_type
- providers.deepl.split_sentences
- providers.deepl.preserve_formatting
- providers.deepl.tag_handling

## 4.4 Example DeepL configuration block
```yaml
provider:
  active: deepl

providers:
  deepl:
    auth_key: "<DEEPL_AUTH_KEY>"
    api_url: "https://api-free.deepl.com/v2/translate"
    formality: "default"
    split_sentences: "1"
    preserve_formatting: true

  openai:
    api_key: "<OPENAI_API_KEY>"
    model_default: "gpt-4.1-mini"
```

## 5. Language Mapping Contract
CLI language values:
- en
- vi

DeepL target mapping:
- en -> EN
- vi -> Not supported natively by DeepL as of this spec baseline

Rules:
- If target language is unsupported by DeepL, fail fast with explicit message.
- Error must include suggested alternatives:
  - switch provider to openai
  - or choose supported DeepL target language
- For this v1 baseline, if `--language vi` is selected while provider is deepl, hard fail with suggestion to switch provider to openai.

## 6. Guardrail Behavior with DeepL
Because DeepL is translation-focused (not instruction-following chat), guardrails are enforced in application logic:
- Input must still be treated as source text data only.
- Non-Japanese dissection requests must be rejected or marked unsupported according to existing policy.
- Mixed-language references remain allowed when primary text is Japanese.

Recommended pre-check logic:
- Lightweight Japanese-content check before provider call
- On rejection, return standardized rejection JSON payload

## 7. Standardized Response Contract
Output must remain JSON object and match current schema_version behavior.

## 7.1 OpenAI mode schema
OpenAI mode keeps the dissection schema already defined in TRANSLATION_AI_SPEC.md.

## 7.2 DeepL mode schema (translation-only)
DeepL mode uses a separate success schema focused on basic translation.

Success shape (required fields):
- schema_version
- status=ok
- language
- input
- mode=translation_only
- translations[] with per-sentence fields:
  - index
  - source
  - natural
  - provider=deepl

Provider note:
- With DeepL mode, only natural translation is required.
- Dissection fields (segmented, literal, grammar_notes) are not part of DeepL success schema.
- `style` is ignored in DeepL mode.

Rejection shape (required):
- schema_version
- status=rejected
- reason_code
- message
- input

## 8. DeepL Request/Response Mapping
## 8.1 Request
Minimum required outbound fields:
- text
- target_lang
- Authorization header with auth key (never persisted raw in audit)

Optional pass-through fields from YAML:
- formality
- split_sentences
- preserve_formatting
- model_type

## 8.2 Response mapping
From DeepL response, map:
- translated text -> sentence natural
- detected_source_language -> audit metadata

Token usage:
- DeepL does not provide OpenAI-style token fields.
- usage.input_tokens/output_tokens/total_tokens must be null.

## 9. Audit Contract for DeepL
Audit file rules remain unchanged:
- directory: memory
- file pattern: translation_audit_YYYYMMDD.jsonl
- timestamp: ISO 8601 UTC

Additional DeepL record fields:
- provider: deepl
- api_variant: deepl.http
- deepl_endpoint
- detected_source_language (if returned)

Redaction rules:
- redact DeepL auth key in request payload/headers
- do not log Authorization headers raw

## 10. Error Handling Contract
Must classify and map DeepL failures into user-friendly runtime errors:
- authentication failure
- quota/rate limit
- unsupported target language
- invalid request parameters
- upstream/network error

All failures must still append one audit record with:
- status=error
- response containing provider error body or mapped message

## 11. CLI Compatibility
No new mandatory CLI flags required.

Existing behavior preserved:
- --language en|vi
- --style standard|cure-dolly
- --model remains OpenAI-specific and must fail fast when provider is deepl

DeepL-specific behavior:
- --style is accepted for CLI compatibility but ignored in deepl mode

Recommended optional future CLI additions:
- --provider openai|deepl (overrides YAML)
- --deepl-formality override

## 12. Testing Requirements
Required tests before enabling DeepL provider in production:
- config validation for deepl required/optional keys
- provider routing tests (openai vs deepl)
- unsupported target language error tests (vi under DeepL)
- standardized response schema validation in deepl mode
- audit redaction tests for deepl_auth_key
- deepL quota/rate error mapping tests

## 13. Migration Guidance
Current users can migrate by changing translation.yml only:
- Set provider.active to deepl
- Provide providers.deepl auth key and URL
- Use a DeepL-supported target language

If Vietnamese output is required:
- keep api.provider=openai until DeepL adds support or hybrid policy is implemented

## 14. Change Management
When DeepL implementation is added:
1. Update TRANSLATION_AI_SPEC.md to include provider matrix and final behavior.
2. Update PROJECT_SPEC.md section 6.5 and section 13.
3. Update README with provider setup examples and supported language caveats.
4. Add tests listed in section 12.

## 15. Revision
- Version: 1.0-draft
- Date: 2026-04-10
- Type: Specification draft for planned DeepL integration
