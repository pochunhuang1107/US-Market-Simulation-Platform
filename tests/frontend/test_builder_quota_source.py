from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_workspace_optimistically_decrements_builder_prompt_quota():
    source = (ROOT / "frontend/src/pages/StrategyChatPage.tsx").read_text()

    assert "function decrementBuilderPromptQuota" in source
    assert "builder_prompts_remaining_today: Math.max(0, remaining - 1)" in source
    assert "builder_prompts_used_today: shouldIncrementUsed ? usedToday + 1 : usedToday" in source
    assert "if (!prompt || isGenerating) return;" in source
    assert "if (isPromptTooLong) return;" in source
    assert "if (entitlementsBeforeSubmit)" in source
    assert "current ? decrementBuilderPromptQuota(current) : current" in source
    assert "const refreshedEntitlements = await fetchMeEntitlements();" in source
    assert "setEntitlements(refreshedEntitlements);" in source
    assert "if (requestFailed && entitlementsBeforeSubmit)" in source
    assert "setEntitlements(entitlementsBeforeSubmit);" in source
