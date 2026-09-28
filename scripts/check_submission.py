#!/usr/bin/env python3
"""Pre-submission lint (§5.8).

    python scripts/check_submission.py

It is a lint, not a grader. Every check here corresponds to an automatic deduction in §5.3 —
the mechanical failures that cost marks regardless of how good the engineering is. A clean run
does not guarantee a good mark; a dirty run nearly guarantees a bad one.

With --ci it runs only the checks that make sense without a full working tree (no git history
scan of unpushed branches, no reliance on local tooling).

Exit code 0 = clean, 1 = at least one ERROR. Warnings never fail the run, because some of them
are judgement calls rather than rules.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Deliberately narrow, high-confidence patterns. A loose regex that flags every "password"
# trains people to ignore the tool, which is worse than not having it.
SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"gsk_[A-Za-z0-9]{40,}", "Groq API key"),
    (r"sk-[A-Za-z0-9]{32,}", "OpenAI-style API key"),
    (r"ghp_[A-Za-z0-9]{36,}", "GitHub personal access token"),
    (r"gho_[A-Za-z0-9]{36,}", "GitHub OAuth token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
]

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".md", ".sh",
    ".conf", ".template", ".toml", ".ini", ".cfg", ".txt", ".html", ".css", ".env",
    "",  # extensionless files such as Dockerfile
}

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov", ".idea", ".vscode",
}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passes: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self, msg: str) -> None:
        self.passes.append(msg)


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
    except FileNotFoundError:  # pragma: no cover
        return ""


def tracked_files() -> list[Path]:
    out = git("ls-files")
    return [ROOT / line for line in out.splitlines() if line]


def readable_text_files() -> list[Path]:
    files = []
    for path in tracked_files():
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


# --- checks -------------------------------------------------------------------


def check_secrets_in_worktree(report: Report) -> None:
    """§5.3: a key, token or password anywhere in Git — -20 plus rotation."""
    hits: list[str] = []
    for path in readable_text_files():
        # .env.example is expected to contain the NAMES of secrets, not values.
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern, label in SECRET_PATTERNS:
            for match in re.finditer(pattern, content):
                line_no = content[: match.start()].count("\n") + 1
                rel = path.relative_to(ROOT)
                hits.append(f"{rel}:{line_no} looks like a {label}")

    if hits:
        for hit in hits:
            report.error(f"SECRET in a tracked file: {hit}")
    else:
        report.ok(f"no secret material in {len(readable_text_files())} tracked text files")


def check_secrets_in_history(report: Report, ci: bool) -> None:
    """A secret removed from HEAD but present in history still costs the marks."""
    if ci:
        report.ok("history scan skipped (--ci)")
        return

    combined = "|".join(p for p, _ in SECRET_PATTERNS)
    found = git("log", "--all", "-p", "--no-color", f"-G{combined}", "--name-only", "--format=%H")
    if found.strip():
        commits = [line for line in found.splitlines() if re.fullmatch(r"[0-9a-f]{40}", line)]
        report.error(
            f"secret-like content appears in git history ({len(commits)} commit(s)). "
            "Rotate the credential and write an incident note (§5.3)."
        )
    else:
        report.ok("git history contains no secret-like patterns")


def check_env_not_tracked(report: Report) -> None:
    tracked = set(git("ls-files").splitlines())
    offenders = [f for f in tracked if Path(f).name == ".env" or f.endswith("/.env")]
    if offenders:
        report.error(f".env is tracked by git: {offenders} (-20)")
    else:
        report.ok(".env is not tracked")

    if ".env.example" in tracked:
        report.ok(".env.example is committed")
    else:
        report.error(".env.example must be committed so a stranger knows what to set")

    gitignore = ROOT / ".gitignore"
    if gitignore.exists() and re.search(r"^\.env$", gitignore.read_text(), re.M):
        report.ok(".env is gitignored")
    else:
        report.error(".gitignore must ignore .env")


def check_env_example_has_no_values(report: Report) -> None:
    """A placeholder file with a real value in it is the most common way this goes wrong."""
    example = ROOT / ".env.example"
    if not example.exists():
        return
    suspicious = []
    for line_no, line in enumerate(example.read_text().splitlines(), 1):
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if not value:
            continue
        if re.search(r"(KEY|TOKEN|SECRET|PASSWORD)$", key.strip().upper()) and value not in {
            "change-me-locally",
            "changeme",
            "",
        }:
            suspicious.append(f"line {line_no}: {key.strip()} has a non-placeholder value")
    for item in suspicious:
        report.error(f".env.example {item} — placeholders only")
    if not suspicious:
        report.ok(".env.example contains placeholders only")


def check_image_pinning(report: Report) -> None:
    """§5.3: an unpinned base image, or postgres/redis/node without a tag — -8."""
    targets = list(ROOT.glob("**/Dockerfile")) + list(ROOT.glob("compose*.yaml"))
    unpinned: list[str] = []
    for path in targets:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            match = re.search(r"(?:^FROM|image:)\s+([^\s]+)", stripped)
            if not match:
                continue
            ref = match.group(1)
            if ref.startswith("${"):  # resolved from the environment at deploy time
                continue
            has_tag = ":" in ref.split("/")[-1]
            has_digest = "@sha256:" in ref
            if not (has_tag or has_digest):
                unpinned.append(f"{path.relative_to(ROOT)}:{line_no} {ref} has no tag")
    if unpinned:
        for item in unpinned:
            report.error(f"UNPINNED image: {item} (-8)")
    else:
        report.ok("every image reference carries a tag or digest")


def check_no_latest_deployed(report: Report) -> None:
    """§5.3: deploying :latest anywhere — -8. Comments are not deployments."""
    offenders: list[str] = []
    for path in [*ROOT.glob("compose*.yaml"), *ROOT.glob("k8s/**/*.yaml"), *ROOT.glob(".github/workflows/*.yml")]:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Pushing :latest is permitted; deploying it is not. `image:` in a manifest or a
            # compose file is a deployment.
            if re.search(r"^\s*image:\s*\S+:latest\b", line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    if offenders:
        for item in offenders:
            report.error(f"deploys :latest at {item} (-8)")
    else:
        report.ok("nothing deploys :latest")


def check_localhost_not_used_between_services(report: Report) -> None:
    """§5.3: localhost for service-to-service communication — -8.

    Healthchecks and probes legitimately target 127.0.0.1, because they run inside the
    container they are checking. Only cross-service configuration is a problem.
    """
    offenders: list[str] = []
    for path in [*ROOT.glob("compose*.yaml"), *ROOT.glob("k8s/**/*.yaml")]:
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        lines = path.read_text().splitlines()
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or not re.search(r"localhost|127\.0\.0\.1", stripped):
                continue
            # Allow it where 127.0.0.1 is correct: a healthcheck or probe runs INSIDE the
            # container it is testing, so it must target the loopback and not a service name.
            # The window is generous because a compose healthcheck written as a YAML list puts
            # the `healthcheck:` key a dozen lines above the URL.
            window = "\n".join(lines[max(0, line_no - 14) : line_no + 2]).lower()
            if any(
                k in window
                for k in ("healthcheck", "probe", "httpget", "ports:", "cors", "test:", "- cmd")
            ):
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{line_no} {stripped[:70]}")
    if offenders:
        for item in offenders:
            report.error(f"localhost used for service-to-service config: {item} (-8)")
    else:
        report.ok("no localhost used between services")


def check_prod_compose_rules(report: Report) -> None:
    prod = ROOT / "compose.prod.yaml"
    if not prod.exists():
        report.error("compose.prod.yaml is missing")
        return

    lines = [line for line in prod.read_text().splitlines() if not line.strip().startswith("#")]
    body = "\n".join(lines)

    if re.search(r"^\s*build:", body, re.M):
        report.error("compose.prod.yaml contains a build: key — it must deploy, not build")
    else:
        report.ok("compose.prod.yaml has no build: key")

    if "${IMAGE_TAG" in body:
        report.ok("compose.prod.yaml references ${IMAGE_TAG}")
    else:
        report.error("compose.prod.yaml must reference ${IMAGE_TAG}")

    # Only the frontend may publish a port.
    for service in ("database", "cache"):
        block = re.search(rf"^  {service}:\n(.*?)(?=^  \S|\Z)", body, re.M | re.S)
        if block and re.search(r"^\s*ports:", block.group(1), re.M):
            report.error(f"compose.prod.yaml publishes a port on {service} (-8)")
    report.ok("compose.prod.yaml publishes no database or cache port")


def check_k8s_rules(report: Report) -> None:
    k8s = ROOT / "k8s"
    if not k8s.exists():
        report.warn("k8s/ does not exist yet")
        return

    manifests = list(k8s.glob("**/*.yaml"))
    joined = "\n".join(
        p.read_text() for p in manifests if not any(part in SKIP_DIRS for part in p.parts)
    )

    # §5.3: PostgreSQL as a Deployment with no PVC — -8.
    if re.search(r"kind:\s*StatefulSet", joined):
        report.ok("Postgres is a StatefulSet")
    else:
        report.error("Postgres must be a StatefulSet with volumeClaimTemplates (-8)")

    # §5.3: a NodePort/LoadBalancer Service on the database — -8.
    for match in re.finditer(r"kind:\s*Service(.*?)(?=kind:|\Z)", joined, re.S):
        block = match.group(1)
        if re.search(r"type:\s*(NodePort|LoadBalancer)", block) and re.search(
            r"postgres|database|redis|cache", block, re.I
        ):
            report.error("a database or cache Service is NodePort/LoadBalancer (-8)")
            break
    else:
        report.ok("no NodePort/LoadBalancer on the database or cache")

    # Base64 is encoding, not encryption: a real secret in a manifest is -15.
    for path in manifests:
        text = path.read_text()
        if not re.search(r"kind:\s*Secret", text):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            match = re.match(r"\s*([\w.\-]+):\s*([A-Za-z0-9+/=]{16,})\s*$", line)
            if not match or match.group(1) in {"apiVersion", "kind", "name", "namespace", "type"}:
                continue
            import base64

            try:
                decoded = base64.b64decode(match.group(2), validate=True).decode(errors="ignore")
            except Exception:
                continue
            for pattern, label in SECRET_PATTERNS:
                if re.search(pattern, decoded):
                    report.error(
                        f"{path.relative_to(ROOT)}:{line_no} contains a base64-encoded "
                        f"{label} — base64 is encoding, not encryption (-15)"
                    )
    report.ok("committed Secret manifests carry placeholders only")

    if re.search(r"resources:\s*\n\s*(requests|limits):", joined):
        report.ok("resource requests/limits are present")
    else:
        report.error("every container needs resources.requests — without it the HPA has no denominator")


def check_workflow_gating(report: Report) -> None:
    """§5.3: a publishing or deploying job not gated by needs: — -8."""
    workflows = list((ROOT / ".github" / "workflows").glob("*.yml"))
    if not workflows:
        report.warn(".github/workflows/ is empty")
        return

    for path in workflows:
        text = path.read_text()
        if "permissions:" in text:
            report.ok(f"{path.name} declares a permissions: block")
        else:
            report.error(f"{path.name} has no permissions: block — the default is too broad")

        # Any job that pushes or deploys must declare needs:.
        for match in re.finditer(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S):
            name, body = match.group(1), match.group(2)
            publishes = bool(
                re.search(r"push:\s*true|docker push|kubectl apply|rollout status", body)
            )
            if publishes and "needs:" not in body:
                report.error(f"{path.name}: job '{name}' publishes or deploys with no needs: (-8)")


def check_commit_hygiene(report: Report, ci: bool) -> None:
    if ci:
        return

    count = git("rev-list", "--count", "HEAD")
    total = int(count) if count.isdigit() else 0
    if total >= 35:
        report.ok(f"{total} commits (floor is 35)")
    else:
        report.warn(f"only {total} commits; the rubric asks for >= 35")

    subjects = git("log", "--format=%s", "-n", "200").splitlines()
    conventional = re.compile(r"^(feat|fix|docs|test|chore|refactor|build|ci|perf|style)(\(.+\))?!?: ")
    bad = [s for s in subjects if not conventional.match(s)]
    if bad:
        report.warn(f"{len(bad)} commit subject(s) are not conventional, e.g. {bad[0]!r}")
    else:
        report.ok(f"all {len(subjects)} commit subjects use conventional prefixes")

    shortlog = git("shortlog", "-sn", "--all")
    if shortlog:
        report.ok(f"git shortlog -sn:\n        " + "\n        ".join(shortlog.splitlines()))


def check_required_files(report: Report) -> None:
    required = [
        "README.md",
        "compose.yaml",
        "compose.prod.yaml",
        ".env.example",
        ".gitignore",
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "backend/.dockerignore",
        "frontend/.dockerignore",
        ".github/workflows/ci.yml",
        ".github/workflows/cd.yml",
        "docs/RUNBOOK.md",
        "docs/ENGINEERING-NOTES.md",
        "docs/AI-USAGE.md",
        "docs/adr/0001-provider-interface.md",
        "docs/adr/0002-frontend-runtime-config.md",
        "docs/adr/0003-deploy-by-sha.md",
        "docs/adr/0004-pii-and-data-governance.md",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    if missing:
        for f in missing:
            report.warn(f"missing deliverable: {f}")
    else:
        report.ok(f"all {len(required)} required files present")


def check_dependency_lock_in_sync(report: Report) -> None:
    """pyproject.toml is the source of truth for direct dependencies; requirements.txt is the
    lock the image installs. If a direct dependency is missing from the lock, the image will not
    contain it and the failure appears at runtime."""
    pyproject = ROOT / "backend" / "pyproject.toml"
    lock = ROOT / "backend" / "requirements.txt"
    if not (pyproject.exists() and lock.exists()):
        return

    # Only the [project] dependencies array. The dev extras under
    # [project.optional-dependencies] are test tooling, deliberately absent from the runtime
    # lock the image installs — counting them would report a permanent false failure.
    text = pyproject.read_text()
    # Terminated by a bracket in column 0, not the first bracket found: an extras marker such as
    # "uvicorn[standard]==0.34.0" contains a ] that would otherwise truncate the list.
    main_block = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", text, re.M | re.S)
    if not main_block:
        return
    declared = set(re.findall(r'"([A-Za-z0-9_.\-]+)[\[>=<~!]', main_block.group(1)))
    locked = {
        m.lower().replace("_", "-")
        for m in re.findall(r"^([A-Za-z0-9_.\-]+)==", lock.read_text(), re.M)
    }
    missing = {d for d in declared if d.lower().replace("_", "-") not in locked}
    if missing:
        report.error(
            f"requirements.txt is out of sync with pyproject.toml, missing: {sorted(missing)}. "
            "Run: uv pip compile pyproject.toml -o requirements.txt"
        )
    else:
        report.ok(f"requirements.txt locks all {len(declared)} direct dependencies")


def check_readme_claims(report: Report) -> None:
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    text = readme.read_text()
    for needle, label in [
        ("docker compose up", "one-command quickstart"),
        ("```mermaid", "Mermaid architecture diagram"),
    ]:
        if needle in text:
            report.ok(f"README has a {label}")
        else:
            report.warn(f"README is missing a {label}")


# --- main ---------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci", action="store_true", help="skip checks that need local history")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    report = Report()

    check_secrets_in_worktree(report)
    check_secrets_in_history(report, args.ci)
    check_env_not_tracked(report)
    check_env_example_has_no_values(report)
    check_image_pinning(report)
    check_no_latest_deployed(report)
    check_localhost_not_used_between_services(report)
    check_prod_compose_rules(report)
    check_k8s_rules(report)
    check_workflow_gating(report)
    check_dependency_lock_in_sync(report)
    check_required_files(report)
    check_readme_claims(report)
    check_commit_hygiene(report, args.ci)

    if args.json:
        print(json.dumps({
            "errors": report.errors,
            "warnings": report.warnings,
            "passes": report.passes,
        }, indent=2))
        return 1 if report.errors else 0

    print("CivicPulse submission check")
    print("=" * 70)
    for msg in report.passes:
        print(f"  ok      {msg}")
    for msg in report.warnings:
        print(f"  WARN    {msg}")
    for msg in report.errors:
        print(f"  ERROR   {msg}")
    print("=" * 70)
    print(f"{len(report.passes)} ok, {len(report.warnings)} warning(s), {len(report.errors)} error(s)")

    if report.errors:
        print("\nFix the errors above before submitting: each maps to an automatic deduction in §5.3.")
        return 1
    print("\nNo automatic-deduction triggers found. This is a lint, not a grade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
