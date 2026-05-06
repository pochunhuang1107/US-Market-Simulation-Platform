from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_landing_and_workspace_routes_are_separate_surfaces():
    router_source = (ROOT / "frontend/src/router.tsx").read_text()
    shell_source = (ROOT / "frontend/src/components/layout/AppShell.tsx").read_text()

    assert "path: '/'," in router_source
    assert "element: <LandingPage />" in router_source
    assert "element: <AppShell />" in router_source
    assert "{ path: '/workspace', element: <StrategyChatPage /> }" in router_source
    assert '{ path: \'/chat\', element: <Navigate to="/workspace" replace /> }' in router_source

    assert "{ to: '/workspace', label: 'Workspace', end: true }" in shell_source
    assert "{ to: '/', label: 'Home', end: true }" not in shell_source
    assert "const isLandingRoute = location.pathname === '/';" not in shell_source


def test_landing_page_covers_story_and_ctas_without_profit_promises():
    landing_source = (ROOT / "frontend/src/pages/LandingPage.tsx").read_text()

    assert "ETF strategy research workspace" in landing_source
    assert "US Market Research" in landing_source
    assert "Open workspace" in landing_source
    assert "{ id: 'research', label: 'Research' },\n  { id: 'product', label: 'Product' },\n  { id: 'templates', label: 'Templates' },\n  { id: 'safety', label: 'Safety' }" in landing_source
    assert "const [activeSection, setActiveSection] = useState<LandingSectionId | null>(null);" in landing_source
    assert "const [showStickyNav, setShowStickyNav] = useState(false);" in landing_source
    assert "id=\"landing-hero\"" in landing_source
    assert "getBoundingClientRect().bottom <= 96" in landing_source
    assert "fixed left-0 right-0 top-0" in landing_source
    assert "IntersectionObserver" in landing_source
    assert "function updateActiveSection()" in landing_source
    assert "const marker = window.innerHeight * 0.38;" in landing_source
    assert "setActiveSection(null);" in landing_source
    assert "window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2" in landing_source
    assert "setActiveSection(sectionIds[sectionIds.length - 1]);" in landing_source
    assert "window.addEventListener('scroll', updateActiveSection, { passive: true });" in landing_source
    assert "aria-hidden={!showStickyNav}" in landing_source
    assert "aria-current={activeSection === item.id ? 'page' : undefined}" in landing_source
    assert "href={`#${item.id}`}" in landing_source
    assert "Describe a strategy, run a historical simulation, inspect trades, and compare results." in landing_source
    assert 'to="/workspace"' in landing_source
    assert 'to="/gallery"' in landing_source
    assert "Research loop" not in landing_source
    assert "CompactSection" not in landing_source
    assert "Natural-language drafting" in landing_source
    assert "Deterministic Strategy V2 configs" in landing_source
    assert "Historical ETF simulations" in landing_source
    assert "Trade-level signal values" in landing_source
    assert "Capital usage inspection" in landing_source
    assert "Parameter sweeps and comparison" in landing_source
    assert "Historical backtests only" in landing_source
    assert "Not financial advice" in landing_source
    assert "No guaranteed performance" in landing_source
    assert "Not a broker or live trading platform" in landing_source
    assert "ETF strategy research workspace for historical simulation and comparison." in landing_source
    assert 'to="/runs"' in landing_source
    assert 'to="/compare"' in landing_source
    assert 'aria-label="Landing footer"' in landing_source
    assert "profit" not in landing_source.lower()


def test_builder_handoffs_target_workspace_not_landing():
    chat_source = (ROOT / "frontend/src/pages/StrategyChatPage.tsx").read_text()
    gallery_source = (ROOT / "frontend/src/pages/StrategyGalleryPage.tsx").read_text()
    run_insight_source = (ROOT / "frontend/src/components/run-detail/RunInsightBreakdown.tsx").read_text()

    assert "HomeGuidancePanel" not in chat_source
    assert "navigate('/workspace', {" in chat_source
    assert "navigate('/workspace', {" in gallery_source
    assert "navigate('/workspace', {" in run_insight_source
    assert "navigate('/', {" not in gallery_source
