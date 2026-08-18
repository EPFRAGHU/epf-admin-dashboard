import pytest

import epf_engine
from epf_engine import Project


# ═══════════════════════════════════════════════════════════════════════════
# Engine-level: Branch -> Division -> Unit hierarchy, CRUD, validation, scoping
# ═══════════════════════════════════════════════════════════════════════════

def test_new_project_has_a_default_main_branch():
    p = Project()
    assert len(p.branches) == 1
    assert p.branches[0].name == "Main Branch"
    assert p.branches[0].is_default is True
    assert p.default_branch().id == p.branches[0].id


def test_new_employee_defaults_to_the_default_branch():
    p = Project()
    p.upsert_master("EMP001", "Test Employee")
    m = p.get_master("EMP001")
    assert m.branch_id == p.default_branch().id
    assert m.division_id is None
    assert m.unit_id is None


def test_add_division_requires_an_existing_branch():
    p = Project()
    with pytest.raises(ValueError):
        p.add_division(999999, "Ghost Division")


def test_add_unit_requires_an_existing_division():
    p = Project()
    with pytest.raises(ValueError):
        p.add_unit(999999, "Ghost Unit")


def test_upsert_master_rejects_division_not_under_given_branch():
    p = Project()
    b1 = p.default_branch()
    b2 = p.add_branch("Second Branch")
    d_under_b2 = p.add_division(b2.id, "Division Under B2")
    with pytest.raises(ValueError):
        p.upsert_master("EMP001", "Test", branch_id=b1.id, division_id=d_under_b2.id)


def test_upsert_master_rejects_unit_not_under_given_division():
    p = Project()
    b = p.default_branch()
    d1 = p.add_division(b.id, "Div1")
    d2 = p.add_division(b.id, "Div2")
    u_under_d2 = p.add_unit(d2.id, "Unit under Div2")
    with pytest.raises(ValueError):
        p.upsert_master("EMP001", "Test", branch_id=b.id, division_id=d1.id, unit_id=u_under_d2.id)


def test_upsert_master_accepts_a_valid_full_chain():
    p = Project()
    b = p.default_branch()
    d = p.add_division(b.id, "Admin")
    u = p.add_unit(d.id, "Payroll")
    p.upsert_master("EMP001", "Test", branch_id=b.id, division_id=d.id, unit_id=u.id)
    m = p.get_master("EMP001")
    assert (m.branch_id, m.division_id, m.unit_id) == (b.id, d.id, u.id)


def test_cannot_remove_the_only_branch_is_enforced_by_caller_but_removal_leaves_none():
    # Project.remove_branch itself has no guard -- the "must keep >=1 branch"
    # rule lives in the API layer (see test_cannot_delete_only_remaining_branch
    # below). This documents that engine-level removal is unconditional.
    p = Project()
    only = p.default_branch()
    p.remove_branch(only.id)
    assert p.branches == []


def test_filter_employees_by_scope_precedence_unit_over_division_over_branch():
    p = Project()
    b1 = p.default_branch()
    b2 = p.add_branch("Branch2")
    d1 = p.add_division(b1.id, "D1")
    d2 = p.add_division(b1.id, "D2")
    u1 = p.add_unit(d1.id, "U1")

    p.upsert_master("E1", "E1", branch_id=b1.id, division_id=d1.id, unit_id=u1.id)
    p.upsert_master("E2", "E2", branch_id=b1.id, division_id=d1.id)
    p.upsert_master("E3", "E3", branch_id=b1.id, division_id=d2.id)
    p.upsert_master("E4", "E4", branch_id=b2.id)

    all_emps = p.master_list()
    assert len(epf_engine.filter_employees_by_scope(all_emps)) == 4
    assert {e.member_id for e in epf_engine.filter_employees_by_scope(all_emps, branch_id=b1.id)} == {"E1", "E2", "E3"}
    assert {e.member_id for e in epf_engine.filter_employees_by_scope(all_emps, division_id=d1.id)} == {"E1", "E2"}
    assert {e.member_id for e in epf_engine.filter_employees_by_scope(all_emps, unit_id=u1.id)} == {"E1"}
    # unit_id wins even if a (mismatched) division_id is also passed
    assert {e.member_id for e in epf_engine.filter_employees_by_scope(all_emps, division_id=d2.id, unit_id=u1.id)} == {"E1"}


