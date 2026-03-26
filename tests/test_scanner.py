"""Tests for the governance-scan scanner module."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from governance_scan.scanner import (
    generate_recommendations,
    scan_agent_config,
    scan_claude_md,
    scan_hooks,
    scan_tests,
    scan_cicd,
    scan_anti_patterns,
    scan_repo,
)
from governance_scan.scoring import grade, calculate_scores


@pytest.fixture
def empty_repo(tmp_path):
    """Create an empty git repo for testing."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    return tmp_path


@pytest.fixture
def rich_repo(tmp_path):
    """Create a repo with governance artifacts for testing."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)

    # CLAUDE.md
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "# Project Rules\n\n"
        "## Conventions\n\n"
        "## Constraints\n\n"
        "- Must use TypeScript for all new files\n"
        "- Never commit secrets\n"
        "- Always run tests before merging\n"
    )

    # Tests directory
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_example.py").write_text("def test_one(): pass\n")
    (tests_dir / "test_two.py").write_text("def test_two(): pass\n")

    # Source files
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hello')\n")
    (src_dir / "utils.py").write_text("# utility\n")

    # CI
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\n")

    # Makefile
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")

    return tmp_path


class TestGrade:
    def test_grade_a(self):
        assert grade(80) == "A"
        assert grade(100) == "A"

    def test_grade_b(self):
        assert grade(60) == "B"
        assert grade(79) == "B"

    def test_grade_c(self):
        assert grade(40) == "C"
        assert grade(59) == "C"

    def test_grade_d(self):
        assert grade(20) == "D"
        assert grade(39) == "D"

    def test_grade_f(self):
        assert grade(0) == "F"
        assert grade(19) == "F"


class TestScanClaudeMd:
    def test_no_claude_md(self, empty_repo):
        result = scan_claude_md(empty_repo)
        assert result["total_lines"] == 0
        assert result["total_rules"] == 0
        assert len(result["files"]) == 0

    def test_with_claude_md(self, rich_repo):
        result = scan_claude_md(rich_repo)
        assert result["total_lines"] > 0
        assert len(result["files"]) == 1
        assert result["structured"] is True
        assert result["total_rules"] == 3

    def test_agents_md_counted_as_guidance(self, tmp_path):
        """AGENTS.md alone gives governance guidance credit."""
        (tmp_path / "AGENTS.md").write_text(
            "# Agents\n\n"
            "## Dispatcher\n\n"
            "## Worker\n\n"
            "- Must follow the task packet\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] > 0
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == "AGENTS.md"
        assert result["structured"] is True
        assert result["total_rules"] == 1

    def test_agents_md_without_claude_md(self, tmp_path):
        """Repo with AGENTS.md but no CLAUDE.md still receives structural context credit."""
        (tmp_path / "AGENTS.md").write_text(
            "# Agent Instructions\n\nFollow the protocol.\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] > 0
        assert len(result["files"]) == 1

    def test_agents_md_combined_with_claude_md(self, tmp_path):
        """Both CLAUDE.md and AGENTS.md contribute to totals."""
        (tmp_path / "CLAUDE.md").write_text("# Rules\n\n## Style\n\n## Tests\n\n- Must lint\n")
        (tmp_path / "AGENTS.md").write_text("# Agents\n\n- Never skip hooks\n")
        result = scan_claude_md(tmp_path)
        assert len(result["files"]) == 2
        assert result["total_rules"] == 2

    def test_claude_commands_counted_as_guidance(self, tmp_path):
        """`.claude/commands/*` guidance files contribute to structural totals."""
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text(
            "# Review\n\n"
            "## Scope\n\n"
            "## Checks\n\n"
            "- Must review tests\n"
            "- Never ignore regressions\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] > 0
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == ".claude/commands/review.md"
        assert result["structured"] is True
        assert result["total_rules"] == 2

    def test_claude_commands_combined_with_other_guidance(self, tmp_path):
        """Claude commands add to CLAUDE.md and Cursor guidance totals."""
        (tmp_path / "CLAUDE.md").write_text("# Rules\n\n## Style\n\n## Tests\n\n- Must lint\n")
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text("- Never skip tests\n")
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "style.mdc").write_text("- Should prefer explicit types\n")
        result = scan_claude_md(tmp_path)
        assert len(result["files"]) == 3
        assert result["total_rules"] == 3

    def test_cursor_rules_dir_counted_as_guidance(self, tmp_path):
        """.cursor/rules directory files contribute governance guidance credit."""
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "style.mdc").write_text(
            "# Style Rules\n\n"
            "## Formatting\n\n"
            "## Naming\n\n"
            "- Must use camelCase for variables\n"
            "- Never use abbreviations\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] > 0
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == ".cursor/rules/style.mdc"
        assert result["structured"] is True
        assert result["total_rules"] == 2

    def test_cursor_rules_multiple_files(self, tmp_path):
        """Multiple files in .cursor/rules each contribute to totals."""
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "a.mdc").write_text("- Must lint\n")
        (rules_dir / "b.mdc").write_text("- Never skip tests\n")
        result = scan_claude_md(tmp_path)
        assert len(result["files"]) == 2
        assert result["total_rules"] == 2

    def test_cursor_rules_nested_files(self, tmp_path):
        """Nested files in .cursor/rules contribute to totals."""
        rules_dir = tmp_path / ".cursor" / "rules" / "backend"
        rules_dir.mkdir(parents=True)
        (rules_dir / "api.mdc").write_text("- Must validate inputs\n")
        result = scan_claude_md(tmp_path)
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == ".cursor/rules/backend/api.mdc"
        assert result["total_rules"] == 1

    def test_cursor_rules_combined_with_claude_md(self, tmp_path):
        """Both CLAUDE.md and .cursor/rules contribute to totals."""
        (tmp_path / "CLAUDE.md").write_text("# Rules\n\n## Style\n\n## Tests\n\n- Must lint\n")
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "extra.mdc").write_text("- Never use any\n")
        result = scan_claude_md(tmp_path)
        assert len(result["files"]) == 2
        assert result["total_rules"] == 2

    def test_cursor_rules_empty_dir_no_credit(self, tmp_path):
        """An empty .cursor/rules directory gives no credit."""
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] == 0
        assert len(result["files"]) == 0

    def test_github_instructions_counted_as_guidance(self, tmp_path):
        """.github/instructions/*.instructions.md contributes governance guidance credit."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "code-review.instructions.md").write_text(
            "# Code Review\n\n"
            "## Scope\n\n"
            "## Checks\n\n"
            "- Must review tests\n"
            "- Never ignore regressions\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] > 0
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == ".github/instructions/code-review.instructions.md"
        assert result["structured"] is True
        assert result["total_rules"] == 2

    def test_github_instructions_multiple_files(self, tmp_path):
        """Multiple top-level GitHub instruction files each contribute to totals."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "code-review.instructions.md").write_text("- Must review tests\n")
        (inst_dir / "testing.instructions.md").write_text("- Always run CI\n")
        result = scan_claude_md(tmp_path)
        assert len(result["files"]) == 2
        assert result["total_rules"] == 2

    def test_github_instructions_nested_dirs_counted(self, tmp_path):
        """Nested directories under .github/instructions/ are counted."""
        inst_dir = tmp_path / ".github" / "instructions"
        (inst_dir / "nested").mkdir(parents=True)
        (inst_dir / "nested" / "code-review.instructions.md").write_text("- Must review tests\n")
        result = scan_claude_md(tmp_path)
        assert result["total_lines"] > 0
        assert result["total_rules"] == 1
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == ".github/instructions/nested/code-review.instructions.md"

    def test_no_agents_md_no_claude_md(self, empty_repo):
        """Repo with neither AGENTS.md nor CLAUDE.md remains negative."""
        result = scan_claude_md(empty_repo)
        assert result["total_lines"] == 0
        assert len(result["files"]) == 0

    def test_numbered_rules_dot(self, tmp_path):
        """Numbered rules with dot notation (1. Must ...) are counted."""
        (tmp_path / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "1. Must use TypeScript\n"
            "2. Never commit secrets\n"
            "3. Always run tests\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_rules"] == 3

    def test_numbered_rules_paren(self, tmp_path):
        """Numbered rules with paren notation (1) Must ...) are counted."""
        (tmp_path / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "1) Must use TypeScript\n"
            "2) Avoid global state\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_rules"] == 2

    def test_mixed_bullet_and_numbered_rules(self, tmp_path):
        """Both bullet and numbered rules count toward total_rules."""
        (tmp_path / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Must use TypeScript\n"
            "1. Never commit secrets\n"
            "2) Always run tests\n"
            "* Should prefer immutable data\n"
        )
        result = scan_claude_md(tmp_path)
        assert result["total_rules"] == 4


class TestScanHooks:
    def test_no_hooks(self, empty_repo):
        result = scan_hooks(empty_repo)
        assert result["l5_count"] == 0

    def test_pre_commit_config(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1

    def test_pre_commit_config_yml(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".pre-commit-config.yml").write_text("repos: []\n")
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1
        sources = [h["source"] for h in result["hooks"]]
        assert ".pre-commit-config.yml" in sources

    def test_lefthook_yml(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n")
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1
        sources = [h["source"] for h in result["hooks"]]
        assert "lefthook.yml" in sources

    def test_lefthook_yaml(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "lefthook.yaml").write_text("pre-commit:\n  commands: {}\n")
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1
        sources = [h["source"] for h in result["hooks"]]
        assert "lefthook.yaml" in sources

    def test_dot_lefthook_yaml(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".lefthook.yaml").write_text("pre-commit:\n  commands: {}\n")
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1
        sources = [h["source"] for h in result["hooks"]]
        assert ".lefthook.yaml" in sources

    def test_claude_settings_hooks(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": {"PreToolUse": [{"matcher": "Write", "command": "echo check"}]}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1

    def test_malformed_hook_string_entries(self, tmp_path):
        """Hook lists containing bare strings instead of dicts are skipped."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": {"PreToolUse": ["Write", "Edit"]}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = scan_hooks(tmp_path)
        assert result["l5_count"] == 0
        assert result["hooks"] == []

    def test_malformed_hook_mixed_entries(self, tmp_path):
        """Valid dict entries are kept; non-dict entries are skipped."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": {"PreToolUse": [
            "Write",
            {"matcher": "Bash", "command": "echo ok"},
            42,
        ]}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = scan_hooks(tmp_path)
        assert result["l5_count"] == 1
        assert result["hooks"][0]["matcher"] == "Bash"

    def test_malformed_hooks_not_a_dict(self, tmp_path):
        """If 'hooks' value is not a dict, scan_hooks should not crash."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": "not-a-dict"}
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = scan_hooks(tmp_path)
        assert result["l5_count"] == 0

    def test_malformed_hook_null_entry(self, tmp_path):
        """Null entries in hook lists are skipped."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": {"PreToolUse": [None]}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = scan_hooks(tmp_path)
        assert result["l5_count"] == 0


class TestScanTests:
    def test_no_tests(self, empty_repo):
        result = scan_tests(empty_repo)
        assert result["test_files"] == 0

    def test_with_tests(self, rich_repo):
        result = scan_tests(rich_repo)
        assert result["test_files"] >= 2
        assert "tests" in result["test_dirs_found"]

    def test_node_style_src_test_ts(self, tmp_path):
        """A repo with src/test.ts should count one test file."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        src = tmp_path / "src"
        src.mkdir()
        (src / "scanner.ts").write_text("export const x = 1\n")
        (src / "test.ts").write_text('import test from "node:test"\n')
        result = scan_tests(tmp_path)
        assert result["test_files"] == 1
        assert result["source_files"] == 1

    def test_init_py_not_counted(self, tmp_path):
        """tests/__init__.py should not inflate test file count."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_foo.py").write_text("def test_foo(): pass\n")
        result = scan_tests(tmp_path)
        assert result["test_files"] == 1

    def test_nested_init_py_not_counted(self, tmp_path):
        """Nested __init__.py under test dirs should not count."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        tests_dir = tmp_path / "tests"
        sub = tests_dir / "sub"
        sub.mkdir(parents=True)
        (tests_dir / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("")
        (sub / "test_bar.py").write_text("def test_bar(): pass\n")
        result = scan_tests(tmp_path)
        assert result["test_files"] == 1

    def test_real_test_files_still_counted_with_init_py(self, tmp_path):
        """Real test modules are counted even when __init__.py exists."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_one.py").write_text("def test_one(): pass\n")
        (tests_dir / "test_two.py").write_text("def test_two(): pass\n")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1\n")
        result = scan_tests(tmp_path)
        assert result["test_files"] == 2
        assert result["source_files"] == 1

    def test_node_style_test_not_double_counted(self, tmp_path):
        """src/test.ts must not be double-counted if it also matches *.test.*."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        src = tmp_path / "src"
        src.mkdir()
        # test.test.ts matches both *.test.* and stem=="test" -- should count once
        (src / "test.test.ts").write_text("test\n")
        result = scan_tests(tmp_path)
        assert result["test_files"] == 1


class TestScanCicd:
    def test_no_ci(self, empty_repo):
        result = scan_cicd(empty_repo)
        assert result["has_ci"] is False

    def test_empty_github_workflows_dir_is_not_ci(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)

        result = scan_cicd(tmp_path)

        assert result["has_ci"] is False
        assert not any(c["name"] == "GitHub Actions" for c in result["configs"])

    def test_with_ci(self, rich_repo):
        result = scan_cicd(rich_repo)
        assert result["has_ci"] is True
        names = [c["name"] for c in result["configs"]]
        assert "GitHub Actions" in names


    def test_npm_type_check_script(self, tmp_path):
        """npm scripts with 'type-check' key should be recognized."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        pkg = {"scripts": {"type-check": "tsc --noEmit", "build": "tsc"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = scan_cicd(tmp_path)
        scripts = next(c["scripts"] for c in result["configs"] if c["name"] == "npm scripts")
        assert "type-check" in scripts
        assert "build" in scripts

    def test_npm_scripts_only_has_ci(self, tmp_path):
        """A repo with only npm scripts (no workflow files) should have has_ci=True."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        pkg = {"scripts": {"test": "jest", "lint": "eslint ."}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = scan_cicd(tmp_path)
        assert result["has_ci"] is True
        names = [c["name"] for c in result["configs"]]
        assert "npm scripts" in names

    def test_compose_yaml_detected(self, tmp_path):
        """compose.yaml (without docker- prefix) should be detected as Docker Compose."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "compose.yaml").write_text("services:\n  app:\n    build: .\n")
        result = scan_cicd(tmp_path)
        assert result["has_ci"] is True
        names = [c["name"] for c in result["configs"]]
        assert "Docker Compose" in names

    def test_compose_yml_detected(self, tmp_path):
        """compose.yml (without docker- prefix) should be detected as Docker Compose."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "compose.yml").write_text("services:\n  web:\n    image: nginx\n")
        result = scan_cicd(tmp_path)
        assert result["has_ci"] is True
        names = [c["name"] for c in result["configs"]]
        assert "Docker Compose" in names

    def test_npm_typecheck_and_type_check(self, tmp_path):
        """Both 'typecheck' and 'type-check' variants should be recognized."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        pkg = {"scripts": {"typecheck": "tsc", "type-check": "tsc --noEmit"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = scan_cicd(tmp_path)
        scripts = next(c["scripts"] for c in result["configs"] if c["name"] == "npm scripts")
        assert "typecheck" in scripts
        assert "type-check" in scripts


class TestScanAgentConfig:
    def test_no_agent_config(self, empty_repo):
        result = scan_agent_config(empty_repo)
        assert result["maturity"] == 0
        assert len(result["files"]) == 0

    def test_claude_settings_json(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps({"permissions": {}}))
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".claude/settings.json" for e in result["files"])

    def test_claude_settings_local_json(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.local.json").write_text(json.dumps({"hooks": {"PreToolUse": []}}))
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".claude/settings.local.json" for e in result["files"])

    def test_both_settings_files(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps({"permissions": {}}))
        (claude_dir / "settings.local.json").write_text(json.dumps({"hooks": {}}))
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 2
        paths = [e["path"] for e in result["files"]]
        assert ".claude/settings.json" in paths
        assert ".claude/settings.local.json" in paths

    def test_claude_commands_detected(self, tmp_path):
        """`.claude/commands/*` counts as agent-config maturity."""
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text("# Review\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".claude/commands/review.md" for e in result["files"])

    def test_claude_commands_multiple_files(self, tmp_path):
        """Multiple files in `.claude/commands/` each contribute maturity."""
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text("# Review\n")
        (commands_dir / "ship.md").write_text("# Ship\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 2
        paths = [e["path"] for e in result["files"]]
        assert ".claude/commands/review.md" in paths
        assert ".claude/commands/ship.md" in paths

    def test_claude_commands_nested_files_detected(self, tmp_path):
        """Nested files in `.claude/commands/` count as agent-config maturity."""
        commands_dir = tmp_path / ".claude" / "commands" / "frontend"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text("# Review\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(
            e["path"] == ".claude/commands/frontend/review.md"
            for e in result["files"]
        )

    def test_claude_commands_empty_dir_no_credit(self, tmp_path):
        """An empty `.claude/commands/` directory gives no credit."""
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 0

    def test_claude_commands_suppresses_recommendation(self, tmp_path):
        """A repo with only `.claude/commands/*` should not get the agent-config recommendation."""
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "review.md").write_text("# Review\n")
        agent_config = scan_agent_config(tmp_path)
        assert agent_config["maturity"] >= 1
        recs = generate_recommendations(
            {"total_lines": 50, "structured": True, "total_rules": 5},
            {"l5_count": 2},
            {"test_files": 10, "source_files": 20},
            {"has_ci": True},
            agent_config,
            {"secrets": 0, "todos": 5},
        )
        assert not any("agent configuration" in r for r in recs)

    def test_copilot_instructions_detected(self, tmp_path):
        """`.github/copilot-instructions.md` counts as agent-config maturity."""
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("# Copilot Instructions\n\nUse TypeScript.\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".github/copilot-instructions.md" for e in result["files"])

    def test_copilot_instructions_combined_with_claude_settings(self, tmp_path):
        """Copilot instructions and Claude settings both contribute maturity."""
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("# Instructions\n")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps({"permissions": {}}))
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 2
        paths = [e["path"] for e in result["files"]]
        assert ".github/copilot-instructions.md" in paths
        assert ".claude/settings.json" in paths

    def test_copilot_instructions_suppresses_recommendation(self, tmp_path):
        """A repo with only copilot-instructions.md should not get the agent-config recommendation."""
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("# Copilot Instructions\n")
        agent_config = scan_agent_config(tmp_path)
        assert agent_config["maturity"] >= 1
        recs = generate_recommendations(
            {"total_lines": 50, "structured": True, "total_rules": 5},
            {"l5_count": 2},
            {"test_files": 10, "source_files": 20},
            {"has_ci": True},
            agent_config,
            {"secrets": 0, "todos": 5},
        )
        assert not any("agent configuration" in r for r in recs)

    def test_cursor_rules_detected(self, tmp_path):
        """`.cursor/rules/*` counts as agent-config maturity."""
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "style.mdc").write_text("# Style\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".cursor/rules/style.mdc" for e in result["files"])

    def test_cursor_rules_multiple_files(self, tmp_path):
        """Multiple direct files in `.cursor/rules/` each contribute maturity."""
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "a.mdc").write_text("# A\n")
        (rules_dir / "b.mdc").write_text("# B\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 2
        paths = [e["path"] for e in result["files"]]
        assert ".cursor/rules/a.mdc" in paths
        assert ".cursor/rules/b.mdc" in paths

    def test_cursor_rules_nested_files_detected(self, tmp_path):
        """Nested files in `.cursor/rules/` count as agent-config maturity."""
        rules_dir = tmp_path / ".cursor" / "rules" / "frontend"
        rules_dir.mkdir(parents=True)
        (rules_dir / "ui.mdc").write_text("# UI\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".cursor/rules/frontend/ui.mdc" for e in result["files"])

    def test_cursor_rules_suppresses_recommendation(self, tmp_path):
        """A repo with only `.cursor/rules/*` should not get the agent-config recommendation."""
        rules_dir = tmp_path / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "dev.mdc").write_text("# Dev\n")
        agent_config = scan_agent_config(tmp_path)
        assert agent_config["maturity"] >= 1
        recs = generate_recommendations(
            {"total_lines": 50, "structured": True, "total_rules": 5},
            {"l5_count": 2},
            {"test_files": 10, "source_files": 20},
            {"has_ci": True},
            agent_config,
            {"secrets": 0, "todos": 5},
        )
        assert not any("agent configuration" in r for r in recs)

    def test_github_instructions_md_detected(self, tmp_path):
        """`.github/instructions/*.instructions.md` counts as agent-config maturity."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "code-review.instructions.md").write_text("# Code Review\n\nBe thorough.\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(e["path"] == ".github/instructions/code-review.instructions.md" for e in result["files"])

    def test_github_instructions_multiple_files(self, tmp_path):
        """Multiple *.instructions.md files each contribute maturity."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "code-review.instructions.md").write_text("# Review\n")
        (inst_dir / "testing.instructions.md").write_text("# Testing\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 2
        paths = [e["path"] for e in result["files"]]
        assert ".github/instructions/code-review.instructions.md" in paths
        assert ".github/instructions/testing.instructions.md" in paths

    def test_github_instructions_nested_dirs_detected(self, tmp_path):
        """Nested *.instructions.md files count as agent-config maturity."""
        inst_dir = tmp_path / ".github" / "instructions"
        (inst_dir / "frontend").mkdir(parents=True)
        (inst_dir / "frontend" / "review.instructions.md").write_text("# Review\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 1
        assert any(
            e["path"] == ".github/instructions/frontend/review.instructions.md"
            for e in result["files"]
        )

    def test_github_instructions_non_matching_ignored(self, tmp_path):
        """Files not matching *.instructions.md in .github/instructions/ are ignored."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "README.md").write_text("# About\n")
        (inst_dir / "notes.txt").write_text("Just notes\n")
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 0

    def test_github_instructions_empty_dir_no_credit(self, tmp_path):
        """An empty .github/instructions/ directory gives no credit."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 0

    def test_github_instructions_combined_with_claude_settings(self, tmp_path):
        """GitHub instructions and Claude settings both contribute maturity."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "style.instructions.md").write_text("# Style\n")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(json.dumps({"permissions": {}}))
        result = scan_agent_config(tmp_path)
        assert result["maturity"] == 2
        paths = [e["path"] for e in result["files"]]
        assert ".github/instructions/style.instructions.md" in paths
        assert ".claude/settings.json" in paths

    def test_github_instructions_suppresses_recommendation(self, tmp_path):
        """A repo with only .github/instructions/*.instructions.md should not get the agent-config recommendation."""
        inst_dir = tmp_path / ".github" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "dev.instructions.md").write_text("# Dev\n")
        agent_config = scan_agent_config(tmp_path)
        assert agent_config["maturity"] >= 1
        recs = generate_recommendations(
            {"total_lines": 50, "structured": True, "total_rules": 5},
            {"l5_count": 2},
            {"test_files": 10, "source_files": 20},
            {"has_ci": True},
            agent_config,
            {"secrets": 0, "todos": 5},
        )
        assert not any("agent configuration" in r for r in recs)


class TestScanAntiPatterns:
    def test_clean_repo(self, empty_repo):
        result = scan_anti_patterns(empty_repo)
        assert result["secrets"] == 0
        assert result["todos"] == 0

    def test_todos_counted(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / "code.py").write_text("# TODO: fix this\n# FIXME: another\n")
        result = scan_anti_patterns(tmp_path)
        assert result["todos"] == 2

    def test_env_file_secrets_detected(self, tmp_path):
        """Committed .env files with secret-like contents are flagged."""
        (tmp_path / ".env").write_text(
            'OPENAI_API_KEY="sk-abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] >= 1

    def test_env_local_secrets_detected(self, tmp_path):
        """Committed .env.local files with secret-like contents are flagged."""
        (tmp_path / ".env.local").write_text(
            'PASSWORD="super-secret-password-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] >= 1

    def test_multiple_env_files_counted_separately(self, tmp_path):
        """Each env file with secrets counts as a separate finding."""
        (tmp_path / ".env").write_text(
            'API_KEY="sk-abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        (tmp_path / ".env.local").write_text(
            'SECRET="this-is-a-very-long-secret-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] >= 2

    def test_env_file_without_secrets_not_flagged(self, tmp_path):
        """A .env file with no secret-like content is not flagged."""
        (tmp_path / ".env").write_text("DEBUG=true\nPORT=3000\n")
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_production_secrets_detected(self, tmp_path):
        """Committed .env.production files with secrets are flagged."""
        (tmp_path / ".env.production").write_text(
            'TOKEN="abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] >= 1

    def test_env_example_ignored(self, tmp_path):
        """.env.example files are templates and should not trigger secret detection."""
        (tmp_path / ".env.example").write_text(
            'API_KEY="sk-placeholder-replace-me-with-real-key"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_sample_ignored(self, tmp_path):
        """.env.sample files are templates and should not trigger secret detection."""
        (tmp_path / ".env.sample").write_text(
            'SECRET="replace-this-with-your-secret-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_template_ignored(self, tmp_path):
        """.env.template and .env.dist files are not scanned for secrets."""
        (tmp_path / ".env.template").write_text(
            'TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"\n'
        )
        (tmp_path / ".env.dist").write_text(
            'PASSWORD="changeme-this-is-a-placeholder-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_real_env_still_detected_alongside_template(self, tmp_path):
        """Real .env is flagged even when a .env.example exists in the same repo."""
        (tmp_path / ".env.example").write_text(
            'API_KEY="sk-placeholder-replace-me-with-real-key"\n'
        )
        (tmp_path / ".env").write_text(
            'API_KEY="sk-live-abcdefghijklmnopqrstuvwxyz123456"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 1

    def test_env_template_local_ignored(self, tmp_path):
        """.env.template.local is a template variant and should not trigger secrets."""
        (tmp_path / ".env.template.local").write_text(
            'TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_example_local_ignored(self, tmp_path):
        """.env.example.local is a template variant and should not trigger secrets."""
        (tmp_path / ".env.example.local").write_text(
            'API_KEY="sk-placeholder-replace-me-with-real-key"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_sample_local_ignored(self, tmp_path):
        """.env.sample.local is a template variant and should not trigger secrets."""
        (tmp_path / ".env.sample.local").write_text(
            'SECRET="replace-this-with-your-secret-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_dist_local_ignored(self, tmp_path):
        """.env.dist.local is a template variant and should not trigger secrets."""
        (tmp_path / ".env.dist.local").write_text(
            'PASSWORD="changeme-this-is-a-placeholder-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_real_env_local_still_detected(self, tmp_path):
        """.env.local (no template marker) must still be flagged."""
        (tmp_path / ".env.local").write_text(
            'PASSWORD="super-secret-password-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] >= 1

    def test_real_env_production_still_detected(self, tmp_path):
        """.env.production must still be flagged."""
        (tmp_path / ".env.production").write_text(
            'TOKEN="abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] >= 1

    # -- suffix-order template variants ----------------------------------------

    def test_env_local_example_ignored(self, tmp_path):
        """.env.local.example (suffix-order) is a template and should not trigger secrets."""
        (tmp_path / ".env.local.example").write_text(
            'API_KEY="sk-placeholder-replace-me-with-real-key"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_production_sample_ignored(self, tmp_path):
        """.env.production.sample (suffix-order) is a template and should not trigger secrets."""
        (tmp_path / ".env.production.sample").write_text(
            'SECRET="replace-this-with-your-secret-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_local_template_ignored(self, tmp_path):
        """.env.local.template (suffix-order) is a template and should not trigger secrets."""
        (tmp_path / ".env.local.template").write_text(
            'TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_staging_dist_ignored(self, tmp_path):
        """.env.staging.dist (suffix-order) is a template and should not trigger secrets."""
        (tmp_path / ".env.staging.dist").write_text(
            'PASSWORD="changeme-this-is-a-placeholder-value"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_real_env_local_detected_alongside_suffix_template(self, tmp_path):
        """Real .env.local is flagged even when .env.local.example exists."""
        (tmp_path / ".env.local.example").write_text(
            'API_KEY="sk-placeholder-replace-me-with-real-key"\n'
        )
        (tmp_path / ".env.local").write_text(
            'API_KEY="sk-live-abcdefghijklmnopqrstuvwxyz123456"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 1

    def test_real_env_production_detected_alongside_suffix_template(self, tmp_path):
        """Real .env.production is flagged even when .env.production.sample exists."""
        (tmp_path / ".env.production.sample").write_text(
            'TOKEN="replace-this-placeholder-token-value-now"\n'
        )
        (tmp_path / ".env.production").write_text(
            'TOKEN="abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 1

    # -- case-insensitive template markers -------------------------------------

    def test_env_Example_uppercase_ignored(self, tmp_path):
        """.env.Example (uppercase E) is a template and should not trigger secrets."""
        (tmp_path / ".env.Example").write_text(
            'TOKEN="replace-this-placeholder-token-value-now"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_SAMPLE_uppercase_ignored(self, tmp_path):
        """.env.SAMPLE (all caps) is a template and should not trigger secrets."""
        (tmp_path / ".env.SAMPLE").write_text(
            'API_KEY="replace-this-placeholder-token-value-now"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_Template_local_mixed_case_ignored(self, tmp_path):
        """.env.Template.local (mixed case prefix) is a template."""
        (tmp_path / ".env.Template.local").write_text(
            'SECRET="replace-this-placeholder-token-value-now"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_local_Example_suffix_uppercase_ignored(self, tmp_path):
        """.env.local.Example (suffix-order, uppercase) is a template."""
        (tmp_path / ".env.local.Example").write_text(
            'TOKEN="replace-this-placeholder-token-value-now"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_production_SAMPLE_suffix_uppercase_ignored(self, tmp_path):
        """.env.production.SAMPLE (suffix-order, all caps) is a template."""
        (tmp_path / ".env.production.SAMPLE").write_text(
            'TOKEN="replace-this-placeholder-token-value-now"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_env_Dist_uppercase_ignored(self, tmp_path):
        """.env.Dist (uppercase D) is a template and should not trigger secrets."""
        (tmp_path / ".env.Dist").write_text(
            'PASSWORD="replace-this-placeholder-token-value-now"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 0

    def test_real_env_still_detected_with_uppercase_template(self, tmp_path):
        """Real .env is flagged even when .env.Example exists."""
        (tmp_path / ".env.Example").write_text(
            'TOKEN="replace-this-placeholder-token-value-now"\n'
        )
        (tmp_path / ".env").write_text(
            'TOKEN="abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 1

    def test_real_env_local_still_detected_with_uppercase_template(self, tmp_path):
        """Real .env.local is flagged even when .env.local.Example exists."""
        (tmp_path / ".env.local.Example").write_text(
            'TOKEN="replace-this-placeholder-token-value-now"\n'
        )
        (tmp_path / ".env.local").write_text(
            'TOKEN="abcdefghijklmnopqrstuvwxyz1234567890"\n'
        )
        result = scan_anti_patterns(tmp_path)
        assert result["secrets"] == 1


class TestGenerateRecommendations:
    """Tests for agent-config recommendation in generate_recommendations."""

    def _defaults(self, **overrides):
        """Return scan result dicts with sane defaults, merged with overrides."""
        base = {
            "claude_md": {"total_lines": 50, "structured": True, "total_rules": 5},
            "hooks": {"l5_count": 2},
            "tests": {"test_files": 10, "source_files": 20},
            "cicd": {"has_ci": True},
            "agent_config": {"maturity": 0},
            "anti_patterns": {"secrets": 0, "todos": 5},
        }
        base.update(overrides)
        return base

    def test_agent_config_zero_maturity_produces_recommendation(self):
        d = self._defaults()
        recs = generate_recommendations(
            d["claude_md"], d["hooks"], d["tests"],
            d["cicd"], d["agent_config"], d["anti_patterns"],
        )
        assert any("agent configuration" in r for r in recs)

    def test_agent_config_nonzero_maturity_no_recommendation(self):
        d = self._defaults(agent_config={"maturity": 1})
        recs = generate_recommendations(
            d["claude_md"], d["hooks"], d["tests"],
            d["cicd"], d["agent_config"], d["anti_patterns"],
        )
        assert not any("agent configuration" in r for r in recs)

    def test_top_three_cap_preserved(self):
        """Even with many gaps, only 3 recommendations are returned."""
        d = self._defaults(
            claude_md={"total_lines": 0, "structured": False, "total_rules": 0},
            hooks={"l5_count": 0},
            tests={"test_files": 0, "source_files": 10},
            cicd={"has_ci": False},
            agent_config={"maturity": 0},
            anti_patterns={"secrets": 3, "todos": 50},
        )
        recs = generate_recommendations(
            d["claude_md"], d["hooks"], d["tests"],
            d["cicd"], d["agent_config"], d["anti_patterns"],
        )
        assert len(recs) <= 3

    def test_agent_config_rec_does_not_displace_higher_priority(self):
        """CLAUDE.md, hooks, tests recs should appear before agent-config when all are missing."""
        d = self._defaults(
            claude_md={"total_lines": 0, "structured": False, "total_rules": 0},
            hooks={"l5_count": 0},
            tests={"test_files": 0, "source_files": 10},
            agent_config={"maturity": 0},
        )
        recs = generate_recommendations(
            d["claude_md"], d["hooks"], d["tests"],
            d["cicd"], d["agent_config"], d["anti_patterns"],
        )
        # CLAUDE.md, hooks, and tests recs take the top 3 slots
        assert "CLAUDE.md" in recs[0]
        assert "hook" in recs[1].lower()
        assert "test" in recs[2].lower()
        assert not any("agent configuration" in r for r in recs)

    def test_secrets_recommendation_high_priority(self):
        """Secret removal recommendation appears when secrets are found, even with other gaps."""
        d = self._defaults(
            claude_md={"total_lines": 0, "structured": False, "total_rules": 0},
            hooks={"l5_count": 0},
            anti_patterns={"secrets": 2, "todos": 5},
        )
        recs = generate_recommendations(
            d["claude_md"], d["hooks"], d["tests"],
            d["cicd"], d["agent_config"], d["anti_patterns"],
        )
        assert any("Remove hardcoded secrets" in r for r in recs)


class TestScanRepo:
    def test_empty_repo(self, empty_repo):
        result = scan_repo(empty_repo)
        assert result["score"] == 0 or result["score"] > 0  # just runs without error
        assert result["grade"] in ("A", "B", "C", "D", "F")
        assert "cta" in result
        assert "walseth.ai" in result["cta"]["assessment"]

    def test_rich_repo(self, rich_repo):
        result = scan_repo(rich_repo)
        assert result["score"] > 0
        assert "categories" in result
        assert "recommendations" in result
        assert len(result["categories"]) == 6

    def test_nonexistent_repo(self):
        with pytest.raises(FileNotFoundError):
            scan_repo("/nonexistent/path/to/repo")

    def test_json_fields(self, rich_repo):
        result = scan_repo(rich_repo)
        assert "score" in result
        assert "grade" in result
        assert "categories" in result
        assert "cta" in result
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100


class TestCalculateScores:
    def test_zero_scores(self):
        scores = calculate_scores(
            {"total_lines": 0, "total_rules": 0, "structured": False},
            {"l5_count": 0},
            {"test_files": 0},
            {"has_ci": False},
            {"maturity": 0},
            {"secrets": 1, "todos": 100},
        )
        assert scores["overall"] >= 0
        assert scores["enforcement"] == 0

    def test_max_scores(self):
        scores = calculate_scores(
            {"total_lines": 100, "total_rules": 10, "structured": True},
            {"l5_count": 5},
            {"test_files": 20},
            {"has_ci": True},
            {"maturity": 5},
            {"secrets": 0, "todos": 5},
        )
        assert scores["overall"] > 50
        assert scores["enforcement"] > 50
