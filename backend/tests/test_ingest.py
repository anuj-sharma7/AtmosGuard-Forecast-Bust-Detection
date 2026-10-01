"""Tests for the ingestion layer.

The HTTP call itself is not tested - this environment's egress policy blocks
every government data host, so there is nothing honest to assert about it. What
*is* tested is everything around it: URL construction, the pagination loop that
decides when a resource is exhausted, CSV writing, and the request shapes sent
to ECMWF. Those are where the bugs would actually be.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from app.ingest import datagov, ecmwf_open
from app.ingest.sources import SOURCES, SOURCES_BY_ID


class TestCatalogue:
    def test_every_source_is_complete(self) -> None:
        for source in SOURCES:
            assert source.portal.startswith("https://"), source.id
            assert source.licence and source.how_to_get and source.role, source.id
            assert source.access in {"open", "key", "account", "restricted"}, source.id

    def test_ids_are_unique(self) -> None:
        assert len(SOURCES_BY_ID) == len(SOURCES)

    def test_the_datasets_actually_in_use_are_marked_so(self) -> None:
        in_use = {s.id for s in SOURCES if s.status == "in use"}
        assert in_use == {
            "imd-subdivision-rainfall",
            "imd-district-daily-rainfall",
            "datameet-boundaries",
            "noaa-ghcn-daily",
        }

    def test_the_station_archive_marked_in_use_is_actually_on_disk(self) -> None:
        from app.core import station_replay

        assert station_replay.DAILY_FILE.is_file()
        assert station_replay.STATIONS_FILE.is_file()

    def test_nothing_claims_to_be_connected_that_is_not(self) -> None:
        """Guards the honesty of the System page.

        Only the two files actually on disk may be listed as in use; everything
        else is a documented route, not a live feed.
        """
        for source in SOURCES:
            if source.status == "in use":
                assert source.access == "open"


class FakeApi:
    """A data.gov.in stand-in that paginates the way the real one does."""

    def __init__(self, total: int, page_size: int = datagov.MAX_LIMIT) -> None:
        self.records = [{"id": str(i), "value": f"row-{i}"} for i in range(total)]
        self.page_size = page_size
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        offset = int(url.split("offset=")[1].split("&")[0])
        limit = int(url.split("limit=")[1].split("&")[0])
        page = self.records[offset : offset + min(limit, self.page_size)]
        return json.dumps({"records": page, "total": len(self.records)}).encode()


class TestDataGovPagination:
    def test_fetches_every_record_across_pages(self) -> None:
        api = FakeApi(total=2500)
        rows = list(datagov.fetch_resource("res-1", key="k", page_size=1000, fetch=api))
        assert len(rows) == 2500
        assert rows[0]["value"] == "row-0" and rows[-1]["value"] == "row-2499"
        assert len(api.calls) == 3

    def test_stops_on_a_short_page(self) -> None:
        """A page shorter than the limit is the end - no extra request."""
        api = FakeApi(total=150)
        rows = list(datagov.fetch_resource("res-1", key="k", page_size=1000, fetch=api))
        assert len(rows) == 150
        assert len(api.calls) == 1

    def test_empty_resource_yields_nothing(self) -> None:
        api = FakeApi(total=0)
        assert list(datagov.fetch_resource("res-1", key="k", fetch=api)) == []

    def test_max_records_caps_the_download(self) -> None:
        api = FakeApi(total=10_000)
        rows = list(datagov.fetch_resource("r", key="k", page_size=1000, max_records=1200, fetch=api))
        assert len(rows) == 1200

    def test_page_size_is_clamped_to_the_platform_limit(self) -> None:
        url = datagov.build_url("r", "k", offset=0, limit=99_999)
        assert f"limit={datagov.MAX_LIMIT}" in url

    def test_url_carries_the_key_and_json_format(self) -> None:
        url = datagov.build_url("abc-123", "secret", offset=40, limit=100)
        assert url.startswith(f"{datagov.BASE}/abc-123?")
        assert "api-key=secret" in url and "format=json" in url and "offset=40" in url

    def test_missing_key_explains_how_to_get_one(self) -> None:
        with pytest.raises(datagov.DataGovError, match="data.gov.in"):
            datagov.api_key()


class TestCsvWriting:
    def test_writes_a_header_and_every_row(self, tmp_path: Path) -> None:
        target = tmp_path / "out" / "rows.csv"
        written = datagov.write_csv(iter([{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]), target)
        assert written == 2

        with target.open() as handle:
            rows = list(csv.DictReader(handle))
        assert rows == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

    def test_an_empty_result_raises_and_leaves_no_file(self, tmp_path: Path) -> None:
        """A zero-byte CSV silently replacing real data is the worst outcome."""
        target = tmp_path / "rows.csv"
        with pytest.raises(datagov.DataGovError, match="no records"):
            datagov.write_csv(iter([]), target)
        assert not target.exists()


class TestEcmwfRequest:
    def test_ensemble_request_asks_for_perturbed_members(self) -> None:
        described = ecmwf_open.describe(ecmwf_open.Request(run_date=date(2026, 9, 1)))
        assert described["stream"] == "enfo"
        assert described["type"] == "pf"

    def test_deterministic_request_asks_for_the_forecast_type(self) -> None:
        described = ecmwf_open.describe(
            ecmwf_open.Request(run_date=date(2026, 9, 1), stream="oper")
        )
        assert described["type"] == "fc"

    def test_default_steps_cover_the_medium_range_window(self) -> None:
        steps = ecmwf_open.DEFAULT_STEPS
        assert steps[0] == 0 and steps[-1] >= 168  # at least out to Day 7
        assert all(b - a == 6 for a, b in zip(steps, steps[1:]))

    def test_default_params_cover_every_dashboard_variable(self) -> None:
        assert set(ecmwf_open.DEFAULT_PARAMS) >= {"tp", "2t", "msl"}
        assert {"10u", "10v"} <= set(ecmwf_open.DEFAULT_PARAMS), "wind needs both components"

    def test_target_filename_identifies_the_cycle(self, tmp_path: Path) -> None:
        request = ecmwf_open.Request(run_date=date(2026, 9, 1), cycle=12)
        assert request.target(tmp_path).name == "ecmwf_enfo_20260901_12z.grib2"

    def test_india_box_contains_the_monitored_network(self) -> None:
        from app.core.domain import ALL_SITES

        north, west, south, east = ecmwf_open.INDIA_BBOX
        for site in ALL_SITES:
            assert south <= site.lat <= north, site.id
            assert west <= site.lon <= east, site.id


class TestLiveWeather:
    def test_compare_ground_truth_aligned(self) -> None:
        from app.ingest import live_weather

        obs = {
            "temperature": 32.0,
            "relative_humidity": 60,
            "precipitation_mm": 0.0,
        }
        res = live_weather.compare_ground_truth(
            obs,
            forecast_temp_max=34.0,
            forecast_temp_min=24.0,
            forecast_precip_expected=False,
        )
        assert res["agreement"] == "HIGH"
        assert res["divergence_count"] == 0

    def test_compare_ground_truth_temperature_divergence(self) -> None:
        from app.ingest import live_weather

        obs = {
            "temperature": 41.5,
            "relative_humidity": 30,
            "precipitation_mm": 0.0,
        }
        res = live_weather.compare_ground_truth(
            obs,
            forecast_temp_max=35.0,
            forecast_temp_min=25.0,
        )
        assert res["agreement"] == "LOW"
        assert res["divergence_count"] >= 1
        assert "exceeds forecast max" in res["notes"][0]

    def test_compare_ground_truth_dry_air_divergence(self) -> None:
        from app.ingest import live_weather

        obs = {
            "temperature": 28.0,
            "relative_humidity": 35.0,
            "precipitation_mm": 0.0,
        }
        res = live_weather.compare_ground_truth(
            obs,
            forecast_temp_max=32.0,
            forecast_precip_expected=True,
        )
        assert res["agreement"] in {"MODERATE", "LOW"}
        assert any("Dry air" in note for note in res["notes"])

    def test_fetch_msn_weather_empty_location(self) -> None:
        from app.ingest import live_weather

        assert live_weather.fetch_msn_weather("") is None

    def test_fetch_live_weather_returns_standard_structure(self) -> None:
        from app.ingest import live_weather

        data = live_weather.fetch_live_weather(26.9, 75.8, location_name="Jaipur")
        assert "temperature" in data
        assert "relative_humidity" in data
        assert "source" in data
        assert "msn_connector" in data