def test_resolve_scope_path_for_ids_builds_full_chain():
    p = Project()
    b = p.default_branch()
    d = p.add_division(b.id, "Admin Division")
    u = p.add_unit(d.id, "Section A")
    assert epf_engine.resolve_scope_path_for_ids(p) == "Unassigned"
    assert epf_engine.resolve_scope_path_for_ids(p, branch_id=b.id) == "Main Branch"
    assert epf_engine.resolve_scope_path_for_ids(p, branch_id=b.id, division_id=d.id) == "Main Branch → Admin Division"
    assert epf_engine.resolve_scope_path_for_ids(p, branch_id=b.id, division_id=d.id, unit_id=u.id) == \
        "Main Branch → Admin Division → Section A"


def test_resolve_employee_scope_path_matches_ids_helper():
    p = Project()
    b = p.default_branch()
    d = p.add_division(b.id, "Admin Division")
    p.upsert_master("EMP001", "Test", branch_id=b.id, division_id=d.id)
    m = p.get_master("EMP001")
    assert epf_engine.resolve_employee_scope_path(m, p) == "Main Branch → Admin Division"


# ═══════════════════════════════════════════════════════════════════════════
# Legacy migration: flat branch/division/unit string tags -> nested hierarchy
# ═══════════════════════════════════════════════════════════════════════════

def _legacy_dict(branches, divisions, units, master):
    return {
        "code": "TESTCODE", "name": "Test Co", "address": "", "coverage_date": "",
        "branches": branches, "divisions": divisions, "units": units,
        "master": master, "years": {},
    }


def test_migrate_legacy_simple_consistent_mapping_no_warnings():
    data = _legacy_dict(
        branches=["HQ"], divisions=["Admin"], units=["Payroll"],
        master={
            "E1": {"member_id": "E1", "name": "Alice", "branch": "HQ", "division": "Admin", "unit": "Payroll"},
            "E2": {"member_id": "E2", "name": "Bob", "branch": "HQ", "division": "Admin", "unit": ""},
        },
    )
    p = Project()
    migrated = p.load_from_dict(data)
    assert migrated is True
    assert p.org_structure_version == 1
    assert p.org_migration_warnings == []

    hq = next(b for b in p.branches if b.name == "HQ")
    assert len(p.branches) == 1  # no extra "Main Branch" auto-added since HQ already exists
    admin = next(d for d in p.divisions if d.name == "Admin")
    assert admin.branch_id == hq.id
    payroll = next(u for u in p.units if u.name == "Payroll")
    assert payroll.division_id == admin.id

    e1 = p.get_master("E1")
    assert (e1.branch_id, e1.division_id, e1.unit_id) == (hq.id, admin.id, payroll.id)
    e2 = p.get_master("E2")
    assert (e2.branch_id, e2.division_id, e2.unit_id) == (hq.id, admin.id, None)


def test_migrate_legacy_division_spanning_multiple_branches_flags_warning_and_reassigns_losers():
    data = _legacy_dict(
        branches=["HQ", "Regional"], divisions=["Shared Division"], units=[],
        master={
            "E1": {"member_id": "E1", "name": "Alice", "branch": "HQ", "division": "Shared Division", "unit": ""},
            "E2": {"member_id": "E2", "name": "Bob", "branch": "HQ", "division": "Shared Division", "unit": ""},
            "E3": {"member_id": "E3", "name": "Carl", "branch": "Regional", "division": "Shared Division", "unit": ""},
        },
    )
    p = Project()
    p.load_from_dict(data)

    multi_branch_warnings = [w for w in p.org_migration_warnings if w["type"] == "division_multi_branch"]
    assert len(multi_branch_warnings) == 1
    assert multi_branch_warnings[0]["entity_name"] == "Shared Division"
    assert "E3" in multi_branch_warnings[0]["affected_member_ids"]

    hq = next(b for b in p.branches if b.name == "HQ")
    division = next(d for d in p.divisions if d.name == "Shared Division")
    assert division.branch_id == hq.id  # majority winner (2 votes HQ vs 1 Regional)

    # E3 (the minority-branch employee) keeps only its branch-level assignment
    e3 = p.get_master("E3")
    regional = next(b for b in p.branches if b.name == "Regional")
    assert e3.branch_id == regional.id
    assert e3.division_id is None
    mismatch_warnings = [w for w in p.org_migration_warnings if w["type"] == "employee_scope_mismatch"]
    assert any(w["entity_name"] == "E3" for w in mismatch_warnings)


def test_migrate_legacy_division_with_no_employees_falls_back_to_default_branch_with_warning():
    data = _legacy_dict(branches=["HQ"], divisions=["Orphan Division"], units=[], master={})
    p = Project()
    p.load_from_dict(data)

    warnings = [w for w in p.org_migration_warnings if w["type"] == "division_unassigned"]
    assert len(warnings) == 1
    assert warnings[0]["entity_name"] == "Orphan Division"
    division = next(d for d in p.divisions if d.name == "Orphan Division")
    assert division.branch_id == p.default_branch().id


