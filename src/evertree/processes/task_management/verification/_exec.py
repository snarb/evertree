"""Evaluate mandatory check results without accepting or executing the decision."""

from evertree.core.cognition.control import verification_result


def run(required_checks: list[str], checks: dict):
    return {"result": verification_result(required_checks, checks).to_dict(), "feedback": None}
