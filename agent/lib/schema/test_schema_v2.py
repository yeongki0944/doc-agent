"""Schema v2 smoke tests — task 8.1.

Validates DocumentState v2 structure: instantiation, serialization,
field presence/absence, resolve() priority, independent mutable defaults,
and extra="forbid"/"allow" behavior.

Requirements: 1.1–1.17, 2.1–2.7, 8.2, 8.3
"""

from __future__ import annotations

import json

import pytest

from agent.lib.schema.document_state import (
    AcceptanceSection,
    AcceptanceStep,
    ArchitectureSection,
    CategoryGroup,
    ContactEntry,
    CostBreakdownRow,
    CostBreakdownSection,
    CoverSection,
    DocumentState,
    ExecutiveSummarySection,
    FieldStatus,
    FieldValue,
    PhaseHours,
    ResourcesCostEstimatesSection,
    ScopeOfWorkSection,
    ScopeTask,
    StakeholdersSection,
    SuccessCriteriaSection,
    AssumptionsSection,
    TeamMember,
    TotalsRow,
)


# ---------------------------------------------------------------------------
# 1. DocumentState() instantiates without error
# ---------------------------------------------------------------------------

class TestDocumentStateInstantiation:
    def test_default_instantiation(self):
        doc = DocumentState()
        assert doc.document_id == ""
        assert doc.template == "apn_poc_project_plan"
        assert doc.version == 0


# ---------------------------------------------------------------------------
# 2. model_dump() produces a valid JSON-serializable dict
# ---------------------------------------------------------------------------

class TestModelDumpJsonSerializable:
    def test_model_dump_is_json_serializable(self):
        doc = DocumentState()
        data = doc.model_dump()
        assert isinstance(data, dict)
        # json.dumps must not raise
        json_str = json.dumps(data, default=str)
        assert isinstance(json_str, str)
        assert len(json_str) > 0


# ---------------------------------------------------------------------------
# 3. FieldStatus enum has only empty, draft, confirmed
# ---------------------------------------------------------------------------

class TestFieldStatusEnum:
    def test_field_status_members(self):
        members = {s.value for s in FieldStatus}
        assert members == {"empty", "draft", "confirmed"}

    def test_no_legacy_statuses(self):
        member_names = {s.name for s in FieldStatus}
        for legacy in ("recommended", "user_modified", "calculated"):
            assert legacy not in member_names


# ---------------------------------------------------------------------------
# 4. FieldValue has no reason, source_patterns, confidence
# ---------------------------------------------------------------------------

class TestFieldValueNoLegacyAttrs:
    def test_no_reason(self):
        fv = FieldValue()
        assert not hasattr(fv, "reason")

    def test_no_source_patterns(self):
        fv = FieldValue()
        assert not hasattr(fv, "source_patterns")

    def test_no_confidence(self):
        fv = FieldValue()
        assert not hasattr(fv, "confidence")


# ---------------------------------------------------------------------------
# 5. FieldValue.resolve() priority: user_input > ai_recommended > calculated > ""
# ---------------------------------------------------------------------------

class TestFieldValueResolve:
    def test_user_input_wins(self):
        fv = FieldValue(user_input="U", ai_recommended="A", calculated="C")
        assert fv.resolve() == "U"

    def test_ai_recommended_second(self):
        fv = FieldValue(ai_recommended="A", calculated="C")
        assert fv.resolve() == "A"

    def test_calculated_third(self):
        fv = FieldValue(calculated="C")
        assert fv.resolve() == "C"

    def test_empty_fallback(self):
        fv = FieldValue()
        assert fv.resolve() == ""

    def test_empty_string_skipped(self):
        fv = FieldValue(user_input="", ai_recommended="A")
        assert fv.resolve() == "A"

    def test_none_skipped(self):
        fv = FieldValue(user_input=None, ai_recommended=None, calculated="C")
        assert fv.resolve() == "C"