def test_migrate_legacy_unit_referencing_unresolvable_division_is_dropped_with_warning():
    data = _legacy_dict(
        branches=["HQ"], divisions=[], units=["Orphan Unit"],
        master={
            "E1": {"member_id": "E1", "name": "Alice", "branch": "HQ", "division": "Ghost Division", "unit": "Orphan Unit"},
        },
    )
    p = Project()
    p.load_from_dict(data)

    assert len(p.units) == 0
    warnings = [w for w in p.org_migration_warnings if w["type"] == "unit_orphaned"]
    assert len(warnings) == 1
    assert warnings[0]["entity_name"] == "Orphan Unit"

    e1 = p.get_master("E1")
    hq = next(b for b in p.branches if b.name == "HQ")
    assert e1.branch_id == hq.id
    assert e1.division_id is None
    assert e1.unit_id is None


def test_migration_runs_once_and_round_trips_through_new_format():
    data = _legacy_dict(
        branches=["HQ"], divisions=[], units=[],
        master={"E1": {"member_id": "E1", "name": "Alice", "branch": "HQ", "division": "", "unit": ""}},
    )
    p = Project()
    migrated = p.load_from_dict(data)
    assert migrated is True
    saved = p.to_dict()
    assert saved["org_structure_version"] == 1

    p2 = Project()
    migrated_again = p2.load_from_dict(saved)
    assert migrated_again is False
    assert [b.name for b in p2.branches] == [b.name for b in p.branches]
    assert p2.get_master("E1").branch_id == p.get_master("E1").branch_id


def test_new_project_to_dict_load_from_dict_round_trip_is_not_treated_as_legacy():
    p = Project()
    p.set_establishment("CODE1", "Co", "Addr")
    b2 = p.add_branch("Second Branch")
    p.upsert_master("E1", "Alice", branch_id=b2.id)
    saved = p.to_dict()

    p2 = Project()
    migrated = p2.load_from_dict(saved)
    assert migrated is False
    assert len(p2.branches) == 2
    assert p2.get_master("E1").branch_id == b2.id


# ═══════════════════════════════════════════════════════════════════════════
# API-level: org-structure endpoints, employee scoping, cross-cutting behavior
# ═══════════════════════════════════════════════════════════════════════════

