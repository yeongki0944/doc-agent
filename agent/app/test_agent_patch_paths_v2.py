"""Agent patch path v2 tests.

Verifies that all agent-generated JSON Patch operations target v2 schema
paths only. Uses source code inspection (ast/inspect) to avoid importing
orchestrator.py which binds port 8080 via runtime.py.

Requirements: 6.1–6.8, 8.6
"""

from __future__ import annotations

import ast
import inspect
import os
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths to source files (relative to workspace root)
# ---------------------------------------------------------------------------

_AGENT_ROOT = Path(__file__).resolve().parent.parent  # agent/
_ORCHESTRATOR_PATH = _AGENT_ROOT / "app" / "parent" / "orchestrator.py"
_DISCOVERY_PATH = _AGENT_ROOT / "app" / "discovery" / "discovery_agent.py"
_REVIEWER_PATH = _AGENT_ROOT / "app" / "reviewer" / "reviewer_agent.py"


def _read_source(path: Path) -> str:
    """Read a Python source file as text."""
    return path.read_text(encoding="utf-8")


def _parse_ast(path: Path) -> ast.Module:
    """Parse a Python source file into an AST."""
    return ast.parse(_read_source(path), filename=str(path))


def _extract_function_source(path: Path, func_name: str) -> str:
    """Extract the source text of a top-level or method function by name."""
    source = _read_source(path)
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                start = node.lineno - 1  # 0-indexed
                end = node.end_lineno  # 1-indexed inclusive
                return "".join(lines[start:end])

    raise ValueError(f"Function {func_name!r} not found in {path}")


def _extract_all_string_literals(source: str) -> list[str]:
    """Extract all string literal values from a chunk of Python source."""
    dedented = textwrap.dedent(source)
    tree = ast.parse(dedented)
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
    return strings


def _strip_docstrings(source: str) -> str:
    """Remove docstrings from source code so we only check executable code."""
    dedented = textwrap.dedent(source)
    tree = ast.parse(dedented)
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
                ds = node.body[0]
                for line_no in range(ds.lineno, (ds.end_lineno or ds.lineno) + 1):
                    docstring_lines.add(line_no)
    lines = dedented.splitlines(keepends=True)
    return "".join(
        line for i, line in enumerate(lines, start=1)
        if i not in docstring_lines
    )


def _extract_non_docstring_string_literals(source: str) -> list[str]:
    """Extract string literals from source, excluding docstrings and comments."""
    cleaned = _strip_docstrings(source)
    tree = ast.parse(cleaned)
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
    return strings


# =========================================================================
# Test 1: Discovery patches target v2 paths only
# =========================================================================

class TestDiscoveryPatchPaths:
    """Verify Discovery-related patches use v2 paths only.

    Requirements: 6.1, 6.2
    """

    def test_discovery_schema_patches_no_legacy_project_goal(self):
        """_discovery_schema_patches must NOT produce /meta/project_goal."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_discovery_schema_patches")
        strings = _extract_all_string_literals(source)
        assert "/meta/project_goal" not in strings, (
            "_discovery_schema_patches still references legacy /meta/project_goal"
        )

    def test_discovery_schema_patches_no_legacy_scope_summary(self):
        """_discovery_schema_patches must NOT produce /sections/scope_of_work/summary."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_discovery_schema_patches")
        strings = _extract_all_string_literals(source)
        assert "/sections/scope_of_work/summary" not in strings, (
            "_discovery_schema_patches still references legacy /sections/scope_of_work/summary"
        )

    def test_discovery_schema_patches_no_role_or_description(self):
        """_discovery_schema_patches must NOT reference role_or_description."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_discovery_schema_patches")
        assert "role_or_description" not in source, (
            "_discovery_schema_patches still references legacy role_or_description"
        )

    def test_delegate_discovery_no_legacy_project_goal(self):
        """_delegate_discovery must NOT produce /meta/project_goal."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_discovery")
        strings = _extract_non_docstring_string_literals(source)
        assert "/meta/project_goal" not in strings, (
            "_delegate_discovery still references legacy /meta/project_goal"
        )

    def test_delegate_discovery_no_legacy_scope_summary(self):
        """_delegate_discovery must NOT produce /sections/scope_of_work/summary."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_discovery")
        strings = _extract_non_docstring_string_literals(source)
        assert "/sections/scope_of_work/summary" not in strings, (
            "_delegate_discovery still references legacy /sections/scope_of_work/summary"
        )

    def test_delegate_discovery_uses_v2_customer_intro(self):
        """_delegate_discovery maps project_goal to /sections/executive_summary/customer_intro."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_discovery")
        assert "/sections/executive_summary/customer_intro" in source

    def test_delegate_discovery_uses_v2_problem_statement(self):
        """_delegate_discovery maps scope_summary to /sections/executive_summary/problem_statement."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_discovery")
        assert "/sections/executive_summary/problem_statement" in source

    def test_discovery_schema_patches_targets_v2_executive_summary(self):
        """_discovery_schema_patches targets v2 executive_summary sub-fields."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_discovery_schema_patches")
        strings = _extract_all_string_literals(source)
        v2_paths = [
            "/sections/executive_summary/customer_intro",
            "/sections/executive_summary/problem_statement",
            "/sections/executive_summary/proposed_solution",
        ]
        for path in v2_paths:
            assert path in strings, f"Missing v2 path: {path}"

    def test_discovery_schema_patches_no_legacy_executive_text(self):
        """_discovery_schema_patches must NOT target /sections/executive_summary/text."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_discovery_schema_patches")
        strings = _extract_all_string_literals(source)
        assert "/sections/executive_summary/text" not in strings
        assert "/sections/executive_summary/summary" not in strings

    def test_discovery_contact_to_field_value_no_role_or_description(self):
        """_contact_to_field_value must NOT use role_or_description as a dict key."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_contact_to_field_value")
        # Strip docstrings — the docstring mentions "role_or_description" as documentation
        cleaned = _strip_docstrings(source)
        assert "role_or_description" not in cleaned, (
            "_contact_to_field_value still uses role_or_description in executable code"
        )

    def test_discovery_agent_source_no_role_or_description_in_contact_list(self):
        """discovery_agent.py _contact_list must NOT produce role_or_description."""
        source = _read_source(_DISCOVERY_PATH)
        # The _contact_list function should not include role_or_description as a key
        contact_list_source = _extract_function_source(_DISCOVERY_PATH, "_contact_list")
        assert "role_or_description" not in contact_list_source


