# governance-scan

[![Governance Score](https://walseth.ai/api/badge/douglasrw/governance-scan)](https://walseth.ai/scan?repo=douglasrw/governance-scan)
[![PyPI](https://img.shields.io/pypi/v/governance-scan.svg)](https://pypi.org/project/governance-scan/)
[![Tests](https://github.com/douglasrw/governance-scan/actions/workflows/test.yml/badge.svg)](https://github.com/douglasrw/governance-scan/actions/workflows/test.yml)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-Governance%20Scan-blue?logo=github)](https://github.com/marketplace/actions/governance-scan)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

AI governance scanner for codebases. Scores enforcement maturity, context hygiene, and automation readiness.

Works on **any** git repository. No API keys, no accounts, no network calls. Pure local static analysis.

The output category name `CLAUDE.md Quality` is kept for compatibility, but the scanner also credits other AI guidance surfaces such as `AGENTS.md`, `GEMINI.md`, Copilot/Cursor/Claude instruction files, and scoped instruction directories.

## Quick Start

### Install via pip

```bash
pip install governance-scan
```

Or install from GitHub:

```bash
pip install git+https://github.com/douglasrw/governance-scan.git
```

### Run a scan

```bash
governance-scan /path/to/your/repo
```

### Example Output

```
  governance-scan  v1.0.0
  /path/to/your/repo

  Score: 45/100  Grade: C  [#########-----------]

  Breakdown:
    Enforcement           35/100 D  [#######--------]
    Hygiene               55/100 C  [########-------]
    Automation            40/100 C  [########-------]

  Categories:
    CLAUDE.md Quality          25/100
    Enforcement Hooks           0/100
    Test Infrastructure        50/100
    CI Integration            100/100
    Enforcement Rules          15/100
    Anti-Pattern Score         80/100

  Top Recommendations:
    1. Add pre-commit hooks or Claude Code hooks to enforce critical rules automatically
    2. Structure your CLAUDE.md with clear headings for rules, conventions, and constraints
    3. Increase test coverage -- aim for at least 1 test file per 5 source files

  ---
  Full assessment with EU AI Act compliance mapping: https://walseth.ai/audit
  Enterprise governance: https://walseth.ai/pricing
```

### JSON Output

```bash
governance-scan --json /path/to/your/repo
```

On success, `--json` writes the full scan payload to `stdout`, including:

- `repo`
- `score`
- `grade`
- `scores`
- `categories`
- `recommendations`
- `cta`
- `raw`

This is the same data used by the GitHub Action outputs and is suitable for CI pipelines.

### JSON Error Contract

When `--json` is enabled, expected CLI failures also return JSON on `stdout` and leave `stderr` empty:

```json
{
  "error": true,
  "code": "REPO_NOT_FOUND",
  "message": "Repository not found: /path/to/repo"
}
```

Current JSON error codes:

- `MISSING_REPO_PATH`
- `INVALID_REPO_ROOT`
- `REPO_NOT_FOUND`
- `PERMISSION_DENIED`

In JSON mode these cases exit with status `1`. In human-readable mode, errors are printed to `stderr`; a missing required path without `--json` uses `argparse`'s standard exit status `2`.

### Options

| Flag | Description |
|------|-------------|
| `--json` | Output machine-readable JSON |
| `--no-color` | Disable colorized terminal output |
| `--version` | Show version |

## GitHub Action

Add governance scanning to your pull requests:

```yaml
# .github/workflows/governance.yml
name: Governance Scan
on: [pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: douglasrw/governance-scan@v1
```

The action posts a PR comment with the scan results, including score, grade, category breakdown, and recommendations.

### Action Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `path` | `.` | Path to scan (relative to workspace root) |
| `comment` | `true` | Post results as a PR comment |

### Action Outputs

| Output | Description |
|--------|-------------|
| `score` | Overall governance score (0-100) |
| `grade` | Letter grade (A-F) |
| `json` | Full scan results as JSON |

## What It Scans

| Category | What it checks |
|----------|---------------|
| **CLAUDE.md Quality** | Presence, structure, and rule density across `CLAUDE.md`, `.claude/CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`, `AGENTS.md`, `GEMINI.md`, `.gemini/GEMINI.md`, `.claude/commands/**`, `.cursor/rules/**`, and `.github/instructions/**/*.instructions.md` |
| **Enforcement Hooks** | Pre-commit hooks, Claude Code hooks, Husky, pre-commit framework, lefthook |
| **Test Infrastructure** | Test files, test directories, source-to-test ratio |
| **CI Integration** | A binary CI signal based on detected GitHub Actions workflow files, GitLab CI, Jenkins, CircleCI, Travis CI, `Makefile`, `Dockerfile`, Docker Compose files, or qualifying npm scripts in `package.json` (`test`, `lint`, `build`, `ci`, `check`, `typecheck`, `type-check`) |
| **Enforcement Rules** | Must/Never/Always/Do not/Prefer/Should/Avoid rule markers across the structural guidance files counted in the `CLAUDE.md Quality` category |
| **Anti-Patterns** | Hardcoded secrets, TODO/FIXME debt, dead code markers |

Notes:

- An empty `.github/workflows/` directory does not count as CI; the directory must contain at least one `.yml` or `.yaml` workflow file.
- Agent-config maturity and recommendations also look at surfaces such as `.claude/settings.json`, `.claude/settings.local.json`, `data/agents`, `data/roles`, and `scripts/agents`.

## Scoring

The overall score (0-100) is a weighted composite:

- **Enforcement Maturity** (40%): Hooks, tests, rules, structure, CI, secret hygiene
- **Context Hygiene** (30%): CLAUDE.md presence/quality, TODO debt
- **Automation Readiness** (30%): CI, agent config, test coverage, hooks

Grades: A (80+), B (60-79), C (40-59), D (20-39), F (0-19).

## Full Assessment

This tool provides a quick local scan. For a comprehensive assessment including EU AI Act compliance mapping, enforcement ladder analysis, and actionable remediation plans:

- [Request a full assessment](https://walseth.ai/audit)
- [Enterprise governance platform](https://walseth.ai/pricing)

## Development

```bash
git clone https://github.com/douglasrw/governance-scan.git
cd governance-scan
pip install -e .
pip install pytest
pytest tests/ -v
```

## License

MIT
