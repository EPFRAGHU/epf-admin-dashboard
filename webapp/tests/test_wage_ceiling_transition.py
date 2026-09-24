"""Wage ceiling 15,000 -> 25,000, effective 17 Sep 2026 (S.O. 5109(E)).

The three transition-month scenarios below are the official EPFO FAQ worked examples
for an employee with September 2026 EPF wages of Rs 20,000; the expected figures are
exact, not estimates. FY 2026 wage-month index 6 is September (idx 0 = March).
"""
from datetime import date

from epf_engine import (
    CEILING_CHANGES,
    Employee,
    default_wage_ceilings,
    get_wage_ceiling,
    get_wage_ceilings_for_year,
)

RATES = (12.0, 0.0, 3.67, 8.33)  # post-1997: EE EPF, EE EPS, ER EPF, ER EPS
SEP = 6


def _emp(wage=20000, month=SEP, year_from="2026", **kw):
    wages = [0] * 12
    wages[month] = wage
    return Employee(member_id="T1", name="T", wages=wages, gross_wages=list(wages),
                    year_from=year_from, **kw)


def _ceil(year_from="2026"):
    return get_wage_ceilings_for_year(year_from)


# ---------------------------------------------------------------- ceiling schedule

def test_change_table_holds_the_2026_ceiling():
    assert (date(2026, 9, 17), 25000.0) in CEILING_CHANGES


def test_september_2026_straddles_and_splits_16_14():
    c = _ceil()[SEP]
    assert [(s, d, v) for s, d, v in c.segments] == [
        (date(2026, 9, 1), 16, 15000.0), (date(2026, 9, 17), 14, 25000.0)]
    assert float(c) == 25000.0  # ceiling in force at END of month


def test_august_2026_is_15000_single_segment():
    c = _ceil()[SEP - 1]
    assert float(c) == 15000.0 and len(c.segments) == 1


def test_october_2026_onward_is_25000_single_segment_no_proration():
    for idx in range(SEP + 1, 12):
        c = _ceil()[idx]
        assert float(c) == 25000.0 and len(c.segments) == 1, idx


def test_fy2027_all_25000():
    assert all(float(c) == 25000.0 and len(c.segments) == 1 for c in _ceil("2027"))


def test_history_unchanged_legacy_tiers_preserved():
    for yf in ("1985", "1995", "2005", "2012", "2014", "2020", "2025"):
        assert [float(c) for c in get_wage_ceilings_for_year(yf)] == [
            get_wage_ceiling(i, yf) for i in range(12)], yf
        assert all(len(c.segments) == 1 for c in get_wage_ceilings_for_year(yf)), yf


def test_default_ceilings_keep_legacy_15000_for_every_old_year():
    for yf in ("1999", "2005", "2012", "2025", ""):
        assert [float(c) for c in default_wage_ceilings(yf)] == [15000.0] * 12, yf


def test_default_ceilings_pick_up_the_new_ceiling_from_the_change():
    d = default_wage_ceilings("2026")
    assert float(d[SEP - 1]) == 15000.0
    assert float(d[SEP]) == 25000.0 and len(d[SEP].segments) == 2
    assert all(float(c) == 25000.0 for c in d[SEP + 1:])


# ---------------------------------------------------------- official FAQ scenarios

def test_scenario_a_newly_covered_from_17_sep():
    e = _emp(epf_from="17-09-2026", eps_from="17-09-2026")
    p1, p2 = e.wage_bases_by_period(SEP, 20000, _ceil()[SEP])
    assert (p1.epf, p1.eps) == (0, 0)
    assert round(p2.epf, 2) == 9333.33 and round(p2.eps, 2) == 9333.33
    b = e.wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.epf, 2) == 9333.33 and round(b.eps, 2) == 9333.33
    row = e.month_rows(*RATES, wage_ceilings=_ceil())[SEP]
    assert row[1] == 1120  # EE EPF = 12% of the TOTAL 9,333.33


