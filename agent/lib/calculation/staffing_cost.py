"""Pure functions for staffing cost calculation.

All functions are stateless — no external dependencies.
"""

from __future__ import annotations


def calculate_role_total_hours(phase_hours: dict[str, float]) -> float:
    """Sum hours across all phases for a single role.

    Args:
        phase_hours: e.g. {"discovery": 40, "development": 80, "testing": 20}

    Returns:
        Total hours (e.g. 140).
    """
    return sum(phase_hours.values())


def calculate_role_total_cost(
    count: int,
    allocation_pct: float,
    rate_per_hour: float,
    total_hours: float,
) -> float:
    """Calculate total cost for a single role.

    Formula: count * (allocation_pct / 100) * rate_per_hour * total_hours

    Returns:
        Role total cost rounded to 2 decimal places.
    """
    return round(count * (allocation_pct / 100) * rate_per_hour * total_hours, 2)


def calculate_grand_total(
    role_costs: list[float],
) -> float:
    """Sum all role costs into a grand total.

    Args:
        role_costs: list of per-role total costs.

    Returns:
        Grand total cost rounded to 2 decimal places.
    """
    return round(sum(role_costs), 2)
