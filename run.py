"""MLOps batch job: rolling-mean trading signal generator.

Reads OHLCV price data and a YAML config, computes a rolling mean of `close`,
emits a binary signal (1 if close > rolling mean else 0) and writes metrics as JSON.

Example:
    python run.py --input data.csv --config config.yaml --output metrics.json --log-file run.log
"""
import argparse
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger("signal_job")


def setup_logging(log_file):
    """Log to file (full detail) and to stderr (so stdout stays clean JSON)."""
    log_dir = os.path.dirname(os.path.abspath(log_file))
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    for handler in (logging.FileHandler(log_file, mode="w"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        logger.addHandler(handler)


def write_metrics(output_path, metrics):
    """Write metrics JSON to disk and print the same JSON to stdout."""
    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=4)
    print(json.dumps(metrics, indent=4))


def load_config(path):
    """Load and validate config.yaml (requires seed, window, version)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError("Config file is empty or not a valid YAML mapping")
    for field in ("seed", "window", "version"):
        if field not in config:
            raise ValueError(f"Missing config field: {field}")
    if not isinstance(config["seed"], int) or isinstance(config["seed"], bool):
        raise ValueError("Config field 'seed' must be an integer")
    if not isinstance(config["window"], int) or isinstance(config["window"], bool) or config["window"] < 1:
        raise ValueError("Config field 'window' must be a positive integer")
    return config


def read_input(path):
    """Read the CSV. Tolerates files where every line is wrapped in quotes (a common export bug)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")
    try:
        df = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"Input CSV is invalid or empty: {exc}")
    if df.shape[1] == 1 and "," in str(df.columns[0]):
        logger.warning("CSV rows are wrapped in quotes; re-parsing with quote stripping")
        with open(path, "r", newline="") as f:
            lines = [ln.strip().strip('"') for ln in f if ln.strip()]
        from io import StringIO
        df = pd.read_csv(StringIO("\n".join(lines)))
    if df.empty:
        raise ValueError("Input CSV is empty")
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "close" not in df.columns:
        raise ValueError("Missing required column: 'close'")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if df["close"].isna().all():
        raise ValueError("Column 'close' contains no numeric values")
    return df


def compute_signal(df, window):
    """rolling_mean over `close`; signal = 1 if close > rolling_mean else 0.

    The first (window - 1) rows have no rolling mean; comparisons with NaN are False,
    so their signal is 0 (documented in the README).
    """
    df = df.copy()
    df["rolling_mean"] = df["close"].rolling(window=window).mean()
    df["signal"] = np.where(df["close"] > df["rolling_mean"], 1, 0)
    return df


def main(argv=None):
    start = time.time()
    parser = argparse.ArgumentParser(description="Rolling-mean signal batch job")
    parser.add_argument("--input", required=True, help="Path to input data.csv")
    parser.add_argument("--config", required=True, help="Path to config.yaml")
    parser.add_argument("--output", required=True, help="Path to output metrics.json")
    parser.add_argument("--log-file", required=True, help="Path to run.log")
    args = parser.parse_args(argv)

    setup_logging(args.log_file)
    logger.info("Job started")
    version = "unknown"
    try:
        config = load_config(args.config)
        version, seed, window = config["version"], config["seed"], config["window"]
        np.random.seed(seed)  # deterministic runs
        logger.info(f"Config loaded and validated: seed={seed}, window={window}, version={version}")

        df = read_input(args.input)
        logger.info(f"Dataset loaded: {len(df)} rows, columns={list(df.columns)}")

        logger.info(f"Computing rolling mean with window={window}")
        df = compute_signal(df, window)
        logger.info("Signals generated")

        metrics = {
            "version": version,
            "rows_processed": int(len(df)),
            "metric": "signal_rate",
            "value": round(float(df["signal"].mean()), 4),
            "latency_ms": int((time.time() - start) * 1000),
            "seed": seed,
            "status": "success",
        }
        logger.info(f"Metrics summary: {metrics}")
        write_metrics(args.output, metrics)
        logger.info("Job ended successfully")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level handler writes error metrics
        logger.error(f"Error occurred: {exc}")
        write_metrics(args.output, {"version": version, "status": "error", "error_message": str(exc)})
        logger.info("Job ended with error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
