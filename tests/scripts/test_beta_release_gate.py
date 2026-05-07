from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_beta_release_gate_runs_safe_local_checks_only():
    source = (ROOT / "scripts/beta_release_gate.sh").read_text()

    assert "pytest" in source
    assert "npm --prefix frontend run build" in source
    assert "--backend-env .env.beta.example" in source
    assert "--frontend-env frontend/.env.beta.example" in source
    assert "docker compose -f docker-compose.beta-local.yml config >/dev/null" in source
    assert "git ls-files | grep -E '(^|/)\\.env($|\\.)'" in source
    assert "grep -Ev '(^|/)\\.env(\\.beta)?\\.example$'" in source
    assert "frontend/src/router.tsx" in source

    assert "docker compose -f docker-compose.beta-local.yml up" not in source
    assert "aws " not in source
    assert ".env.beta " not in source
    assert "cat .env" not in source


def test_beta_release_checklist_documents_gate_command():
    checklist = (ROOT / "docs/BETA_RELEASE_CHECKLIST.md").read_text()

    assert "bash scripts/beta_release_gate.sh" in checklist
    assert "local/code release readiness" in checklist
    assert "does not require AWS/Auth0 secrets" in checklist
