"""
test_app.py — Flask endpoint integration tests for the market performance dashboard.
All tests use the flask_client fixture (from conftest.py):
  - _price_cache monkeypatched with synthetic data
  - load_universe monkeypatched with minimal universe list
  - Zero real network calls
"""

from __future__ import annotations

import json

import pytest


# ════════════════════════════════════════════════════════════════════════════
# /api/overview
# ════════════════════════════════════════════════════════════════════════════

class TestOverviewEndpoint:
    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/overview")
        assert resp.status_code == 200

    def test_response_is_json(self, flask_client):
        resp = flask_client.get("/api/overview")
        data = resp.get_json()
        assert data is not None

    def test_top_level_keys(self, flask_client):
        data = flask_client.get("/api/overview").get_json()
        assert "rows" in data
        assert "last_updated" in data

    def test_rows_is_list(self, flask_client):
        data = flask_client.get("/api/overview").get_json()
        assert isinstance(data["rows"], list)

    def test_row_contains_required_fields(self, flask_client):
        data = flask_client.get("/api/overview").get_json()
        required = {"id", "name", "type", "currency", "has_data"}
        for row in data["rows"]:
            for field in required:
                assert field in row, f"Field '{field}' missing from row {row.get('id')}"

    def test_fund_with_data_has_numeric_returns(self, flask_client):
        data = flask_client.get("/api/overview").get_json()
        fund_rows = [r for r in data["rows"] if r["id"] == "FUND_A"]
        assert len(fund_rows) == 1
        row = fund_rows[0]
        assert row["has_data"] is True
        # ytd and ret_12m should be float or None (not missing key)
        assert "ytd" in row
        assert "ret_12m" in row

    def test_empty_fund_has_none_returns(self, flask_client):
        data = flask_client.get("/api/overview").get_json()
        empty_rows = [r for r in data["rows"] if r["id"] == "FUND_EMPTY"]
        assert len(empty_rows) == 1
        row = empty_rows[0]
        assert row["has_data"] is False
        assert row["ytd"] is None

    def test_last_updated_is_string(self, flask_client):
        data = flask_client.get("/api/overview").get_json()
        assert isinstance(data["last_updated"], str)

    def test_no_numpy_serialisation_error(self, flask_client):
        """Response must be fully JSON-serialisable (no numpy scalars leaking)."""
        resp = flask_client.get("/api/overview")
        # If Flask's jsonify fails on numpy scalars it raises 500
        assert resp.status_code == 200
        # Verify round-trip parse works
        _ = json.loads(resp.data)


# ════════════════════════════════════════════════════════════════════════════
# /api/timeseries
# ════════════════════════════════════════════════════════════════════════════