def test_scenario_b_higher_epf_existing_member_eps_from_17_sep():
    e = _emp(higher_epf_ee=True, higher_epf_er=True, eps_from="17-09-2026")
    b = e.wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.epf, 2) == 20000.00
    assert round(b.eps, 2) == 9333.33
    p1, p2 = e.wage_bases_by_period(SEP, 20000, _ceil()[SEP])
    assert p1.eps == 0 and round(p2.eps, 2) == 9333.33
    row = e.month_rows(*RATES, wage_ceilings=_ceil())[SEP]
    assert row[1] == 2400


def test_scenario_c_existing_member_capped_then_actual():
    e = _emp()
    p1, p2 = e.wage_bases_by_period(SEP, 20000, _ceil()[SEP])
    assert round(p1.epf, 2) == 8000.00 and round(p2.epf, 2) == 9333.33
    b = e.wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.epf, 2) == 17333.33 and round(b.eps, 2) == 17333.33
    row = e.month_rows(*RATES, wage_ceilings=_ceil())[SEP]
    assert row[1] == 2080


def test_rates_applied_once_to_combined_totals_not_per_period():
    """ER total = round(12% of the combined base); pension = round(8.33% of the
    combined EPS base); ER EPF is the remainder -- never a sum of per-period rounds."""
    row = _emp().month_rows(*RATES, wage_ceilings=_ceil())[SEP]
    _, w_epf, _, _, e_epf, e_eps, e_total = row
    assert w_epf == round(17333.3333 * 12 / 100)
    assert e_eps == round(17333.3333 * 8.33 / 100)
    assert e_epf + e_eps == w_epf  # employer total 12% == employee 12%


# ------------------------------------------------------------- non-transition months

def test_august_2026_is_capped_at_15000_no_proration():
    e = _emp(wage=20000, month=SEP - 1)
    b = e.wage_bases(SEP - 1, 20000, _ceil()[SEP - 1])
    assert (b.epf, b.eps, b.edli) == (15000.0, 15000.0, 15000.0)
    assert e.month_rows(*RATES, wage_ceilings=_ceil())[SEP - 1][1] == 1800


def test_october_2026_is_capped_at_25000_no_proration():
    e = _emp(wage=30000, month=SEP + 1)
    b = e.wage_bases(SEP + 1, 30000, _ceil()[SEP + 1])
    assert (b.epf, b.eps, b.edli) == (25000.0, 25000.0, 25000.0)
    assert e.month_rows(*RATES, wage_ceilings=_ceil())[SEP + 1][1] == 3000


def test_default_path_used_by_the_forms_matches_explicit_ceilings():
    """Form 3A/6A/12A and several PDFs call month_rows() with NO ceilings -- that
    default must carry the new ceiling too or those forms silently stay at 15,000."""
    for month, wage in ((SEP - 1, 20000), (SEP, 20000), (SEP + 1, 30000)):
        e = _emp(wage=wage, month=month)
        assert e.month_rows(*RATES)[month] == e.month_rows(*RATES, wage_ceilings=_ceil())[month]


def test_history_month_rows_identical_with_and_without_year_from():
    """Byte-identical guard: pre-change years compute exactly as before."""
    for yf in ("2005", "2014", "2025"):
        for wage in (9000, 15000, 20000, 60000):
            wages = [wage] * 12
            new = Employee(wages=wages, year_from=yf).month_rows(*RATES)
            old = Employee(wages=wages).month_rows(*RATES, wage_ceilings=[15000.0] * 12)
            assert new == old, (yf, wage)


# --------------------------------------------------------------- eligibility dates

def test_blank_or_garbage_eligibility_dates_never_zero_anything():
    for bad in ("", "not-a-date", "31-02-2026"):
        b = _emp(epf_from=bad, eps_from=bad).wage_bases(SEP, 20000, _ceil()[SEP])
        assert round(b.epf, 2) == 17333.33 and round(b.eps, 2) == 17333.33, bad


def test_epf_from_after_the_whole_month_zeroes_it():
    e = _emp(month=SEP + 1, epf_from="01-11-2026")
    b = e.wage_bases(SEP + 1, 20000, _ceil()[SEP + 1])
    assert b.epf == 0 and b.eps == 0 and b.edli == 0


