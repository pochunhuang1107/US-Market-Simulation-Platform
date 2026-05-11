# Strategy Builder Translation Boundary

The Strategy Builder executes deterministic Strategy V2 configs only. Natural
language input is translated into declarative Strategy V2 JSON, then validated
before the frontend can save or simulate it. LLM output must never execute
trading logic, run code, call tools, or bypass backend validation.

## Providers

`STRATEGY_BUILDER_PROVIDER=deterministic` is the default. The deterministic
provider wraps the existing parser-based builder used by
`/strategy-builder/generate`, including single-symbol strategies, rotation
drafts, parameter sweep drafts, follow-up edits, answer responses, and guidance
responses.

`STRATEGY_BUILDER_PROVIDER=hybrid` is the recommended product-like mode when AI
fallback is desired. It runs deterministic parsing first and returns immediately
when the result is a valid Strategy V2 draft. OpenAI is used only when
deterministic parsing returns guidance, an unsupported request, a validation
error, or no valid config. This keeps common RSI, trend/SMA, VIX/reference,
rotation, and follow-up edit prompts fast and cheaper while still allowing AI to
help with messier unsupported prompts.

`STRATEGY_BUILDER_PROVIDER=openai` enables the optional OpenAI adapter. It is
for direct provider testing, is disabled by default, is not required by CI or
beta release checks, and must be configured only in a private local/deployment
environment. If OpenAI is selected without `OPENAI_API_KEY`, the builder returns
provider-unavailable guidance; it does not expose stack traces, require a key
for deterministic behavior, or let provider output skip validation.

The API response remains compatible with the existing frontend shape:

- `config`
- `summary`
- `warnings`
- `assumptions`
- `changes`
- `guidance_data`
- `validation_data`
- `response_type`

Provider metadata is additive:

- `translation_provider`
- `translation_mode`
- `translation_fallback_used`
- `primary_provider`
- `fallback_provider`
- `deterministic_attempted`
- `openai_attempted`
- `llm_enabled`

## Structured Contract

Provider integrations plug in behind `StrategyTranslationProvider`. The OpenAI
adapter uses the Responses API when the optional SDK is installed and requests
structured JSON matching
`LlmStructuredTranslationOutput`, not free-form text:

```json
{
  "action": "create_config",
  "full_config": {
    "schema_version": "2.0"
  },
  "config_patch": null,
  "summary": "Drafted a Strategy V2 config.",
  "assumptions": [],
  "warnings": [],
  "unsupported_features": [],
  "validation_errors": [],
  "changes": []
}
```

Allowed actions are:

- `create_config`
- `edit_config`
- `guidance`

`create_config` must return a complete Strategy V2 config. `edit_config` may
return a full config or a `config_patch` applied to `current_config`. `guidance`
returns no executable draft. Unsupported requests should become guidance or
`unsupported_features`; providers must not invent unsupported fields,
indicators, symbols, or execution behavior.

## Validation Pipeline

All translated configs, deterministic or future LLM, must pass backend checks:

1. Parse/construct declarative Strategy V2 JSON only.
2. Validate with the Strategy V2 schema.
3. Normalize via `StrategyV2.model_dump(mode="json", exclude_none=True)`.
4. Validate ETF/reference symbols against backend-supported symbols.
5. Validate date coverage and plan backtest windows.
6. Enforce advanced rotation and parameter sweep entitlements.
7. Reject unsupported features instead of silently executing them.
8. Reject user-facing performance promises such as guaranteed returns.

Frontend validation is only a convenience layer. The backend is the source of
truth.

## Provider Selection

Safe defaults:

```env
STRATEGY_BUILDER_PROVIDER=deterministic
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=20
OPENAI_MAX_RETRIES=1
```

Provider options:

- `deterministic`: default, fastest path, no OpenAI key required.
- `hybrid`: deterministic first, OpenAI fallback only when needed.
- `openai`: direct OpenAI provider testing.

OpenAI setup for local private testing:

1. Install the optional SDK in your local environment, for example
   `pip install -e ".[openai]"`.
2. Put `STRATEGY_BUILDER_PROVIDER=openai` or
   `STRATEGY_BUILDER_PROVIDER=hybrid` in your uncommitted local `.env`.
3. Put `OPENAI_API_KEY=<your private key>` in the same uncommitted env. The key
   is required when `provider=openai`; in `provider=hybrid`, it is required only
   when a deterministic miss actually needs fallback.
4. Optionally set `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, or
   `OPENAI_MAX_RETRIES`.
5. Run tests with mocked clients; no test should call the real OpenAI API.

Do not commit real keys. The beta preflight requires `OPENAI_API_KEY` only when
`STRATEGY_BUILDER_PROVIDER=openai`; deterministic and hybrid beta releases do
not require any OpenAI variables at preflight time.

## Testing Notes

Provider tests should mock the OpenAI client or adapter method. Required safety
coverage includes:

- deterministic remains the default
- hybrid returns valid deterministic drafts without calling OpenAI
- hybrid falls back to mocked OpenAI only for deterministic misses
- OpenAI is selected only when configured
- missing keys return safe guidance
- valid mocked structured output is normalized and returned
- invalid configs, unsupported symbols, and performance promises are rejected
- entitlement gates still reject gated rotation or sweep configs
- provider errors/timeouts return safe guidance without raw upstream details

The LLM is translation-only. It does not run strategy logic, execute tools,
simulate results, train ML models, or change simulation engine behavior.
