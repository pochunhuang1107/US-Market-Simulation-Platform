#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


PROTECTED_ENVS = {"beta", "prod", "production"}
DEV_AUTH_MODES = {"dev", "local", "test"}


@dataclass
class Finding:
    level: str
    message: str


@dataclass
class CheckContext:
    backend: dict[str, str] = field(default_factory=dict)
    frontend: dict[str, str] = field(default_factory=dict)
    target_env: str = "beta"
    require_s3_artifacts: bool = True
    findings: list[Finding] = field(default_factory=list)
    checks: int = 0

    def error(self, message: str) -> None:
        self.findings.append(Finding("ERROR", message))

    def warn(self, message: str) -> None:
        self.findings.append(Finding("WARN", message))

    def note_check(self) -> None:
        self.checks += 1


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(path)

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number} is not KEY=VALUE format")

        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_inline_comment(value.strip())
        if not key:
            raise ValueError(f"{path}:{line_number} has an empty key")
        if not _valid_key(key):
            raise ValueError(f"{path}:{line_number} has invalid key {key!r}")
        values[key] = _unquote(value)

    return values


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _valid_key(key: str) -> bool:
    return key.replace("_", "A").isalnum() and not key[0].isdigit()


def load_env(path: Path | None) -> dict[str, str]:
    if path is None:
        return dict(os.environ)
    return parse_env_file(path)


def configured(values: dict[str, str], key: str) -> bool:
    return bool(values.get(key, "").strip())


def normalized(values: dict[str, str], key: str, default: str = "") -> str:
    return values.get(key, default).strip().lower()


def check_backend(ctx: CheckContext) -> None:
    backend = ctx.backend
    env = normalized(backend, "ENV", ctx.target_env)
    auth_mode = normalized(backend, "AUTH_MODE", "dev" if env not in PROTECTED_ENVS else "")
    protected = env in PROTECTED_ENVS

    require_key(ctx, backend, "DATABASE_URL", "Backend must configure DATABASE_URL.")

    ctx.note_check()
    if protected and auth_mode in DEV_AUTH_MODES:
        ctx.error("Protected ENV must not use dev/local/test AUTH_MODE.")

    ctx.note_check()
    if protected and normalized(backend, "ENABLE_DEV_ADMIN_OVERRIDE", "false") == "true":
        ctx.error("Protected ENV must not enable DEV_ADMIN override.")

    oidc_required = protected or auth_mode == "oidc"
    if oidc_required:
        require_key(ctx, backend, "OIDC_JWKS_URL", "OIDC mode requires OIDC_JWKS_URL.")
        require_key(ctx, backend, "OIDC_ISSUER", "OIDC mode should configure OIDC_ISSUER.")
        require_key(ctx, backend, "OIDC_AUDIENCE", "OIDC mode should configure OIDC_AUDIENCE.")
    else:
        ctx.note_check()

    require_key(ctx, backend, "MARKET_DATA_PATH", "Backend must configure MARKET_DATA_PATH.")
    require_key(ctx, backend, "ETF_METADATA_S3_URI", "Backend must configure ETF_METADATA_S3_URI.")
    require_key(ctx, backend, "REFERENCE_SERIES_DATA_PATH", "Backend must configure REFERENCE_SERIES_DATA_PATH.")
    require_key(
        ctx,
        backend,
        "REFERENCE_SERIES_METADATA_S3_URI",
        "Backend must configure REFERENCE_SERIES_METADATA_S3_URI.",
    )

    artifact_backend = normalized(backend, "ARTIFACT_STORAGE_BACKEND", "LOCAL").upper()
    ctx.note_check()
    if ctx.require_s3_artifacts and protected and artifact_backend == "LOCAL":
        ctx.error("Protected beta/production should use ARTIFACT_STORAGE_BACKEND=S3.")
    elif protected and artifact_backend == "LOCAL":
        ctx.warn("Protected beta/production is configured for local artifact storage.")

    if artifact_backend == "S3":
        require_key(ctx, backend, "ARTIFACT_S3_BUCKET", "S3 artifacts require ARTIFACT_S3_BUCKET.")
        require_key(ctx, backend, "ARTIFACT_S3_PREFIX", "S3 artifacts should configure ARTIFACT_S3_PREFIX.")
        require_key(ctx, backend, "ARTIFACT_S3_REGION", "S3 artifacts should configure ARTIFACT_S3_REGION.")
    elif artifact_backend == "LOCAL":
        require_key(ctx, backend, "ARTIFACTS_DIR", "Local artifacts require ARTIFACTS_DIR.")
    else:
        ctx.error("ARTIFACT_STORAGE_BACKEND must be LOCAL or S3.")

    strategy_provider = normalized(backend, "STRATEGY_BUILDER_PROVIDER", "deterministic")
    ctx.note_check()
    if strategy_provider not in {"deterministic", "openai", "llm"}:
        ctx.error("STRATEGY_BUILDER_PROVIDER must be deterministic, openai, or llm.")

    if strategy_provider == "openai":
        require_key(
            ctx,
            backend,
            "OPENAI_API_KEY",
            "OPENAI_API_KEY is required only when STRATEGY_BUILDER_PROVIDER=openai.",
        )
    else:
        ctx.note_check()