def test_eps_from_never_zeroes_epf():
    b = _emp(eps_from="01-01-2030").wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.epf, 2) == 17333.33 and b.eps == 0


def test_age_58_and_non_member_still_zero_eps_in_transition_month():
    e = _emp(dob="01-01-1960")  # 58 well before Sep 2026
    b = e.wage_bases(SEP, 20000, _ceil()[SEP])
    assert b.eps == 0 and round(b.epf, 2) == 17333.33
    e2 = _emp(eps_member=False)
    assert e2.wage_bases(SEP, 20000, _ceil()[SEP]).eps == 0


def test_edli_wage_is_prorated_capped_and_not_age_zeroed():
    b = _emp(dob="01-01-1960").wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.edli, 2) == 17333.33


def test_edli_wage_ignores_higher_epf():
    b = _emp(higher_epf_ee=True, higher_epf_er=True).wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.epf, 2) == 20000.00 and round(b.edli, 2) == 17333.33


def test_pohw_eps_on_full_wage_prorated_by_eligible_days():
    e = _emp(pohw=True, eps_from="17-09-2026")
    b = e.wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.eps, 2) == round(20000 * 14 / 30, 2)


# ---------------------------------------------------------------- API / ECR level

def _wages_for(idx_to_wage):
    w = [0.0] * 12
    for i, v in idx_to_wage.items():
        w[i] = float(v)
    return w


def _seed_transition_establishment(consultant_a, test_db, code):
    import json
    from epf_engine import Project
    from webapp.database import Establishment
    from webapp.auth import save_establishment_project

    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": code, "name": f"{code} Co"})
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    people = [
        # (member, uan, extra employee fields)                       FAQ scenario
        ("TRA0001", "100900000031", {"epf_from": "17-09-2026", "eps_from": "17-09-2026"}),  # A
        ("TRB0001", "100900000032", {"higher_epf_ee": True, "higher_epf_er": True,
                                     "eps_from": "17-09-2026"}),                              # B
        ("TRC0001", "100900000033", {}),                                                      # C
    ]
    for mid, uan, extra in people:
        res = consultant_a.post("/api/employees", json={
            "member_id": mid, "name": f"Scenario {mid}", "uan": uan, **extra})
        assert res.status_code == 200, res.text
    est_obj = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    project = Project()
    project.load_from_dict(json.loads(est_obj.data))
    for mid, _, _ in people:
        project.upsert_entry("2026-27", mid, _wages_for({5: 20000, 6: 20000, 7: 30000}))
    save_establishment_project(test_db, est_obj, project)
    return est_id


def _ecr_by_uan(session, est_id, month_idx):
    session.set_establishment(est_id)
    res = session.get(f"/api/reports/2026-27/ecr/{month_idx}")
    assert res.status_code == 200, res.text
    return {ln.split("#~#")[0]: ln.split("#~#") for ln in res.text.strip().splitlines()}


def test_ecr_september_2026_matches_the_three_official_scenarios(consultant_a, superadmin_session, test_db):
    est_id = _seed_transition_establishment(consultant_a, test_db, "TRANS001")
    ecr = _ecr_by_uan(superadmin_session, est_id, 6)
    # UAN#~#Name#~#Gross#~#EPF#~#EPS#~#EDLI#~#EE#~#EPS_share#~#ER_EPF#~#NCP#~#Refund
    a, b, c = ecr["100900000031"], ecr["100900000032"], ecr["100900000033"]
    assert (a[3], a[4], a[5], a[6]) == ("9333", "9333", "9333", "1120")
    assert (b[3], b[4], b[5], b[6]) == ("20000", "9333", "17333", "2400")
    assert (c[3], c[4], c[5], c[6]) == ("17333", "17333", "17333", "2080")
    for f in (a, b, c):
        assert int(f[6]) == int(f[7]) + int(f[8])  # EE 12% == pension + ER EPF


