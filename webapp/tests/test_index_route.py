"""Regression: the homepage route must accept HEAD as well as GET. FastAPI/Starlette
does not auto-add HEAD support to a GET-only route, so uptime monitors that default to
HEAD requests (e.g. UptimeRobot) got a 405 "Allow: GET" on every check and reported
the site as down, even though it was fully up. Found live on production
(epf-dashboard.xyz) 2026-08-29."""


def test_homepage_accepts_get(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_homepage_accepts_head(client):
    res = client.head("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_homepage_head_has_no_body(client):
    res = client.head("/")
    assert res.content == b""
