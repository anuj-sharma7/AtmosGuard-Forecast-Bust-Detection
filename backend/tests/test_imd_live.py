"""Tests for the live IMD status. Fake fetchers; no network; no real key."""

from __future__ import annotations

import pytest

from app.ingest import imd_api, imd_live

FAKE_KEY = "fedcba9876543210fedcba9876543210"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(imd_api, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("IMD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("IMD_API_AUTH", "header-x-api-key")
    imd_live._cache.clear()


def failing(status):
    def fetch(url):
        raise imd_api.ImdApiError("boom", status=status)
    return fetch


def test_no_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("IMD_API_KEY")
    assert imd_live.check()["state"] == "not_configured"


def test_key_without_scheme_needs_probe(monkeypatch):
    monkeypatch.delenv("IMD_API_AUTH")
    assert imd_live.check()["state"] == "needs_probe"


@pytest.mark.parametrize("code", [401, 403])
def test_auth_refusal_points_at_the_ip(code):
    result = imd_live.check(fetch=failing(code))
    assert result["state"] == "rejected"
    assert "ip.php" in result["message"]
    assert result["cities"] == []


def test_network_failure_is_unreachable():
    assert imd_live.check(fetch=failing(None))["state"] == "unreachable"


def test_other_http_errors_are_errors():
    assert imd_live.check(fetch=failing(500))["state"] == "error"


def test_non_json_is_unrecognised():
    result = imd_live.check(fetch=lambda url: b"<html>maintenance</html>")
    assert result["state"] == "unrecognised"
    assert result["cities"] == []


def test_unknown_field_names_are_reported_for_mapping():
    result = imd_live.check(fetch=lambda url: b'[{"Stn": "Jaipur", "Tx": "34"}]')
    assert result["state"] == "unrecognised"
    assert set(result["fields_seen"]) == {"Stn", "Tx"}


def test_real_looking_payload_connects_and_matches_our_sites():
    payload = (
        b'[{"Station_Name": "Jaipur", "State": "Rajasthan", "Max_Temp": "34.2", "Min_Temp": "25.1"},'
        b' {"Station_Name": "Nowhere", "Max_Temp": "30"}]'
    )
    result = imd_live.check(fetch=lambda url: payload)
    assert result["state"] == "connected"
    assert len(result["cities"]) == 2
    assert result["matched"]["jaipur"]["max_temp"] == 34.2


def test_status_is_cached_until_refreshed():
    calls = []

    def fetch(url):
        calls.append(url)
        return b'[{"Station_Name": "Delhi", "Max_Temp": "33"}]'

    imd_live.status(fetch=fetch)
    imd_live.status(fetch=fetch)
    assert len(calls) == 1
    imd_live.status(refresh=True, fetch=fetch)
    assert len(calls) == 2


def test_nothing_is_substituted_when_not_connected():
    for fetch in (failing(403), failing(None), lambda url: b"nope"):
        assert imd_live.check(fetch=fetch)["cities"] == []