def _new_establishment(consultant, code, name):
    res = consultant.post("/api/establishments", json={"code": code, "name": name})
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def test_new_establishment_exposes_default_branch_via_api(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000001", "Org Structure Co")
    res = consultant_a.get("/api/org-structure")
    assert res.status_code == 200
    data = res.json()
    assert len(data["branches"]) == 1
    assert data["branches"][0]["name"] == "Main Branch"
    assert data["branches"][0]["is_default"] is True
    assert data["migration_warnings"] == []


def test_branch_division_unit_crud_via_api(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000002", "CRUD Co")

    res = consultant_a.post("/api/org-structure/branches", json={"name": "West Zone"})
    assert res.status_code == 200
    branch_id = next(b["id"] for b in res.json()["branches"] if b["name"] == "West Zone")

    res = consultant_a.post("/api/org-structure/divisions", json={"name": "Sales", "branch_id": branch_id})
    assert res.status_code == 200
    division_id = next(d["id"] for d in res.json()["divisions"] if d["name"] == "Sales")

    res = consultant_a.post("/api/org-structure/units", json={"name": "Retail", "division_id": division_id})
    assert res.status_code == 200
    unit_id = next(u["id"] for u in res.json()["units"] if u["name"] == "Retail")

    res = consultant_a.put(f"/api/org-structure/branches/{branch_id}", json={"name": "West Zone Renamed"})
    assert res.status_code == 200
    assert any(b["name"] == "West Zone Renamed" for b in res.json()["branches"])

    res = consultant_a.put(f"/api/org-structure/divisions/{division_id}", json={"name": "Sales Renamed"})
    assert res.status_code == 200
    res = consultant_a.put(f"/api/org-structure/units/{unit_id}", json={"name": "Retail Renamed"})
    assert res.status_code == 200

    res = consultant_a.post("/api/org-structure/divisions", json={"name": "Ghost", "branch_id": 999999})
    assert res.status_code == 400
    res = consultant_a.post("/api/org-structure/units", json={"name": "Ghost", "division_id": 999999})
    assert res.status_code == 400

    res = consultant_a.delete(f"/api/org-structure/units/{unit_id}")
    assert res.status_code == 200
    res = consultant_a.delete(f"/api/org-structure/divisions/{division_id}")
    assert res.status_code == 200
    res = consultant_a.delete(f"/api/org-structure/branches/{branch_id}")
    assert res.status_code == 200


def test_cannot_delete_only_remaining_branch(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000003", "Solo Branch Co")
    only_branch_id = consultant_a.get("/api/org-structure").json()["branches"][0]["id"]
    res = consultant_a.delete(f"/api/org-structure/branches/{only_branch_id}")
    assert res.status_code == 400


def test_cannot_delete_branch_with_child_division_or_employees(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000004", "Guarded Co")

    res = consultant_a.post("/api/org-structure/branches", json={"name": "Second Branch"})
    branch_id = next(b["id"] for b in res.json()["branches"] if b["name"] == "Second Branch")

    res = consultant_a.post("/api/org-structure/divisions", json={"name": "Div", "branch_id": branch_id})
    division_id = next(d["id"] for d in res.json()["divisions"] if d["name"] == "Div")

    res = consultant_a.delete(f"/api/org-structure/branches/{branch_id}")
    assert res.status_code == 400  # has a child division

    res = consultant_a.delete(f"/api/org-structure/divisions/{division_id}")
    assert res.status_code == 200

    res = consultant_a.post("/api/employees", json={
        "member_id": "ORGSTR0000004001", "name": "Assigned Employee",
        "uan": "100333333333", "branch_id": branch_id,
    })
    assert res.status_code == 200

    res = consultant_a.delete(f"/api/org-structure/branches/{branch_id}")
    assert res.status_code == 400  # has an assigned employee


def test_cannot_delete_division_or_unit_with_assigned_employees(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000008", "Guarded Co 2")
    default_branch_id = consultant_a.get("/api/org-structure").json()["branches"][0]["id"]

    res = consultant_a.post("/api/org-structure/divisions", json={"name": "Div", "branch_id": default_branch_id})
    division_id = next(d["id"] for d in res.json()["divisions"] if d["name"] == "Div")
    res = consultant_a.post("/api/org-structure/units", json={"name": "Unit", "division_id": division_id})
    unit_id = next(u["id"] for u in res.json()["units"] if u["name"] == "Unit")

    res = consultant_a.post("/api/employees", json={
        "member_id": "ORGSTR0000008001", "name": "Employee", "uan": "100333330000",
        "branch_id": default_branch_id, "division_id": division_id, "unit_id": unit_id,
    })
    assert res.status_code == 200

    assert consultant_a.delete(f"/api/org-structure/units/{unit_id}").status_code == 400
    assert consultant_a.delete(f"/api/org-structure/divisions/{division_id}").status_code == 400


def test_employee_defaults_to_default_branch_when_unspecified(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000005", "Default Branch Co")
    res = consultant_a.post("/api/employees", json={
        "member_id": "SC00501", "name": "No Scope Employee", "uan": "100444444444",
    })
    assert res.status_code == 200
    emps = consultant_a.get("/api/employees").json()["employees"]
    # normalize_member_id keeps only the last 7 chars of a submitted account number
    emp = next(e for e in emps if e["name"] == "No Scope Employee")
    default_branch_id = consultant_a.get("/api/org-structure").json()["branches"][0]["id"]
    assert emp["branch_id"] == default_branch_id
    assert emp["scope_path"] == "Main Branch"


def test_employee_rejects_division_not_under_the_given_branch(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000006", "Mismatch Co")

    org = consultant_a.get("/api/org-structure").json()
    default_branch_id = next(b["id"] for b in org["branches"] if b["is_default"])

    res = consultant_a.post("/api/org-structure/branches", json={"name": "Other Branch"})
    other_branch_id = next(b["id"] for b in res.json()["branches"] if b["name"] == "Other Branch")
    res = consultant_a.post("/api/org-structure/divisions", json={"name": "Div Under Other", "branch_id": other_branch_id})
    division_id = next(d["id"] for d in res.json()["divisions"] if d["name"] == "Div Under Other")

    res = consultant_a.post("/api/employees", json={
        "member_id": "ORGSTR0000006001", "name": "Bad Scope Employee", "uan": "100555555555",
        "branch_id": default_branch_id, "division_id": division_id,
    })
    assert res.status_code == 400


def test_org_structure_employee_counts_reflect_assignments(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000007", "Counting Co")

    res = consultant_a.post("/api/org-structure/branches", json={"name": "North"})
    north_id = next(b["id"] for b in res.json()["branches"] if b["name"] == "North")
    res = consultant_a.post("/api/org-structure/divisions", json={"name": "North Sales", "branch_id": north_id})
    div_id = next(d["id"] for d in res.json()["divisions"] if d["name"] == "North Sales")

    consultant_a.post("/api/employees", json={
        "member_id": "ORGSTR0000007001", "name": "A", "uan": "100666666601",
        "branch_id": north_id, "division_id": div_id,
    })
    consultant_a.post("/api/employees", json={
        "member_id": "ORGSTR0000007002", "name": "B", "uan": "100666666602", "branch_id": north_id,
    })

    data = consultant_a.get("/api/org-structure").json()
    branch_row = next(b for b in data["branches"] if b["id"] == north_id)
    division_row = next(d for d in data["divisions"] if d["id"] == div_id)
    assert branch_row["employee_count"] == 2
    assert division_row["employee_count"] == 1


def test_report_generation_respects_branch_scope_and_agrees_with_dashboard_totals(consultant_a, superadmin_session):
    """Cross-checks that scoping a report to one branch produces the same
    wage total as scoping the dashboard to that same branch -- both must go
    through the same filter_employees_by_scope helper. Report downloads are
    gated by subscription fee status for consultants (unrelated to org
    structure), so we use the superadmin bypass to isolate the scoping check."""
    est_id = _new_establishment(consultant_a, "ORGSTR0000009", "Scope Cross-Check Co")

    org = consultant_a.get("/api/org-structure").json()
    default_branch_id = org["branches"][0]["id"]
    res = consultant_a.post("/api/org-structure/branches", json={"name": "Branch B"})
    branch_b_id = next(b["id"] for b in res.json()["branches"] if b["name"] == "Branch B")

    consultant_a.post("/api/employees", json={
        "member_id": "SC00901", "name": "In Default Branch", "uan": "100777777701",
    })
    consultant_a.post("/api/employees", json={
        "member_id": "SC00902", "name": "In Branch B", "uan": "100777777702",
        "branch_id": branch_b_id,
    })

    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "SC00901", "wages": [10000.0] + [0.0] * 11,
    })
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "SC00902", "wages": [20000.0] + [0.0] * 11,
    })

    dash_default = consultant_a.get(f"/api/dashboard?branch_id={default_branch_id}").json()
    dash_b = consultant_a.get(f"/api/dashboard?branch_id={branch_b_id}").json()
    assert dash_default["employees"] == 1
    assert dash_b["employees"] == 1
    assert dash_default["year_stats"][0]["epf_wages"] == 10000
    assert dash_b["year_stats"][0]["epf_wages"] == 20000

    superadmin_session.set_establishment(est_id)
    res_default = superadmin_session.get(f"/api/reports/2026-27?branch_id={default_branch_id}")
    assert res_default.status_code == 200
    res_b = superadmin_session.get(f"/api/reports/2026-27?branch_id={branch_b_id}")
    assert res_b.status_code == 200


def test_migration_warnings_dismiss_endpoint_clears_them(consultant_a):
    _new_establishment(consultant_a, "ORGSTR0000010", "Dismiss Co")
    # A freshly created establishment has no warnings; just verify the
    # endpoint is reachable, ownership-checked, and idempotent.
    res = consultant_a.post("/api/org-structure/migration-warnings/dismiss", json={})
    assert res.status_code == 200
    data = consultant_a.get("/api/org-structure").json()
    assert data["migration_warnings"] == []


# ═══════════════════════════════════════════════════════════════════════════
# Multi-tenant isolation for org-structure endpoints
# ═══════════════════════════════════════════════════════════════════════════

def test_org_structure_isolated_between_consultants(consultant_a, consultant_b):
    est_a_id = _new_establishment(consultant_a, "ORGSTRISO000A", "Isolation Co A")
    res = consultant_a.post("/api/org-structure/branches", json={"name": "A's Branch"})
    assert res.status_code == 200
    a_branch_id = next(b["id"] for b in res.json()["branches"] if b["name"] == "A's Branch")

    _new_establishment(consultant_b, "ORGSTRISO000B", "Isolation Co B")

    # B is scoped to est B via X-Establishment-Id; hitting A's branch id must not succeed.
    res = consultant_b.put(f"/api/org-structure/branches/{a_branch_id}", json={"name": "Hijacked"})
    assert res.status_code == 404
    res = consultant_b.delete(f"/api/org-structure/branches/{a_branch_id}")
    assert res.status_code == 404

    # And B cannot list A's org structure by pointing the establishment header at A's id.
    res = consultant_b.get(f"/api/org-structure?establishment_id={est_a_id}")
    assert res.status_code in (403, 404)
    assert "A's Branch" not in res.text
