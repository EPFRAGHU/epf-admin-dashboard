import pytest


def _new_establishment(consultant, code, name):
    res = consultant.post("/api/establishments", json={"code": code, "name": name})
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def _setup_year_and_employee(consultant, code, member_id, **employee_kwargs):
    _new_establishment(consultant, code, f"{code} Co")
    consultant.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant.post("/api/employees", json={
        "member_id": member_id, "name": "PoHW Test Employee", "uan": f"1009{member_id}",
        **employee_kwargs,
    })
    assert res.status_code == 200, res.text


def test_pohw_calculates_eps_on_actual_wage_not_capped(consultant_a):
    """
    Verify the exact worked example the feature was speced against: Rs.75,000 monthly
    wage with PoHW ticked should give EE=9000, ER EPF=2752 (2752.50 rounded), ER EPS=6248
    (6247.50 rounded) -- EPS computed on the actual wage, not capped at the Rs.15,000
    ceiling like an ordinary Higher EPF (ER) employee would be.
    """
    _setup_year_and_employee(consultant_a, "POHW0000001", "PH0001", pohw=True)

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0001", "wages": [75000.0] + [0.0] * 11, "pohw": True,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0001")
    assert emp["pohw"] is True
    assert emp["pohw_additional_1_16"] is False

    april = emp["months"][0]
    assert april["w"] == 75000
    assert april["we"] == 9000     # employee EPF: 12% of 75,000
    assert april["ee"] == 2752     # employer EPF: 9000 - 6247.50, rounded
    assert april["es"] == 6248     # employer EPS: 8.33% of 75,000, rounded


def test_pohw_additional_1_16_percent_add_on(consultant_a):
    """
    With the optional 1.16% add-on also ticked: additional 1.16% on the wage portion
    above the Rs.15,000 ceiling gets folded into the EPS/Account-10 figure, on top of
    the standard 8.33%. (75000-15000)*1.16% = 696, so ER EPS becomes 6247.50+696=6943.50
    -> rounds to 6944. ER EPF stays unaffected (still derived from the standard 8.33%
    EPS only, not the inflated figure) at 2752.
    """
    _setup_year_and_employee(consultant_a, "POHW0000002", "PH0002", pohw=True, pohw_additional_1_16=True)

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0002", "wages": [75000.0] + [0.0] * 11,
        "pohw": True, "pohw_additional_1_16": True,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0002")
    assert emp["pohw_additional_1_16"] is True

    april = emp["months"][0]
    assert april["we"] == 9000
    assert april["ee"] == 2752      # unaffected by the 1.16% add-on
    assert april["es"] == 6944      # 6248 (standard) + 696 (additional) = 6944


def test_pohw_is_standalone_and_does_not_need_higher_epf_flags_ticked(consultant_a):
    """
    Explicit design decision: PoHW alone forces full-wage EPF/EPS on both sides,
    independent of whatever the separate Higher EPF (EE)/(ER) checkboxes say.
    """
    _setup_year_and_employee(consultant_a, "POHW0000003", "PH0003", pohw=True)

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0003", "wages": [75000.0] + [0.0] * 11,
        "pohw": True, "higher_epf_ee": False, "higher_epf_er": False,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0003")
    assert emp["higher_epf_ee"] is False
    assert emp["higher_epf_er"] is False

    april = emp["months"][0]
    assert april["we"] == 9000   # still full 12% of 75,000, not capped at 15,000*12%=1800
    assert april["es"] == 6248   # still uncapped EPS


def test_pohw_age_crosses_58_still_zeroes_eps(consultant_a):
    """PoHW doesn't override the existing age>=58 rule -- EPS still goes to zero and
    every rupee of the employer's 12% flows to EPF instead."""
    _setup_year_and_employee(consultant_a, "POHW0000004", "PH0004", pohw=True)

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0004", "wages": [75000.0] + [0.0] * 11,
        "pohw": True, "age_crosses_58": True,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0004")
    assert emp["age_crosses_58"] is True

    april = emp["months"][0]
    assert april["es"] == 0
    assert april["ee"] == 9000   # all employer contribution flows to EPF


def test_non_pohw_employee_unaffected_by_the_new_fields(consultant_a):
    """Regression guard: an ordinary employee (no PoHW, no Higher EPF flags) at exactly
    the Rs.15,000 ceiling must still get the pre-existing standard figures."""
    _setup_year_and_employee(consultant_a, "POHW0000005", "PH0005")

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0005", "wages": [15000.0] + [0.0] * 11,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0005")
    assert emp["pohw"] is False
    assert emp["pohw_additional_1_16"] is False

    april = emp["months"][0]
    assert april["we"] == 1800   # 12% of 15,000
    assert april["ee"] == 550    # 3.67% of 15,000
    assert april["es"] == 1250   # 8.33% of 15,000