def check_frontend(ctx: CheckContext) -> None:
    frontend = ctx.frontend
    if not frontend:
        ctx.warn("Frontend env was not checked.")
        return

    backend_env = normalized(ctx.backend, "ENV", ctx.target_env)
    protected = backend_env in PROTECTED_ENVS
    auth_provider = normalized(frontend, "VITE_AUTH_PROVIDER", "dev")

    ctx.note_check()
    if protected and auth_provider != "auth0":
        ctx.error("Protected beta frontend should set VITE_AUTH_PROVIDER=auth0.")

    if protected or auth_provider == "auth0":
        require_key(ctx, frontend, "VITE_AUTH0_DOMAIN", "Auth0 frontend build requires VITE_AUTH0_DOMAIN.")
        require_key(ctx, frontend, "VITE_AUTH0_CLIENT_ID", "Auth0 frontend build requires VITE_AUTH0_CLIENT_ID.")
        require_key(ctx, frontend, "VITE_AUTH0_AUDIENCE", "Auth0 frontend build requires VITE_AUTH0_AUDIENCE.")
    else:
        ctx.note_check()


def require_key(ctx: CheckContext, values: dict[str, str], key: str, message: str) -> None:
    ctx.note_check()
    if not configured(values, key):
        ctx.error(message)


def run_checks(
    backend: dict[str, str],
    frontend: dict[str, str] | None,
    *,
    target_env: str,
    require_s3_artifacts: bool,
) -> CheckContext:
    ctx = CheckContext(
        backend=backend,
        frontend=frontend or {},
        target_env=target_env.strip().lower(),
        require_s3_artifacts=require_s3_artifacts,
    )
    check_backend(ctx)
    check_frontend(ctx)
    return ctx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate beta deployment env shape without printing secrets.",
    )
    parser.add_argument(
        "--backend-env",
        type=Path,
        default=Path(".env.beta.example"),
        help="Backend env file to validate. Defaults to .env.beta.example.",
    )
    parser.add_argument(
        "--frontend-env",
        type=Path,
        default=Path("frontend/.env.beta.example"),
        help="Frontend env file to validate. Defaults to frontend/.env.beta.example.",
    )
    parser.add_argument(
        "--target-env",
        default="beta",
        choices=["local", "beta", "production"],
        help="Deployment target to validate when ENV is absent. Defaults to beta.",
    )
    parser.add_argument(
        "--allow-local-artifacts",
        action="store_true",
        help="Warn instead of failing when beta/production uses local artifact storage.",
    )
    parser.add_argument(
        "--current-env",
        action="store_true",
        help="Validate the current process environment instead of env files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.current_env:
            backend = load_env(None)
            frontend = load_env(None)
        else:
            backend = load_env(args.backend_env)
            frontend = load_env(args.frontend_env)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR unable to load env input: {exc}", file=sys.stderr)
        return 2

    ctx = run_checks(
        backend,
        frontend,
        target_env=args.target_env,
        require_s3_artifacts=not args.allow_local_artifacts,
    )

    for finding in ctx.findings:
        print(f"{finding.level} {finding.message}", file=sys.stderr)

    error_count = sum(1 for finding in ctx.findings if finding.level == "ERROR")
    warning_count = sum(1 for finding in ctx.findings if finding.level == "WARN")
    if error_count:
        print(
            f"FAIL beta preflight: {error_count} error(s), {warning_count} warning(s), {ctx.checks} check(s).",
            file=sys.stderr,
        )
        return 1

    print(f"PASS beta preflight: {ctx.checks} check(s), {warning_count} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
