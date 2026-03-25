"""Tests for the governance-scan CLI."""

import json
import subprocess
import sys

import pytest


@pytest.fixture
def empty_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    return tmp_path


class TestCli:
    def test_human_output(self, empty_repo):
        result = subprocess.run(
            [sys.executable, "-m", "governance_scan.cli", str(empty_repo), "--no-color"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Score:" in result.stdout
        assert "Grade:" in result.stdout
        assert "walseth.ai" in result.stdout

    def test_json_output(self, empty_repo):
        result = subprocess.run(
            [sys.executable, "-m", "governance_scan.cli", "--json", str(empty_repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "score" in data
        assert "grade" in data
        assert "cta" in data
        assert "walseth.ai" in data["cta"]["assessment"]

    def test_nonexistent_path(self):
        result = subprocess.run(
            [sys.executable, "-m", "governance_scan.cli", "/nonexistent/path"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "Error" in result.stderr

    def test_nonexistent_path_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "governance_scan.cli", "--json", "/nonexistent/path"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["error"] is True
        assert data["code"] == "REPO_NOT_FOUND"
        assert "message" in data
        assert result.stderr == ""

    def test_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "governance_scan.cli", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "1.0.0" in result.stdout

    def test_cta_in_human_output(self, empty_repo):
        result = subprocess.run(
            [sys.executable, "-m", "governance_scan.cli", str(empty_repo), "--no-color"],
            capture_output=True, text=True,
        )
        assert "walseth.ai/audit" in result.stdout
        assert "walseth.ai/pricing" in result.stdout
