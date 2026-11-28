# AI Safety, PII Minimization & Third-Party Model Consent

## 1. Verified Default Model IDs
Verified against the official Google Gemini API documentation:
- Quality model: `gemini-3.6-flash`
- Fast / structured extraction model: `gemini-3.5-flash-lite`
- Optional OpenRouter fallback: restricted to `:free` models unless `AI_ALLOW_PAID_FALLBACK=true`.

When `IS_PRODUCTION=true`, `GEMINI_API_KEY` is configured, and `AI_STARTUP_HEALTHCHECK=true`, the backend runs `gemini_service.verify_startup_model_health()` at startup and fails loudly (`RuntimeError`) if the configured model cannot be reached, rather than silently dropping to fallback heuristics.

## 2. Explicit Third-Party Model Consent
- Controlled by `AI_THIRD_PARTY_CONSENT_REQUIRED` (default `false` for local dev; recommended `true` in multi-tenant production) and per-request / per-user `ai_consent_granted` flag.
- When consent is required and not granted for a user, TalentFlow AI does **not** transmit CV or profile text to any external LLM API; it executes exclusively on the deterministic local ground-truth engine and logs `status="CONSENT_REQUIRED"` in `ai_operation_logs`.

## 3. PII Minimization & Input Size Caps
- `minimize_pii_for_llm()` strips emails (`[REDACTED_EMAIL]`), phone numbers (`[REDACTED_PHONE]`), IBANs (`[REDACTED_IBAN]`), and 11-digit national IDs (`[REDACTED_ID]`) before sending prompts to external LLM providers.
- Untrusted job postings and candidate markdown payloads are capped (`max_chars`) and wrapped inside random-nonce XML tags (`wrap_untrusted_input`) with explicit system-instruction boundaries against prompt injection.

## 4. Per-User Daily Token Budget & Cache Hygiene
- `AI_DAILY_TOKEN_BUDGET_PER_USER` (default `250000` tokens/UTC day) caps external LLM usage per authenticated user. Exceeding the budget logs `status="BUDGET_EXCEEDED"` and cleanly falls back to deterministic heuristics.
- Persistent cache entries (`ai_cache_entries`) include tenant (`user_id`), `model_name`, `prompt_version`, and schema tag in the SHA-256 key, and enforce an eviction cap (`MAX_AI_CACHE_ENTRIES`, default `1000`), pruning expired rows and oldest entries automatically.
