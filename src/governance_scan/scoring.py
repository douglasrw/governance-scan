"""Scoring and grading for governance scans."""


def grade(score: int) -> str:
    """Convert a numeric score (0-100) to a letter grade (A/B/C/D/F)."""
    if score >= 80:
        return "A"
    elif score >= 60:
        return "B"
    elif score >= 40:
        return "C"
    elif score >= 20:
        return "D"
    return "F"


def calculate_scores(claude_md: dict, hooks: dict, tests: dict,
                     cicd: dict, agent_config: dict,
                     anti_patterns: dict) -> dict:
    """Calculate enforcement posture scores from scan results.

    Returns dict with enforcement, hygiene, automation, overall (all 0-100).
    """
    # Enforcement maturity (0-100)
    enforcement = 0
    enforcement += min(30, hooks["l5_count"] * 10)
    enforcement += min(25, tests["test_files"] * 2)
    enforcement += min(15, claude_md["total_rules"] * 3)
    enforcement += 10 if claude_md["structured"] else 0
    enforcement += 10 if cicd["has_ci"] else 0
    enforcement += 10 if anti_patterns["secrets"] == 0 else 0
    enforcement = min(100, enforcement)

    # Context hygiene (0-100)
    hygiene = 50
    if claude_md["total_lines"] > 0:
        hygiene += 20
        if claude_md["total_lines"] > 500:
            hygiene -= 20
        if claude_md["structured"]:
            hygiene += 15
    else:
        hygiene -= 30
    if anti_patterns["todos"] < 10:
        hygiene += 10
    elif anti_patterns["todos"] > 50:
        hygiene -= 10
    hygiene = max(0, min(100, hygiene))

    # Automation readiness (0-100)
    automation = 0
    automation += 20 if cicd["has_ci"] else 0
    automation += min(20, agent_config["maturity"] * 4)
    automation += 20 if tests["test_files"] > 5 else (10 if tests["test_files"] > 0 else 0)
    automation += 20 if hooks["l5_count"] > 0 else 0
    automation = min(100, automation)

    # Overall (weighted)
    overall = int(enforcement * 0.4 + hygiene * 0.3 + automation * 0.3)

    return {
        "enforcement": enforcement,
        "hygiene": hygiene,
        "automation": automation,
        "overall": overall,
    }