# ---------------------------------------------------------------------------
# 6. DocumentState has no staffing_plan attribute
# ---------------------------------------------------------------------------

class TestNoStaffingPlan:
    def test_no_staffing_plan(self):
        doc = DocumentState()
        assert not hasattr(doc, "staffing_plan")


# ---------------------------------------------------------------------------
# 7. ExecutiveSummarySection: no text/summary, HAS business_case
# ---------------------------------------------------------------------------

class TestExecutiveSummarySection:
    def test_no_text_attribute(self):
        section = ExecutiveSummarySection()
        assert not hasattr(section, "text")

    def test_no_summary_attribute(self):
        section = ExecutiveSummarySection()
        assert not hasattr(section, "summary")

    def test_has_business_case(self):
        section = ExecutiveSummarySection()
        assert hasattr(section, "business_case")
        assert hasattr(section.business_case, "problem_definition")
        assert hasattr(section.business_case, "roi_calculation")
        assert hasattr(section.business_case, "executive_sponsor")
        assert hasattr(section.business_case, "production_commitment")


# ---------------------------------------------------------------------------
# 8. ArchitectureSection: no description/tools, has diagram_image_s3_key/tools_list
# ---------------------------------------------------------------------------

class TestArchitectureSection:
    def test_no_description(self):
        section = ArchitectureSection()
        assert not hasattr(section, "description")

    def test_no_tools(self):
        section = ArchitectureSection()
        assert not hasattr(section, "tools")

    def test_has_diagram_image_s3_key(self):
        section = ArchitectureSection()
        assert hasattr(section, "diagram_image_s3_key")
        assert isinstance(section.diagram_image_s3_key, FieldValue)

    def test_has_tools_list(self):
        section = ArchitectureSection()
        assert hasattr(section, "tools_list")
        assert isinstance(section.tools_list, list)


# ---------------------------------------------------------------------------
# 9. AcceptanceSection: no text, has steps list
# ---------------------------------------------------------------------------

class TestAcceptanceSection:
    def test_no_text(self):
        section = AcceptanceSection()
        assert not hasattr(section, "text")

    def test_has_steps(self):
        section = AcceptanceSection()
        assert hasattr(section, "steps")
        assert isinstance(section.steps, list)

    def test_acceptance_step_structure(self):
        step = AcceptanceStep(
            heading=FieldValue(user_input="Step 1"),
            content=FieldValue(user_input="Do something"),
            bullets=[FieldValue(user_input="bullet 1")],
        )
        assert step.heading.user_input == "Step 1"
        assert step.content.user_input == "Do something"
        assert len(step.bullets) == 1


# ---------------------------------------------------------------------------
# 10. ContactEntry: has description/stakeholder_for/role, no role_or_description
# ---------------------------------------------------------------------------

class TestContactEntry:
    def test_has_description(self):
        ce = ContactEntry()
        assert hasattr(ce, "description")

    def test_has_stakeholder_for(self):
        ce = ContactEntry()
        assert hasattr(ce, "stakeholder_for")

    def test_has_role(self):
        ce = ContactEntry()
        assert hasattr(ce, "role")

    def test_no_role_or_description(self):
        ce = ContactEntry()
        assert not hasattr(ce, "role_or_description")


# ---------------------------------------------------------------------------
# 11. CategoryGroup has bullets (not items)
# ---------------------------------------------------------------------------

class TestCategoryGroup:
    def test_has_bullets(self):
        cg = CategoryGroup()
        assert hasattr(cg, "bullets")
        assert isinstance(cg.bullets, list)

    def test_no_items(self):
        cg = CategoryGroup()
        assert not hasattr(cg, "items")


# ---------------------------------------------------------------------------
# 12. ScopeTask fields are FieldValue
# ---------------------------------------------------------------------------

