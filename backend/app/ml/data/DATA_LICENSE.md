# Data attribution

## `online_retail_sample.csv.gz` — REAL transaction data

* **What:** the first 15,000 line items (1-7 December 2010; 442 customers, ~620 invoices) of the *Online Retail* data set:
  all transactions of a UK-based, registered, non-store online retailer (mostly wholesale customers).
* **Origin:** UCI Machine Learning Repository, *Online Retail*, donated by Daqing Chen (2015). UCI lists the data set under
  **CC BY 4.0** — please verify the licence and cite the original authors if you publish results.
* **Copy used here:** the sample distributed in the Elastic `eland` repository
  (`docs/sphinx/examples/data/online-retail.csv.gz`).
* **Why it is here:** it is real customer behaviour (invoice amounts, repeat-purchase timing, bursts from wholesale
  customers). It contains **no payment failures and no recovery outcomes**, so it is used only to sanity-check the
  simulator's amount distribution and to stress-test the card-testing detector for false positives
  (`python -m app.ml.realdata`). To use the full data set (541,909 rows), download it from UCI and pass `--path`.

## `industry_benchmarks.json` — PUBLISHED AGGREGATE STATISTICS

Figures quoted from public vendor/industry articles (sources and URLs are inside the file). They are **vendor-published,
unaudited, subscription-billing figures** — not a dataset, and not specific to Razorpay / UPI. They are used only as
calibration targets and reality checks, never as training data.
