"""Tests for the governance-scan scanner module."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from governance_scan.scanner import (
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


class TestScanHooks:
    def test_no_hooks(self, empty_repo):
        result = scan_hooks(empty_repo)
        assert result["l5_count"] == 0

    def test_pre_commit_config(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1

    def test_claude_settings_hooks(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": {"PreToolUse": [{"matcher": "Write", "command": "echo check"}]}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = scan_hooks(tmp_path)
        assert result["l5_count"] >= 1


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