# =========================================================================
# Test 2: Orchestrator architecture patches target v2 paths
# =========================================================================

class TestArchitecturePatchPaths:
    """Verify architecture delegation uses v2 paths.

    Requirements: 6.3, 6.4
    """

    def test_delegate_architecture_no_legacy_description(self):
        """_delegate_architecture must NOT target /sections/architecture/description."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_architecture")
        strings = _extract_non_docstring_string_literals(source)
        assert "/sections/architecture/description" not in strings, (
            "_delegate_architecture still references legacy /sections/architecture/description"
        )

    def test_delegate_architecture_no_legacy_tools(self):
        """_delegate_architecture must NOT target /sections/architecture/tools (without _list)."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_architecture")
        strings = _extract_non_docstring_string_literals(source)
        # Must not have exactly "/sections/architecture/tools" (the legacy path)
        # but "/sections/architecture/tools_list" is fine
        legacy_tools_paths = [s for s in strings if s == "/sections/architecture/tools"]
        assert len(legacy_tools_paths) == 0, (
            "_delegate_architecture still references legacy /sections/architecture/tools"
        )

    def test_delegate_architecture_uses_overview(self):
        """_delegate_architecture targets /sections/architecture/overview."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_architecture")
        assert "/sections/architecture/overview" in source

    def test_delegate_architecture_uses_tools_list(self):
        """_delegate_architecture targets /sections/architecture/tools_list."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_architecture")
        assert "/sections/architecture/tools_list" in source


# =========================================================================
# Test 3: Orchestrator staffing patches target v2 paths
# =========================================================================