def test_ecr_august_and_october_2026_use_one_ceiling_no_proration(consultant_a, superadmin_session, test_db):
    est_id = _seed_transition_establishment(consultant_a, test_db, "TRANS002")
    aug = _ecr_by_uan(superadmin_session, est_id, 5)["100900000033"]
    assert (aug[3], aug[4], aug[5], aug[6]) == ("20000", "15000", "15000", "1800")
    octo = _ecr_by_uan(superadmin_session, est_id, 7)["100900000033"]
    assert (octo[3], octo[4], octo[5], octo[6]) == ("30000", "25000", "25000", "3000")


def test_get_wages_exposes_ceiling_segments_and_coverage_dates(consultant_a, test_db):
    est_id = _seed_transition_establishment(consultant_a, test_db, "TRANS003")
    data = consultant_a.get("/api/years/2026-27/wages").json()
    rates = data["rates"]
    assert rates["wage_ceilings"][5] == 15000 and rates["wage_ceilings"][6] == 25000
    assert rates["wage_ceiling_segments"][6] == [["2026-09-01", 16, 15000.0], ["2026-09-17", 14, 25000.0]]
    assert rates["wage_ceiling_segments"][7] == [["2026-10-01", 31, 25000.0]]
    a = next(e for e in data["employees"] if e["member_id"] == "TRA0001")
    assert (a["epf_from"], a["eps_from"]) == ("17-09-2026", "17-09-2026")
    a_sep = a["months"][6]
    assert a_sep["we"] == 1120  # engine's EE EPF for the transition month


def test_employee_coverage_dates_validated_and_normalized(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "TRANS004", "name": "Coverage Date Co"})
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    bad = consultant_a.post("/api/employees", json={
        "member_id": "CDV0001", "name": "Bad Date", "epf_from": "not a date"})
    assert bad.status_code == 400
    ok = consultant_a.post("/api/employees", json={
        "member_id": "CDV0002", "name": "Alt Format", "epf_from": "17-SEP-2026", "eps_from": ""})
    assert ok.status_code == 200, ok.text
    emp = next(e for e in consultant_a.get("/api/employees").json()["employees"] if e["member_id"] == "CDV0002")
    assert emp["epf_from"] == "17-09-2026" and emp["eps_from"] == ""


def test_upsert_master_update_without_coverage_dates_preserves_them():
    from epf_engine import Project, MasterEmployee
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Emp", epf_from="17-09-2026", eps_from="17-09-2026")
    p.upsert_master("M1", "Emp", father_name="F")       # importer-style: says nothing about them
    assert (p.master["M1"].epf_from, p.master["M1"].eps_from) == ("17-09-2026", "17-09-2026")
    p.upsert_master("M1", "Emp", epf_from="")            # explicit clear
    assert p.master["M1"].epf_from == "" and p.master["M1"].eps_from == "17-09-2026"
    again = MasterEmployee.from_dict(p.master["M1"].to_dict())
    assert again.eps_from == "17-09-2026"
    assert MasterEmployee.from_dict({"member_id": "OLD0001", "name": "Legacy"}).epf_from == ""


# -------------------------------------------------- half-up rounding at the new ceiling

def test_pension_at_25000_is_2083_half_up_and_er_pf_917():
    """8.33% of 25,000 = 2082.5. EPFO rounds 50 paise up (2083); Python's round() would
    give 2082. From Oct 2026 every employee at/above the ceiling lands on this value."""
    e = _emp(wage=30000, month=SEP + 1)
    _, w_epf, _, _, e_epf, e_eps, _ = e.month_rows(*RATES)[SEP + 1]
    assert (w_epf, e_eps, e_epf) == (3000, 2083, 917)


def test_ecr_and_month_rows_agree_at_the_new_ceiling():
    from epf_engine import generate_ecr_month, Establishment, YearRecord, SCHEME_POST_1997
    e = _emp(wage=30000, month=SEP + 1)
    e.uan = "100900000099"
    est = Establishment(code="X", name="X", address="", year_from="2026", year_to="2027",
                        scheme=SCHEME_POST_1997)
    yr = YearRecord(year_from="2026", year_to="2027")
    f = generate_ecr_month(est, [e], yr, SEP + 1).split("#~#")
    # UAN#~#Name#~#Gross#~#EPF#~#EPS#~#EDLI#~#EE#~#EPS_share#~#ER_EPF
    assert (f[4], f[5], f[6], f[7], f[8]) == ("25000", "25000", "3000", "2083", "917")


