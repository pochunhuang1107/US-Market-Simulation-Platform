# Strategy Builder Translation Boundary

The Strategy Builder executes deterministic Strategy V2 configs only. Natural
language input is translated into declarative Strategy V2 JSON, then validated
before the frontend can save or simulate it. LLM output must never execute
trading logic, run code, call tools, or bypass backend validation.

## Current Provider

`STRATEGY_BUILDER_PROVIDER=deterministic` is the default. The deterministic
provider wraps the existing parser-based builder used by
`/strategy-builder/generate`, including single-symbol strategies, rotation
drafts, parameter sweep drafts, follow-up edits, answer responses, and guidance
responses.

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
- `llm_enabled`

## Future LLM Contract

Future provider integrations must plug in behind
`StrategyTranslationProvider`. A provider returns structured JSON matching
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
  "validation_errors": []
}
```

Allowed actions are:

- `create_config`
- `edit_config`
- `guidance`

`create_config` must return a complete Strategy V2 config. `edit_config` may
return a full config or a `config_patch` applied to `current_config`. `guidance`
returns no executable draft.

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
STRATEGY_BUILDER_LLM_ENABLED=false
```

LLM translation is disabled in this branch. No provider keys, model names,
secrets, or network clients are required or committed. If LLM mode is requested
while disabled, the API falls back to the deterministic provider.

## Future Integration Notes

To add OpenAI or another provider later:

1. Implement a concrete `StrategyTranslationProvider`.
2. Keep provider calls outside deterministic builder logic.
3. Return only `LlmStructuredTranslationOutput` JSON.
4. Run the shared validation pipeline before returning any config.
5. Keep API keys in deployment secret stores, never in committed files.
6. Add provider tests that mock external calls and prove invalid output is
   rejected before simulation.

Simulation engine behavior is intentionally outside this boundary.