class TestScopeTaskFields:
    def test_all_fields_are_field_value(self):
        st = ScopeTask()
        assert isinstance(st.task_category, FieldValue)
        assert isinstance(st.schedule, FieldValue)
        assert isinstance(st.details, FieldValue)
        assert isinstance(st.personnel, FieldValue)


# ---------------------------------------------------------------------------
# 13. partner_technical_team is list[TeamMember]
# ---------------------------------------------------------------------------

class TestPartnerTechnicalTeam:
    def test_is_list_of_team_member(self):
        rce = ResourcesCostEstimatesSection()
        assert isinstance(rce.partner_technical_team, list)
        # Add a member and verify type
        member = TeamMember(
            role=FieldValue(user_input="SA"),
            name=FieldValue(user_input="Alice"),
        )
        rce.partner_technical_team.append(member)
        assert isinstance(rce.partner_technical_team[0], TeamMember)
        assert rce.partner_technical_team[0].role.user_input == "SA"
        assert rce.partner_technical_team[0].name.user_input == "Alice"


# ---------------------------------------------------------------------------
# 14. total_hours and total_cost are TotalsRow
# ---------------------------------------------------------------------------

class TestTotalsRow:
    def test_total_hours_is_totals_row(self):
        rce = ResourcesCostEstimatesSection()
        assert isinstance(rce.total_hours, TotalsRow)
        assert rce.total_hours.sa == ""
        assert rce.total_hours.eng == ""
        assert rce.total_hours.other == ""
        assert rce.total_hours.total == ""

    def test_total_cost_is_totals_row(self):
        rce = ResourcesCostEstimatesSection()
        assert isinstance(rce.total_cost, TotalsRow)


# ---------------------------------------------------------------------------
# 15. phase_hours_table is list[PhaseHours]
# ---------------------------------------------------------------------------

class TestPhaseHoursTable:
    def test_is_list(self):
        rce = ResourcesCostEstimatesSection()
        assert isinstance(rce.phase_hours_table, list)

    def test_phase_hours_structure(self):
        ph = PhaseHours(
            phase=FieldValue(user_input="Discovery"),
            sa_hours=40,
            eng_hours=80,
            other_hours=10,
            total=130,
        )
        assert isinstance(ph.phase, FieldValue)
        assert ph.sa_hours == 40
        assert ph.eng_hours == 80
        assert ph.other_hours == 10
        assert ph.total == 130


# ---------------------------------------------------------------------------
# 16. CostBreakdownSection has calculator_url, mrr, arr, breakdown_table, bedrock_extra
# ---------------------------------------------------------------------------

class TestCostBreakdownSection:
    def test_has_calculator_url(self):
        cbs = CostBreakdownSection()
        assert hasattr(cbs, "calculator_url")
        assert isinstance(cbs.calculator_url, FieldValue)

    def test_has_mrr(self):
        cbs = CostBreakdownSection()
        assert hasattr(cbs, "mrr")
        assert isinstance(cbs.mrr, FieldValue)

    def test_has_arr(self):
        cbs = CostBreakdownSection()
        assert hasattr(cbs, "arr")
        assert isinstance(cbs.arr, FieldValue)

    def test_has_breakdown_table(self):
        cbs = CostBreakdownSection()
        assert hasattr(cbs, "breakdown_table")
        assert isinstance(cbs.breakdown_table, list)

    def test_has_bedrock_extra(self):
        cbs = CostBreakdownSection()
        assert hasattr(cbs, "bedrock_extra")
        assert isinstance(cbs.bedrock_extra, FieldValue)


# ---------------------------------------------------------------------------
# 17. CostBreakdownRow has category, mrr, arr, note
# ---------------------------------------------------------------------------

class TestCostBreakdownRow:
    def test_fields_are_field_value(self):
        row = CostBreakdownRow()
        assert isinstance(row.category, FieldValue)
        assert isinstance(row.mrr, FieldValue)
        assert isinstance(row.arr, FieldValue)
        assert isinstance(row.note, FieldValue)


