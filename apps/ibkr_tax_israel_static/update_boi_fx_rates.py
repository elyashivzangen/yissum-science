#!/usr/bin/env python3
"""Update Bank of Israel USD/ILS FX cache for the static IBKR tax app.

This script runs in GitHub Actions, where server-side requests are not blocked by
browser CORS. It writes apps/ibkr_tax_israel_static/boi_fx_rates.json for the
GitHub Pages app to consume from the same origin.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

API_BASE = "https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0/"
OUT = Path(__file__).with_name("boi_fx_rates.json")


def fetch_rates(start: str, end: str) -> dict[str, float]:
    params = {
        "c[BASE_CURRENCY]": "USD",
        "c[COUNTER_CURRENCY]": "ILS",
        "format": "csv",
        "startPeriod": start,
        "endPeriod": end,
    }
    url = API_BASE + "?" + urlencode(params)
    with urlopen(url, timeout=60) as res:
        text = res.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rates: dict[str, float] = {}
    for row in reader:
        d = row.get("TIME_PERIOD") or row.get("Time period") or row.get("time_period")
        v = row.get("OBS_VALUE") or row.get("Obs value") or row.get("obs_value")
        if not d or not v:
            continue
        try:
            rates[str(d)[:10]] = float(str(v).replace(",", ""))
        except ValueError:
            continue
    if not rates:
        raise RuntimeError("No BOI rates parsed from API response")
    return rates


def main() -> None:
    start = os.environ.get("BOI_START", "2020-01-01")
    end = os.environ.get("BOI_END", date.today().isoformat())
    rates = fetch_rates(start, end)
    payload = {
        "source": "Bank of Israel EXR series API, RER_USD_ILS / USD to ILS representative exchange rate",
        "source_url": API_BASE + "?" + urlencode({"c[BASE_CURRENCY]": "USD", "c[COUNTER_CURRENCY]": "ILS", "format": "csv"}),
        "series": "RER_USD_ILS",
        "base_currency": "USD",
        "counter_currency": "ILS",
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "start": start,
        "end": end,
        "rates": dict(sorted(rates.items())),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rates)} BOI USD/ILS rates to {OUT}")


if __name__ == "__main__":
    main()
