"""Core scanning engine for governance-scan.

Analyzes a repository for AI governance posture across 6 dimensions:
CLAUDE.md quality, hooks, test infrastructure, enforcement rules, CI integration,
and anti-patterns.

All analysis is local -- no network calls, no API dependencies.
"""

import json
import os
import re
import subprocess
from pathlib import Path

from .scoring import calculate_scores, grade

# Directories to skip during file scanning
_SKIP_DIRS = {
    ".git", "node_modules", ".next", "dist", "build", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".eggs",
    "egg-info", ".ruff_cache",
}

_CODE_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".swift", ".cs", ".cpp", ".c", ".h",
}


def _should_skip(path: Path) -> bool:
    return any(part in _SKIP_DIRS for part in path.parts)


def scan_claude_md(repo: Path) -> dict:
    """Scan for CLAUDE.md / .cursorrules and analyze structure."""
    results = {"files": [], "total_lines": 0, "total_rules": 0, "structured": False}

    candidates = ["CLAUDE.md", ".claude/CLAUDE.md", ".cursorrules", ".github/copilot-instructions.md"]
    for name in candidates:
        path = repo / name
        if path.exists():
            try:
                text = path.read_text(errors="ignore")
            except Exception:
                continue
            lines = text.splitlines()
            results["files"].append({
                "path": name,
                "lines": len(lines),
            })
            results["total_lines"] += len(lines)

            # Structured if 3+ headings
            headings = [l for l in lines if l.startswith("#")]
            if len(headings) >= 3:
                results["structured"] = True

            # Count enforcement rules
            rule_pattern = re.compile(
                r'^\s*[-*]\s+\*?\*?(Must|Never|Always|Do not|Prefer|Should|Avoid)',
                re.IGNORECASE,
            )
            results["total_rules"] += sum(1 for l in lines if rule_pattern.match(l))

    return results


def scan_hooks(repo: Path) -> dict:
    """Check for pre-commit hooks, Claude hooks, husky, etc."""
    results = {"hooks": [], "l5_count": 0}

    # Claude Code settings
    for name in [".claude/settings.json", ".claude/settings.local.json"]:
        path = repo / name
        if path.exists():
            try:
                data = json.loads(path.read_text())
                hooks = data.get("hooks", {})
                for hook_type, hook_list in hooks.items():
                    if isinstance(hook_list, list):
                        for hook in hook_list:
                            results["hooks"].append({
                                "type": hook_type,
                                "matcher": hook.get("matcher", ""),
                                "source": name,
                            })
                            results["l5_count"] += 1
            except (json.JSONDecodeError, OSError):
                pass

    # Git hooks
    pre_commit = repo / ".git" / "hooks" / "pre-commit"
    if pre_commit.exists() and os.access(pre_commit, os.X_OK):
        results["hooks"].append({
            "type": "pre-commit",
            "matcher": "git",
            "source": ".git/hooks/pre-commit",
        })
        results["l5_count"] += 1

    # Husky
    husky_dir = repo / ".husky"
    if husky_dir.exists() and husky_dir.is_dir():
        for f in husky_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                results["hooks"].append({
                    "type": f.name,
                    "matcher": "husky",
                    "source": f".husky/{f.name}",
                })
                results["l5_count"] += 1

    # pre-commit-config.yaml
    if (repo / ".pre-commit-config.yaml").exists():
        results["hooks"].append({
            "type": "pre-commit-config",
            "matcher": "pre-commit framework",
            "source": ".pre-commit-config.yaml",
        })
        results["l5_count"] += 1

    # lefthook
    if (repo / "lefthook.yml").exists() or (repo / ".lefthook.yml").exists():
        results["hooks"].append({
            "type": "lefthook",
            "matcher": "lefthook",
            "source": "lefthook.yml",
        })
        results["l5_count"] += 1

    return results


