"""CLI interface for governance-scan."""

import argparse
import json
import sys

from . import __version__
from .scanner import scan_repo
from .scoring import grade


# ANSI colors (disabled with --no-color)
class _Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    DIM = "\033[2m"


class _NoColors:
    RESET = ""
    BOLD = ""
    RED = ""
    GREEN = ""
    YELLOW = ""
    BLUE = ""
    CYAN = ""
    DIM = ""


def _grade_color(g: str, c) -> str:
    colors = {"A": c.GREEN, "B": c.GREEN, "C": c.YELLOW, "D": c.RED, "F": c.RED}
    return colors.get(g, "")


def _score_bar(score: int, width: int = 20) -> str:
    filled = int(score / 100 * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _format_human(result: dict, c) -> str:
    lines = []
    g = result["grade"]
    gc = _grade_color(g, c)

    lines.append("")
    lines.append(f"  {c.BOLD}governance-scan{c.RESET}  v{__version__}")
    lines.append(f"  {c.DIM}{result['repo']}{c.RESET}")
    lines.append("")

    # Overall score
    lines.append(f"  {c.BOLD}Score:{c.RESET} {gc}{result['score']}/100{c.RESET}  "
                 f"{c.BOLD}Grade:{c.RESET} {gc}{g}{c.RESET}  "
                 f"{_score_bar(result['score'])}")
    lines.append("")

    # Sub-scores
    scores = result["scores"]
    lines.append(f"  {c.BOLD}Breakdown:{c.RESET}")
    for label, key in [("Enforcement", "enforcement"), ("Hygiene", "hygiene"), ("Automation", "automation")]:
        s = scores[key]
        sg = grade(s)
        sgc = _grade_color(sg, c)
        lines.append(f"    {label:20s} {sgc}{s:3d}/100 {sg}{c.RESET}  {_score_bar(s, 15)}")
    lines.append("")

    # Category breakdown
    lines.append(f"  {c.BOLD}Categories:{c.RESET}")
    for cat in result["categories"].values():
        cs = cat["score"]
        cg = grade(cs)
        cgc = _grade_color(cg, c)
        lines.append(f"    {cat['name']:25s} {cgc}{cs:3d}/100{c.RESET}")
    lines.append("")

    # Recommendations
    if result["recommendations"]:
        lines.append(f"  {c.BOLD}Top Recommendations:{c.RESET}")
        for i, rec in enumerate(result["recommendations"], 1):
            lines.append(f"    {c.YELLOW}{i}.{c.RESET} {rec}")
        lines.append("")

    # CTA
    lines.append(f"  {c.DIM}---{c.RESET}")
    lines.append(f"  {c.CYAN}{result['cta']['assessment']}{c.RESET}")
    lines.append(f"  {c.CYAN}{result['cta']['enterprise']}{c.RESET}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        prog="governance-scan",
        description="AI governance scanner for codebases. Scores enforcement maturity, context hygiene, and automation readiness.",
    )
    parser.add_argument("path", help="Path to the repository to scan")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output machine-readable JSON")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colorized output")
    parser.add_argument("--version", action="version", version=f"governance-scan {__version__}")

    args = parser.parse_args()

    try:
        result = scan_repo(args.path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        c = _NoColors if args.no_color else _Colors
        print(_format_human(result, c))


if __name__ == "__main__":
    main()
