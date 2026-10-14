# MLOps Batch Pipeline: Rolling-Mean Trading Signals

A small, production-style batch job that turns minute-level BTC price data into a binary trading signal.
It is built to show **reproducibility, observability and deployment readiness**: config-driven, seeded,
logged, tested, containerized and CI-checked.

## What it does
1. Loads and validates `config.yaml` (`seed`, `window`, `version`).
2. Loads and validates the OHLCV dataset (`data.csv`, 10,000 one-minute rows, requires a numeric `close` column).
3. Computes a rolling mean of `close` over `window` rows.
4. Generates a signal: `1` if `close > rolling_mean`, otherwise `0`.
5. Writes metrics to `metrics.json`, prints the same JSON to stdout, and logs every step to `run.log`.

> The first `window - 1` rows have no rolling mean, so their signal is `0`. These rows are included in
> `rows_processed` and in the `signal_rate` denominator.

## Project structure
```
run.py                 the batch job (CLI)
config.yaml            seed, window, version
data.csv               10,000-row BTC OHLCV sample
tests/test_run.py      pytest suite (11 tests)
Dockerfile             container image
.github/workflows/ci.yml   runs tests, the job, and the Docker build on every push
```

## Run locally
```bash
pip install -r requirements.txt
python run.py --input data.csv --config config.yaml --output metrics.json --log-file run.log
```

## Run with Docker
```bash
docker build -t signal-job .
docker run --rm signal-job
```
To keep the outputs on your machine:
```bash
docker run --rm -v "$(pwd)/out:/out" signal-job \
  python run.py --input data.csv --config config.yaml --output /out/metrics.json --log-file /out/run.log
```

## Example output
```json
{
    "version": "v1",
    "rows_processed": 10000,
    "metric": "signal_rate",
    "value": 0.4989,
    "latency_ms": 25,
    "seed": 42,
    "status": "success"
}
```
On any failure the job exits with code `1` and writes an error record instead:
```json
{ "version": "v1", "status": "error", "error_message": "Missing required column: 'close'" }
```

## Tests
```bash
pytest -q
```
Covers the metrics schema, signal correctness, determinism, quoted-CSV handling, and error paths
(empty file, missing column, non-numeric data, bad config, missing files).

## Design notes
- **Reproducible:** every run is seeded from `config.yaml`; identical inputs give identical metrics (only `latency_ms` varies).
- **Observable:** logs go to `run.log` and stderr; stdout carries only the final JSON, so it is easy to pipe.
- **Robust:** validates config and data types, and tolerates CSV exports where every line is wrapped in quotes.