def scan_tests(repo: Path) -> dict:
    """Count test files and estimate coverage."""
    test_dirs = ["tests", "test", "__tests__", "spec"]
    results = {"test_files": 0, "test_dirs_found": [], "source_files": 0}

    seen = set()

    # Count test files in test directories
    for td in test_dirs:
        test_path = repo / td
        if test_path.exists():
            results["test_dirs_found"].append(td)
            for f in test_path.rglob("*"):
                if f.is_file() and f.suffix in _CODE_EXTENSIONS and not _should_skip(f):
                    seen.add(f)
                    results["test_files"] += 1

    # Test files scattered in codebase
    test_patterns = ["test_*.py", "*_test.py", "*.spec.*", "*.test.*"]
    for pattern in test_patterns:
        for f in repo.rglob(pattern):
            if f.is_file() and f not in seen and not _should_skip(f):
                seen.add(f)
                results["test_files"] += 1

    # Node-style single-entrypoint test files (e.g. src/test.ts)
    for f in repo.rglob("test.*"):
        if (f.is_file() and f.stem == "test" and f.suffix in _CODE_EXTENSIONS
                and f not in seen and not _should_skip(f)):
            seen.add(f)
            results["test_files"] += 1

    # Count source files
    for f in repo.rglob("*"):
        if (f.is_file() and f.suffix in _CODE_EXTENSIONS
                and f not in seen and not _should_skip(f)):
            results["source_files"] += 1

    return results


def scan_cicd(repo: Path) -> dict:
    """Check for CI/CD configuration."""
    results = {"configs": [], "has_ci": False}

    checks = [
        (".github/workflows", "GitHub Actions"),
        (".gitlab-ci.yml", "GitLab CI"),
        ("Jenkinsfile", "Jenkins"),
        (".circleci", "CircleCI"),
        (".travis.yml", "Travis CI"),
        ("Makefile", "Makefile"),
        ("Dockerfile", "Docker"),
        ("docker-compose.yml", "Docker Compose"),
        ("docker-compose.yaml", "Docker Compose"),
    ]

    for path_str, name in checks:
        check_path = repo / path_str
        if check_path.exists():
            if check_path.is_dir():
                files = [f for f in check_path.iterdir() if f.is_file()]
                results["configs"].append({"name": name, "path": path_str, "files": len(files)})
            else:
                results["configs"].append({"name": name, "path": path_str})
            results["has_ci"] = True

    # npm scripts
    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            ci_scripts = [k for k in scripts if k in ("test", "lint", "build", "ci", "check", "typecheck", "type-check")]
            if ci_scripts:
                results["configs"].append({"name": "npm scripts", "path": "package.json", "scripts": ci_scripts})
        except (json.JSONDecodeError, OSError):
            pass

    return results


def scan_agent_config(repo: Path) -> dict:
    """Check for AI agent configuration files."""
    results = {"files": [], "maturity": 0}

    checks = [
        ("AGENTS.md", "Agent roster"),
        ("data/agents", "Agent data directory"),
        ("data/roles", "Role definitions"),
        (".claude/settings.json", "Claude settings"),
        (".claude/settings.local.json", "Claude local settings"),
        ("scripts/agents", "Agent scripts"),
    ]

    for path_str, name in checks:
        if (repo / path_str).exists():
            results["files"].append({"path": path_str, "name": name})
            results["maturity"] += 1

    return results


def scan_anti_patterns(repo: Path) -> dict:
    """Scan for common anti-patterns (secrets, TODOs, dead code)."""
    results = {"secrets": 0, "todos": 0, "dead_code": 0}

    scannable = {".py", ".ts", ".js", ".tsx", ".jsx", ".md", ".yaml", ".yml", ".json", ".env", ".toml", ".cfg"}
    secret_patterns = [
        re.compile(r'(?i)(api_key|secret|password|token)\s*=\s*["\'][^"\']{8,}'),
        re.compile(r'sk-[a-zA-Z0-9]{20,}'),
        re.compile(r'-----BEGIN (RSA |EC )?PRIVATE KEY-----'),
    ]

    file_count = 0
    max_files = 5000  # Safety limit

    for f in repo.rglob("*"):
        if file_count >= max_files:
            break
        if not f.is_file() or f.suffix not in scannable or _should_skip(f):
            continue
        file_count += 1

        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue

        # Skip .env files for secret scanning (they are supposed to have secrets)
        if f.suffix != ".env":
            for pattern in secret_patterns:
                if pattern.search(text):
                    results["secrets"] += 1
                    break

        results["todos"] += len(re.findall(r'(?i)\b(TODO|FIXME|HACK|XXX)\b', text))
        results["dead_code"] += len(re.findall(r'(?i)\b(DEPRECATED|DEAD CODE|UNUSED|REMOVE ME)\b', text))

    return results


