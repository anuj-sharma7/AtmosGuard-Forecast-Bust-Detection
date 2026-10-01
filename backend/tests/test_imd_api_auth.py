"""Tests for IMD API key handling. No network; a made-up key throughout."""

from __future__ import annotations

import pytest

from app.ingest import imd_api

FAKE_KEY = "0123456789abcdef0123456789abcdef"


def test_header_scheme_puts_the_key_in_a_header_not_the_url():
    url, headers = imd_api.authorise("https://api.imd.gov.in/api/v1/cityforecast", FAKE_KEY, "header-x-api-key")
    assert FAKE_KEY not in url
    assert headers == {"x-api-key": FAKE_KEY}


def test_bearer_scheme_prefixes_the_key():
    _, headers = imd_api.authorise("https://x/y", FAKE_KEY, "bearer")
    assert headers == {"Authorization": f"Bearer {FAKE_KEY}"}


def test_query_scheme_appends_correctly_with_and_without_a_query():
    url, headers = imd_api.authorise("https://x/y", FAKE_KEY, "query-api_key")
    assert url == f"https://x/y?api_key={FAKE_KEY}" and headers == {}
    url, _ = imd_api.authorise("https://x/y?a=1", FAKE_KEY, "query-key")
    assert url == f"https://x/y?a=1&key={FAKE_KEY}"


def test_unknown_scheme_is_refused():
    with pytest.raises(imd_api.ImdApiError):
        imd_api.authorise("https://x/y", FAKE_KEY, "carrier-pigeon")


def test_mask_never_shows_the_whole_key():
    shown = imd_api.mask(f"GET https://x/y?api_key={FAKE_KEY}", FAKE_KEY)
    assert FAKE_KEY not in shown
    assert "0123...cdef" in shown


def test_a_key_without_a_scheme_stops_rather_than_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr(imd_api, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("IMD_API_KEY", FAKE_KEY)
    monkeypatch.delenv("IMD_API_AUTH", raising=False)
    with pytest.raises(imd_api.ImdApiError, match="--probe"):
        imd_api.configured_fetch()


def test_no_key_means_unauthenticated_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(imd_api, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("IMD_API_KEY", raising=False)
    assert imd_api.configured_fetch() is imd_api._default_fetch


def test_env_file_is_read_when_the_environment_is_empty(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(f'# comment\nIMD_API_KEY="{FAKE_KEY}"\nIMD_API_AUTH=query-apikey\n')
    monkeypatch.setattr(imd_api, "ENV_FILE", env)
    monkeypatch.delenv("IMD_API_KEY", raising=False)
    monkeypatch.delenv("IMD_API_AUTH", raising=False)
    assert imd_api.setting("IMD_API_KEY") == FAKE_KEY
    assert imd_api.setting("IMD_API_AUTH") == "query-apikey"


def test_parsing_still_works_with_an_injected_fetcher():
    payload = b'[{"Station_Name": "Jaipur", "State": "Rajasthan", "Max_Temp": "34.2"}]'
    cities = imd_api.city_forecast(fetch=lambda url: payload)
    assert cities[0].city == "Jaipur" and cities[0].max_temp == 34.2