def test_history_keeps_bankers_rounding_byte_identical():
    """Half-up is switched on only from the first dated ceiling change. A Rs 5,000 wage in
    the old Rs 5,000-ceiling era is an exact .5 (416.5) that has always rounded to 416 here;
    it must not move."""
    e = Employee(wages=[5000] * 12, year_from="1999")
    assert e.month_rows(*RATES, wage_ceilings=[5000.0] * 12)[0][5] == 416
    # ...and August 2026 (last month before the change) is untouched too: 1249.5 -> 1250 either way.
    assert _emp(wage=15000, month=SEP - 1).month_rows(*RATES)[SEP - 1][5] == 1250


def test_round_contribution_half_up_only_when_asked():
    from epf_engine import round_contribution
    assert round_contribution(2082.5, False) == 2082 and round_contribution(2082.5, True) == 2083
    assert round_contribution(1119.9996, True) == 1120 and round_contribution(0, True) == 0


# ------------------------------------ coverage-from dates mid-period; reported wage

def test_epf_from_mid_period_covers_only_from_that_day():
    """20 Sep: Sep 1-16 and 17-19 uncovered, 20-30 (11 of 30 days) covered at the new 25,000."""
    e = _emp(epf_from="20-09-2026")
    b = e.wage_bases(SEP, 20000, _ceil()[SEP])
    assert round(b.epf, 2) == round(20000 * 11 / 30, 2)
    e2 = _emp(month=SEP + 1, epf_from="10-10-2026")   # Oct: 22 of 31 days covered
    assert round(e2.wage_bases(SEP + 1, 20000, _ceil()[SEP + 1]).epf, 2) == round(20000 * 22 / 31, 2)


def test_cut_on_a_period_boundary_does_not_add_a_period():
    e = _emp(epf_from="17-09-2026", eps_from="17-09-2026")
    assert len(e.wage_bases_by_period(SEP, 20000, _ceil()[SEP])) == 2


def test_reported_epf_wage_only_differs_when_the_month_is_split():
    from epf_engine import reported_epf_wage
    c = _ceil()
    e = _emp()
    assert reported_epf_wage(e, SEP, 20000, c[SEP]) == 17333          # straddling month: prorated
    assert reported_epf_wage(_emp(month=SEP - 1), SEP - 1, 20000, c[SEP - 1]) == 20000   # Aug: as entered
    assert reported_epf_wage(_emp(month=SEP + 1), SEP + 1, 20000, c[SEP + 1]) == 20000   # Oct: as entered
    assert reported_epf_wage(e, SEP, 0, c[SEP]) == 0
    # an employee's own mid-month coverage date splits an otherwise ordinary month
    assert reported_epf_wage(_emp(month=SEP + 1, epf_from="10-10-2026"), SEP + 1, 20000, c[SEP + 1]) == 14194


def test_coverage_date_range_validated(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "TRANS005", "name": "Range Co"})
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    for bad in ("17-09-0026", "01-01-2099x", "01-01-2150"):
        r = consultant_a.post("/api/employees", json={"member_id": "RNG0001", "name": "R", "eps_from": bad})
        assert r.status_code == 400, bad


def test_remittance_admin_base_uses_prorated_epf_wage_in_september(consultant_a, test_db):
    """A/c 2/22 are computed on the EPF wage the ECR reports -- the prorated 17,333, not the
    entered 20,000 -- for the straddling month only."""
    est_id = _seed_transition_establishment(consultant_a, test_db, "TRANS006")
    rem = consultant_a.get("/api/years/2026-27/remittances").json()["remittances"]
    sep, aug, octo = rem[6], rem[5], rem[7]
    # three employees each: Sep A=9333 B=20000 C=17333 (higher EPF B reports full)
    assert sep["epf_wages"] == 9333 + 20000 + 17333
    assert aug["epf_wages"] == 3 * 20000 and octo["epf_wages"] == 3 * 30000