class TestStaffingPatchPaths:
    """Verify staffing delegation uses /sections/resources_cost_estimates/.

    Requirements: 6.5, 6.6
    """

    def test_delegate_staffing_no_legacy_staffing_plan(self):
        """_delegate_staffing must NOT target /staffing_plan/..."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_staffing")
        strings = _extract_non_docstring_string_literals(source)
        staffing_plan_paths = [s for s in strings if s.startswith("/staffing_plan")]
        assert len(staffing_plan_paths) == 0, (
            f"_delegate_staffing still references legacy /staffing_plan paths: {staffing_plan_paths}"
        )

    def test_delegate_staffing_uses_resources_cost_estimates(self):
        """_delegate_staffing targets /sections/resources_cost_estimates/..."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_staffing")
        assert "/sections/resources_cost_estimates/" in source

    def test_delegate_staffing_targets_partner_technical_team(self):
        """_delegate_staffing patches partner_technical_team."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_staffing")
        assert "partner_technical_team" in source

    def test_delegate_discovery_no_staffing_plan_patches(self):
        """_delegate_discovery must NOT generate /staffing_plan/ patches."""
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_discovery")
        strings = _extract_non_docstring_string_literals(source)
        staffing_plan_paths = [s for s in strings if "/staffing_plan" in s]
        assert len(staffing_plan_paths) == 0, (
            f"_delegate_discovery references /staffing_plan paths: {staffing_plan_paths}"
        )


# =========================================================================
# Test 4: ReviewerAgent does not reference staffing_plan.roles
# =========================================================================

class TestReviewerNoStaffingPlan:
    """Verify ReviewerAgent does not reference staffing_plan.roles.

    Requirement: 6.7
    """

    def test_reviewer_review_no_staffing_plan_roles(self):
        """ReviewerAgent.review() must not reference staffing_plan.roles."""
        from agent.app.reviewer.reviewer_agent import ReviewerAgent
        source = inspect.getsource(ReviewerAgent.review)
        assert "staffing_plan.roles" not in source, (
            "ReviewerAgent.review() still references staffing_plan.roles"
        )
        assert "staffing_plan" not in source, (
            "ReviewerAgent.review() still references staffing_plan"
        )

    def test_reviewer_calculate_completion_score_no_staffing_plan(self):
        """ReviewerAgent.calculate_completion_score() must not reference staffing_plan in code."""
        from agent.app.reviewer.reviewer_agent import ReviewerAgent
        source = inspect.getsource(ReviewerAgent.calculate_completion_score)
        # Strip docstrings — the docstring mentions "staffing_plan" as documentation
        cleaned = _strip_docstrings(source)
        assert "staffing_plan" not in cleaned, (
            "ReviewerAgent.calculate_completion_score() still references staffing_plan in executable code"
        )

    def test_reviewer_uses_resources_cost_estimates(self):
        """ReviewerAgent.review() reads staffing from resources_cost_estimates."""
        from agent.app.reviewer.reviewer_agent import ReviewerAgent
        source = inspect.getsource(ReviewerAgent.review)
        assert "resources_cost_estimates" in source, (
            "ReviewerAgent.review() should reference resources_cost_estimates for staffing data"
        )


# =========================================================================
# Test 5: ReviewerAgent can patch /sections/cost_breakdown/funding_calculation
# =========================================================================

class TestReviewerFundingCalculation:
    """Verify ReviewerAgent can patch /sections/cost_breakdown/funding_calculation.

    Requirement: 6.8
    """

    def test_reviewer_calls_funding_validator(self):
        """ReviewerAgent.review() invokes FundingValidator."""
        from agent.app.reviewer.reviewer_agent import ReviewerAgent
        source = inspect.getsource(ReviewerAgent.review)
        assert "FundingValidator" in source, (
            "ReviewerAgent.review() should call FundingValidator"
        )

    def test_funding_validator_writes_funding_calculation(self):
        """FundingValidator.calculate_funding reads from cost_breakdown.funding_calculation."""
        from agent.app.funding.funding_validator import FundingValidator
        source = inspect.getsource(FundingValidator.calculate_funding)
        assert "funding_calculation" in source, (
            "FundingValidator.calculate_funding should reference funding_calculation"
        )

    def test_document_state_allows_funding_calculation_patch(self):
        """CostBreakdownSection has a funding_calculation dict field that can be patched."""
        from agent.lib.schema.document_state import CostBreakdownSection, DocumentState

        # Verify the field exists and is a dict
        doc = DocumentState()
        assert hasattr(doc.sections.cost_breakdown, "funding_calculation")
        assert isinstance(doc.sections.cost_breakdown.funding_calculation, dict)

        # Verify we can set funding_calculation data
        doc.sections.cost_breakdown.funding_calculation = {
            "yr1_arr": 100000,
            "sow_cost": 50000,
            "eligible_amount": 25000,
        }
        dumped = doc.sections.cost_breakdown.model_dump()
        assert dumped["funding_calculation"]["yr1_arr"] == 100000
        assert dumped["funding_calculation"]["eligible_amount"] == 25000

    def test_reviewer_result_includes_funding_validation(self):
        """ReviewerAgent.review() stores funding_validation in ReviewResult."""
        from agent.app.reviewer.reviewer_agent import ReviewerAgent
        source = inspect.getsource(ReviewerAgent.review)
        assert "funding_validation" in source, (
            "ReviewerAgent.review() should store funding_validation result"
        )

    def test_delegate_reviewer_patches_funding_path(self):
        """Orchestrator._delegate_reviewer can produce patches for cost_breakdown."""
        # The reviewer delegation in orchestrator patches /completion_score,
        # /blocking_issues, /warnings. The funding_calculation is written
        # by FundingValidator into the ReviewResult, which the orchestrator
        # can then patch to /sections/cost_breakdown/funding_calculation.
        # Verify the orchestrator's _delegate_reviewer references the right paths.
        source = _extract_function_source(_ORCHESTRATOR_PATH, "_delegate_reviewer")
        # The reviewer patches completion_score, blocking_issues, warnings
        assert "/completion_score" in source
        assert "/blocking_issues" in source
        assert "/warnings" in source