class TestTimeseriesEndpoint:
    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/timeseries?ids=FUND_A")
        assert resp.status_code == 200

    def test_response_structure(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_A").get_json()
        assert "FUND_A" in data
        fund_data = data["FUND_A"]
        assert "dates" in fund_data
        assert "prices_100" in fund_data
        assert "drawdown" in fund_data

    def test_rebased_first_value_100(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_A&start=2022-01-01").get_json()
        prices = data["FUND_A"]["prices_100"]
        assert len(prices) > 0
        assert abs(prices[0] - 100.0) < 0.01

    def test_dates_and_prices_same_length(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_A").get_json()
        d = data["FUND_A"]
        assert len(d["dates"]) == len(d["prices_100"]) == len(d["drawdown"])

    def test_drawdown_nonpositive(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_A").get_json()
        dd = data["FUND_A"]["drawdown"]
        for v in dd:
            assert v <= 0.0001  # allow tiny float rounding

    def test_empty_fund_returns_empty_lists(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_EMPTY").get_json()
        d = data["FUND_EMPTY"]
        assert d["dates"] == []
        assert d["prices_100"] == []
        assert d["drawdown"] == []

    def test_multiple_ids(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_A,FUND_B").get_json()
        assert "FUND_A" in data
        assert "FUND_B" in data

    def test_no_ids_returns_all(self, flask_client):
        """No ids param → all funds with data returned."""
        data = flask_client.get("/api/timeseries").get_json()
        assert len(data) >= 1  # at least FUND_A and FUND_B

    def test_end_date_filter(self, flask_client):
        data_full = flask_client.get("/api/timeseries?ids=FUND_A").get_json()
        data_trunc = flask_client.get("/api/timeseries?ids=FUND_A&end=2023-01-01").get_json()
        assert len(data_trunc["FUND_A"]["dates"]) <= len(data_full["FUND_A"]["dates"])

    def test_date_format_yyyy_mm_dd(self, flask_client):
        data = flask_client.get("/api/timeseries?ids=FUND_A").get_json()
        dates = data["FUND_A"]["dates"]
        assert len(dates) > 0
        # Each date should be YYYY-MM-DD (10 chars)
        for d in dates[:5]:
            assert len(d) == 10 and d[4] == "-" and d[7] == "-"


# ════════════════════════════════════════════════════════════════════════════
# /api/stats
# ════════════════════════════════════════════════════════════════════════════

class TestStatsEndpoint:
    STAT_KEYS = {"cagr", "vol", "sharpe", "sharpe_lo", "sharpe_hi",
                 "sortino", "max_dd", "calmar", "skew", "kurt", "n_obs"}

    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/stats?ids=FUND_A")
        assert resp.status_code == 200

    def test_contains_fund_id(self, flask_client):
        data = flask_client.get("/api/stats?ids=FUND_A").get_json()
        assert "FUND_A" in data

    def test_stat_keys_present(self, flask_client):
        data = flask_client.get("/api/stats?ids=FUND_A").get_json()
        for key in self.STAT_KEYS:
            assert key in data["FUND_A"], f"Missing key: {key}"

    def test_empty_fund_returns_nones(self, flask_client):
        data = flask_client.get("/api/stats?ids=FUND_EMPTY").get_json()
        for v in data["FUND_EMPTY"].values():
            assert v is None

    def test_no_ids_returns_all(self, flask_client):
        data = flask_client.get("/api/stats").get_json()
        assert len(data) >= 2

    def test_start_date_param(self, flask_client):
        data = flask_client.get("/api/stats?ids=FUND_A&start=2023-01-01").get_json()
        full = flask_client.get("/api/stats?ids=FUND_A").get_json()
        # Sliced window should have fewer obs
        assert data["FUND_A"]["n_obs"] <= full["FUND_A"]["n_obs"]

    def test_values_are_json_serialisable(self, flask_client):
        resp = flask_client.get("/api/stats?ids=FUND_A")
        assert resp.status_code == 200
        _ = json.loads(resp.data)

    def test_vol_nonnegative(self, flask_client):
        data = flask_client.get("/api/stats?ids=FUND_A").get_json()
        v = data["FUND_A"]["vol"]
        if v is not None:
            assert v >= 0

    def test_max_dd_nonpositive(self, flask_client):
        data = flask_client.get("/api/stats?ids=FUND_A").get_json()
        mdd = data["FUND_A"]["max_dd"]
        if mdd is not None:
            assert mdd <= 0


# ════════════════════════════════════════════════════════════════════════════
# /api/calendar
# ════════════════════════════════════════════════════════════════════════════

class TestCalendarEndpoint:
    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/calendar?id=FUND_A")
        assert resp.status_code == 200

    def test_missing_id_returns_400(self, flask_client):
        resp = flask_client.get("/api/calendar")
        assert resp.status_code == 400

    def test_response_is_dict(self, flask_client):
        data = flask_client.get("/api/calendar?id=FUND_A").get_json()
        assert isinstance(data, dict)

    def test_all_keys_are_strings(self, flask_client):
        """
        CRITICAL: Python 3.13 jsonify raises TypeError on dict with mixed int/str keys.
        All year keys must be strings.
        """
        data = flask_client.get("/api/calendar?id=FUND_A").get_json()
        for k in data.keys():
            assert isinstance(k, str), f"Calendar year key {k!r} is not a string"

    def test_inner_keys_are_strings(self, flask_client):
        data = flask_client.get("/api/calendar?id=FUND_A").get_json()
        for year_str, month_dict in data.items():
            for mk in month_dict.keys():
                assert isinstance(mk, str), (
                    f"Month key {mk!r} in year {year_str} is not a string"
                )

    def test_ann_key_present(self, flask_client):
        data = flask_client.get("/api/calendar?id=FUND_A").get_json()
        for year_str, month_dict in data.items():
            assert "ann" in month_dict, f"'ann' missing from year {year_str}"

    def test_empty_fund_returns_empty_dict(self, flask_client):
        data = flask_client.get("/api/calendar?id=FUND_EMPTY").get_json()
        assert data == {}

    def test_unknown_fund_returns_empty_dict(self, flask_client):
        data = flask_client.get("/api/calendar?id=DOES_NOT_EXIST").get_json()
        assert data == {}

    def test_values_are_numbers(self, flask_client):
        data = flask_client.get("/api/calendar?id=FUND_A").get_json()
        for year_str, month_dict in data.items():
            for mk, mv in month_dict.items():
                assert isinstance(mv, (int, float)), (
                    f"Value for {year_str}/{mk} is {type(mv)}"
                )


# ════════════════════════════════════════════════════════════════════════════
# /api/correlation
# ════════════════════════════════════════════════════════════════════════════

class TestCorrelationEndpoint:
    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/correlation")
        assert resp.status_code == 200

    def test_response_structure(self, flask_client):
        data = flask_client.get("/api/correlation").get_json()
        for key in ("ids", "names", "matrix", "window", "n_obs"):
            assert key in data, f"Missing key: {key}"

    def test_matrix_is_square(self, flask_client):
        data = flask_client.get("/api/correlation").get_json()
        n = len(data["ids"])
        assert len(data["matrix"]) == n
        for row in data["matrix"]:
            assert len(row) == n

    def test_diagonal_is_one(self, flask_client):
        data = flask_client.get("/api/correlation").get_json()
        for i in range(len(data["ids"])):
            assert data["matrix"][i][i] == 1.0

    def test_window_param_1y(self, flask_client):
        data = flask_client.get("/api/correlation?window=1Y").get_json()
        assert data["window"] == "1Y"

    def test_names_same_length_as_ids(self, flask_client):
        data = flask_client.get("/api/correlation").get_json()
        assert len(data["names"]) == len(data["ids"])

    def test_values_bounded(self, flask_client):
        data = flask_client.get("/api/correlation?window=All").get_json()
        for row in data["matrix"]:
            for v in row:
                if v is not None:
                    assert -1.0 <= v <= 1.0

    def test_json_serialisable(self, flask_client):
        resp = flask_client.get("/api/correlation")
        assert resp.status_code == 200
        _ = json.loads(resp.data)


# ════════════════════════════════════════════════════════════════════════════
# /api/universe (GET)
# ════════════════════════════════════════════════════════════════════════════

class TestUniverseEndpoint:
    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/universe")
        assert resp.status_code == 200

    def test_response_is_list(self, flask_client):
        data = flask_client.get("/api/universe").get_json()
        assert isinstance(data, list)

    def test_each_item_has_id(self, flask_client):
        data = flask_client.get("/api/universe").get_json()
        for item in data:
            assert "id" in item


# ════════════════════════════════════════════════════════════════════════════
# /api/returns
# ════════════════════════════════════════════════════════════════════════════

class TestReturnsEndpoint:
    def test_returns_200(self, flask_client):
        resp = flask_client.get("/api/returns?window=YTD")
        assert resp.status_code == 200

    def test_fund_ids_in_response(self, flask_client):
        data = flask_client.get("/api/returns?window=YTD").get_json()
        assert "FUND_A" in data

    def test_each_entry_has_return_and_currency(self, flask_client):
        data = flask_client.get("/api/returns?window=YTD").get_json()
        for fid, entry in data.items():
            assert "return" in entry
            assert "currency" in entry

    def test_empty_fund_return_is_none(self, flask_client):
        data = flask_client.get("/api/returns?window=YTD").get_json()
        assert data["FUND_EMPTY"]["return"] is None

    def test_valid_window_options(self, flask_client):
        for window in ["1M", "3M", "YTD", "1Y"]:
            resp = flask_client.get(f"/api/returns?window={window}")
            assert resp.status_code == 200