def generate_recommendations(claude_md: dict, hooks: dict, tests: dict,
                             cicd: dict, anti_patterns: dict) -> list:
    """Generate top recommendations based on scan results."""
    recs = []

    if claude_md["total_lines"] == 0:
        recs.append("Add a CLAUDE.md with project structure, key rules, and enforcement requirements")
    elif not claude_md["structured"]:
        recs.append("Structure your CLAUDE.md with clear headings for rules, conventions, and constraints")
    elif claude_md["total_lines"] > 500:
        recs.append("Trim CLAUDE.md to <200 lines -- move reference material to separate files")

    if hooks["l5_count"] == 0:
        recs.append("Add pre-commit hooks or Claude Code hooks to enforce critical rules automatically")

    if tests["test_files"] == 0:
        recs.append("Create a test suite -- start with integration tests for the 3 most critical code paths")
    elif tests["source_files"] > 0 and tests["test_files"] / tests["source_files"] < 0.1:
        recs.append("Increase test coverage -- aim for at least 1 test file per 5 source files")

    if not cicd["has_ci"]:
        recs.append("Set up CI/CD with automated testing, linting, and type checking")

    if anti_patterns["secrets"] > 0:
        recs.append("Remove hardcoded secrets from source code -- use environment variables instead")

    if anti_patterns["todos"] > 30:
        recs.append("Convert TODO/FIXME markers to tracked issues -- you have %d untracked items" % anti_patterns["todos"])

    return recs[:3]


def scan_repo(path: str | Path) -> dict:
    """Run a full governance scan on a repository.

    Args:
        path: Path to the repository root.

    Returns:
        Dict with keys: score, grade, categories, recommendations, cta, raw.
    """
    repo = Path(path).resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Repository not found: {repo}")

    # Run all category scans
    claude_md = scan_claude_md(repo)
    hooks = scan_hooks(repo)
    tests = scan_tests(repo)
    cicd = scan_cicd(repo)
    agent_config = scan_agent_config(repo)
    anti_patterns = scan_anti_patterns(repo)

    # Calculate scores
    scores = calculate_scores(claude_md, hooks, tests, cicd, agent_config, anti_patterns)

    # Category breakdown
    categories = {
        "claude_md": {
            "name": "CLAUDE.md Quality",
            "score": min(100, (15 if claude_md["total_lines"] > 0 else 0)
                         + (10 if claude_md["structured"] else 0)
                         + min(25, claude_md["total_rules"] * 5)),
            "details": {
                "files_found": len(claude_md["files"]),
                "total_lines": claude_md["total_lines"],
                "structured": claude_md["structured"],
                "rule_count": claude_md["total_rules"],
            },
        },
        "hooks": {
            "name": "Enforcement Hooks",
            "score": min(100, hooks["l5_count"] * 25),
            "details": {
                "hook_count": hooks["l5_count"],
                "hooks": [h["source"] for h in hooks["hooks"]],
            },
        },
        "tests": {
            "name": "Test Infrastructure",
            "score": min(100, tests["test_files"] * 5),
            "details": {
                "test_files": tests["test_files"],
                "source_files": tests["source_files"],
                "test_dirs": tests["test_dirs_found"],
            },
        },
        "ci": {
            "name": "CI Integration",
            "score": 100 if cicd["has_ci"] else 0,
            "details": {
                "has_ci": cicd["has_ci"],
                "configs": [c["name"] for c in cicd["configs"]],
            },
        },
        "enforcement_rules": {
            "name": "Enforcement Rules",
            "score": min(100, claude_md["total_rules"] * 10),
            "details": {
                "rule_count": claude_md["total_rules"],
            },
        },
        "anti_patterns": {
            "name": "Anti-Pattern Score",
            "score": max(0, 100 - anti_patterns["secrets"] * 20 - min(50, anti_patterns["todos"])),
            "details": {
                "secrets_found": anti_patterns["secrets"],
                "todo_count": anti_patterns["todos"],
                "dead_code_markers": anti_patterns["dead_code"],
            },
        },
    }

    recommendations = generate_recommendations(claude_md, hooks, tests, cicd, anti_patterns)

    cta = {
        "assessment": "Full assessment with EU AI Act compliance mapping: https://walseth.ai/audit",
        "enterprise": "Enterprise governance: https://walseth.ai/pricing",
    }

    return {
        "repo": str(repo),
        "score": scores["overall"],
        "grade": grade(scores["overall"]),
        "scores": scores,
        "categories": categories,
        "recommendations": recommendations,
        "cta": cta,
        "raw": {
            "claude_md": claude_md,
            "hooks": hooks,
            "tests": tests,
            "cicd": cicd,
            "agent_config": agent_config,
            "anti_patterns": anti_patterns,
        },
    }
