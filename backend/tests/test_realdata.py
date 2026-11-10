import gzip
import json

import pytest

from app.ml import realdata as R
from app.ml import registry


def _write(tmp_path, text, name="t.csv"):
    p = tmp_path / name
    p.write_text(text)
    return p


HEADER = "InvoiceNo,StockCode,Description,Quantity,InvoiceDate,UnitPrice,CustomerID,Country\n"


def test_bundled_sample_is_real_and_loads():
    invs, st = R.load_invoices()
    assert len(invs) >= 500 and len({i.customer for i in invs}) >= 400
    assert st["rows"] == 15000 and st["rows_missing_customer"] > 1000      # real data has anonymous (guest) rows
    assert st["cancelled_invoices"] > 0 and all(i.amount > 0 for i in invs)
    assert all(a.ts <= b.ts for a, b in zip(invs, invs[1:]))


def test_loader_handles_original_uci_format_cancellations_and_junk(tmp_path):
    csv_text = HEADER + "\n".join([
        "536365,A,x,6,12/1/2010 8:26,2.55,17850,United Kingdom",
        "536365,B,y,2,12/1/2010 8:26,10.00,17850,United Kingdom",      # same invoice -> amounts add up
        "C536379,D,z,-1,12/1/2010 9:41,27.50,14527,United Kingdom",    # cancellation: excluded
        "536366,E,w,3,12/1/2010 9:00,1.00,,United Kingdom",            # no customer: excluded
        "536367,F,v,1,not-a-date,5.00,12345,United Kingdom",           # unparseable: counted
        "536368,G,u,-5,12/1/2010 9:10,5.00,12346,United Kingdom",      # non-positive total: dropped
    ]) + "\n"
    invs, st = R.load_invoices(_write(tmp_path, csv_text))
    assert [(i.id, i.customer, round(i.amount, 2)) for i in invs] == [("536365", "17850", 35.30)]
    assert st["cancelled_invoices"] == 1 and st["rows_missing_customer"] == 1 and st["bad_rows"] == 1


def test_loader_reads_gzip_and_online_retail_ii_column_names(tmp_path):
    text = "Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country\n489434,A,x,12,2009-12-01 07:45:00,6.95,13085.0,UK\n"
    p = tmp_path / "ii.csv.gz"
    p.write_bytes(gzip.compress(text.encode()))
    invs, _ = R.load_invoices(p)
    assert len(invs) == 1 and invs[0].customer == "13085" and invs[0].amount == pytest.approx(83.4)


def test_missing_columns_are_reported_clearly(tmp_path):
    with pytest.raises(ValueError, match="missing required column"):
        R.load_invoices(_write(tmp_path, "a,b\n1,2\n"))


def test_report_on_real_sample_is_sane_and_deterministic():
    a = R.run(write=False, seed=3)
    b = R.run(write=False, seed=3)
    assert a["detector_stress"] == b["detector_stress"]
    shape = a["amount_shape"]
    assert 0.8 < shape["real_log_sd"] < 1.4                                   # simulator's 1.0 is in the right ballpark
    s = a["detector_stress"]
    worst, real = s["worst_case_all_attempts_fail"], s["realistic"]
    assert worst["windows"] == a["dataset"]["invoices_used"] and 0 <= worst["rate"] < 0.15
    assert real["hold_rate_mean"] <= worst["rate"] and real["hold_rate_mean"] < 0.02
    assert a["dataset"]["is_bundled_sample"] and "NO payment failures" in a["dataset"]["limits"]


def test_shipped_report_matches_a_fresh_run():
    shipped = registry.read_json("realdata_report.json")
    fresh = R.run(write=False)
    assert shipped["detector_stress"]["worst_case_all_attempts_fail"] == fresh["detector_stress"]["worst_case_all_attempts_fail"]
    assert shipped["amount_shape"]["real_log_sd"] == fresh["amount_shape"]["real_log_sd"]


def test_too_little_data_is_refused(tmp_path):
    rows = "".join(f"{i},A,x,1,2010-12-01 08:00:00,5.0,{i},UK\n" for i in range(5))
    with pytest.raises(ValueError, match="Too few"):
        R.run(_write(tmp_path, HEADER + rows), write=False)


def test_licence_and_benchmark_files_ship_with_sources():
    assert (R.DEFAULT_PATH.parent / "DATA_LICENSE.md").exists()
    b = json.loads((R.DEFAULT_PATH.parent / "industry_benchmarks.json").read_text())
    assert "unaudited" in b["disclaimer"]
    for group in ("failure_mix", "recovery_rates", "timing"):
        assert b[group] and all(x["url"].startswith("https://") and x["source"] for x in b[group])
