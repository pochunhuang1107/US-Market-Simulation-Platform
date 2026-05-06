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
    assert "AUTH0_RETURN_TO_STORAGE_KEY" in provider_source
    assert "normalizeReturnToPath(returnTo)" in provider_source
    assert "storeAuthReturnTo(normalizedReturnTo)" in provider_source
    assert "appState: {" in provider_source
    assert "returnTo: normalizedReturnTo" in provider_source
    assert "consumeStoredAuthReturnTo() ?? '/'" in provider_source
    assert "window.sessionStorage.removeItem(AUTH0_RETURN_TO_STORAGE_KEY)" in provider_source
    assert "function replaceBrowserRoute(returnTo: string)" in provider_source
    assert "window.history.replaceState({}, document.title, returnTo)" in provider_source
    assert "window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))" in provider_source
    assert "function isAuth0CallbackRequest(): boolean" in provider_source
    assert "params.has('code') || params.has('error')" in provider_source
    assert "isLoading && isAuth0CallbackRequest()" in provider_source
    assert "<Auth0CallbackLoadingState />" in provider_source
    assert "Finishing sign-in before loading your research workspace." in provider_source

    assert "isAccessTokenUnavailableError(error)" in api_source
    assert "const status = error.reason === 'loading' ? 0 : 401" in api_source
    assert "'auth_loading'" in api_source
    assert "'auth_unauthenticated'" in api_source
    assert "'auth_token_unavailable'" in api_source

    assert "const currentRoute = `${location.pathname}${location.search}${location.hash}`" in shell_source
    assert "void auth.login(currentRoute)" in shell_source
    assert "<AuthRequiredState returnTo={currentRoute} />" in shell_source
    assert "returnTo={currentRoute}" in shell_source