# ---------------------------------------------------------------------------
# 18. ScopeOfWorkSection has tasks, out_of_scope, items
# ---------------------------------------------------------------------------

class TestScopeOfWorkSection:
    def test_has_tasks(self):
        sow = ScopeOfWorkSection()
        assert hasattr(sow, "tasks")
        assert isinstance(sow.tasks, list)

    def test_has_out_of_scope(self):
        sow = ScopeOfWorkSection()
        assert hasattr(sow, "out_of_scope")
        assert isinstance(sow.out_of_scope, list)

    def test_has_items(self):
        sow = ScopeOfWorkSection()
        assert hasattr(sow, "items")
        assert isinstance(sow.items, list)


# ---------------------------------------------------------------------------
# 19. phases_overview, current_pain_points, poc_objectives are list
# ---------------------------------------------------------------------------

class TestListFields:
    def test_phases_overview_is_list(self):
        es = ExecutiveSummarySection()
        assert isinstance(es.phases_overview, list)

    def test_current_pain_points_is_list(self):
        es = ExecutiveSummarySection()
        assert isinstance(es.current_pain_points, list)

    def test_poc_objectives_is_list(self):
        es = ExecutiveSummarySection()
        assert isinstance(es.poc_objectives, list)


# ---------------------------------------------------------------------------
# 20. Two DocumentState() instances have independent mutable lists
# ---------------------------------------------------------------------------

class TestIndependentMutableDefaults:
    def test_independent_blocking_issues(self):
        doc1 = DocumentState()
        doc2 = DocumentState()
        doc1.blocking_issues.append({"code": "TEST"})
        assert len(doc2.blocking_issues) == 0

    def test_independent_section_lists(self):
        doc1 = DocumentState()
        doc2 = DocumentState()
        doc1.sections.stakeholders.executive_sponsors.append(
            ContactEntry(name=FieldValue(user_input="Test"))
        )
        assert len(doc2.sections.stakeholders.executive_sponsors) == 0

    def test_independent_phases_overview(self):
        doc1 = DocumentState()
        doc2 = DocumentState()
        doc1.sections.executive_summary.phases_overview.append(
            FieldValue(user_input="Phase 1")
        )
        assert len(doc2.sections.executive_summary.phases_overview) == 0


# ---------------------------------------------------------------------------
# 21. CoverSection allows extra fields; other sections forbid extra fields
# ---------------------------------------------------------------------------

class TestExtraFieldsBehavior:
    def test_cover_section_allows_extra(self):
        # Should not raise
        cover = CoverSection(dynamic_field="some value")
        assert cover.dynamic_field == "some value"

    def test_executive_summary_forbids_extra(self):
        with pytest.raises(Exception):
            ExecutiveSummarySection(unknown_field="bad")

    def test_architecture_forbids_extra(self):
        with pytest.raises(Exception):
            ArchitectureSection(unknown_field="bad")

    def test_acceptance_forbids_extra(self):
        with pytest.raises(Exception):
            AcceptanceSection(unknown_field="bad")

    def test_cost_breakdown_forbids_extra(self):
        with pytest.raises(Exception):
            CostBreakdownSection(unknown_field="bad")

    def test_stakeholders_forbids_extra(self):
        with pytest.raises(Exception):
            StakeholdersSection(unknown_field="bad")

    def test_success_criteria_forbids_extra(self):
        with pytest.raises(Exception):
            SuccessCriteriaSection(unknown_field="bad")

    def test_assumptions_forbids_extra(self):
        with pytest.raises(Exception):
            AssumptionsSection(unknown_field="bad")

    def test_scope_of_work_forbids_extra(self):
        with pytest.raises(Exception):
            ScopeOfWorkSection(unknown_field="bad")

    def test_resources_cost_estimates_forbids_extra(self):
        with pytest.raises(Exception):
            ResourcesCostEstimatesSection(unknown_field="bad")
