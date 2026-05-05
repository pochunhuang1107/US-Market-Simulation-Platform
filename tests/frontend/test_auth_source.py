from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_auth0_restore_state_gates_protected_routes_before_api_calls():
    shell_source = (ROOT / "frontend/src/components/layout/AppShell.tsx").read_text()
    provider_source = (ROOT / "frontend/src/auth/AppAuthProvider.tsx").read_text()
    api_source = (ROOT / "frontend/src/lib/api.ts").read_text()

    assert "auth.isAuth0Mode && auth.isLoading" in shell_source
    assert 'title="Restoring session..."' in shell_source
    assert "(!auth.isAuthenticated && !hasManualAccessToken)" in shell_source
    assert "getDevelopmentAccessToken()" in shell_source

    assert "new AccessTokenUnavailableError('loading', 'Restoring session...')" in provider_source
    assert "new AccessTokenUnavailableError('unauthenticated', 'Sign in required.')" in provider_source
    assert "getDevelopmentAccessToken()" in provider_source

    assert "isAccessTokenUnavailableError(error)" in api_source
    assert "const status = error.reason === 'loading' ? 0 : 401" in api_source
    assert "'auth_loading'" in api_source
    assert "'auth_unauthenticated'" in api_source
    assert "'auth_token_unavailable'" in api_source
