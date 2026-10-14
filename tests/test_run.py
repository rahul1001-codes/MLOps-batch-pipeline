import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_job(tmp_path, csv_text, config_text="seed: 42\nwindow: 3\nversion: \"v1\"\n"):
    data, cfg = tmp_path / "data.csv", tmp_path / "config.yaml"
    data.write_text(csv_text)
    cfg.write_text(config_text)
    out, log = tmp_path / "metrics.json", tmp_path / "run.log"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--input", str(data), "--config", str(cfg),
         "--output", str(out), "--log-file", str(log)], capture_output=True, text=True)
    return proc, json.loads(out.read_text()), log


CSV = "timestamp,close\n1,10\n2,12\n3,11\n4,15\n5,9\n"


def test_success_metrics_schema(tmp_path):
    proc, m, log = run_job(tmp_path, CSV)
    assert proc.returncode == 0
    assert set(m) == {"version", "rows_processed", "metric", "value", "latency_ms", "seed", "status"}
    assert m["status"] == "success" and m["rows_processed"] == 5 and m["metric"] == "signal_rate"
    assert json.loads(proc.stdout) == m  # stdout is pure JSON
    assert "Job started" in log.read_text() and "Job ended successfully" in log.read_text()


def test_signal_value_is_correct(tmp_path):
    # window=3 rolling means: NaN, NaN, 11, 12.67, 11.67 -> signals 0,0,0,1,0 -> 0.2
    _, m, _ = run_job(tmp_path, CSV)
    assert m["value"] == 0.2


def test_deterministic(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    _, m1, _ = run_job(tmp_path / "a", CSV)
    _, m2, _ = run_job(tmp_path / "b", CSV)
    assert m1["value"] == m2["value"] and m1["seed"] == m2["seed"]


def test_quoted_csv_is_handled(tmp_path):
    quoted = "\n".join(f'"{ln}"' for ln in CSV.strip().splitlines()) + "\n"
    proc, m, _ = run_job(tmp_path, quoted)
    assert proc.returncode == 0 and m["rows_processed"] == 5


@pytest.mark.parametrize("csv_text,msg", [
    ("", "empty"),
    ("timestamp,open\n1,2\n", "Missing required column: 'close'"),
    ("close\nabc\ndef\n", "no numeric values"),
])
def test_invalid_input_writes_error(tmp_path, csv_text, msg):
    proc, m, _ = run_job(tmp_path, csv_text)
    assert proc.returncode == 1 and m["status"] == "error" and msg in m["error_message"]


def test_missing_config_field(tmp_path):
    proc, m, _ = run_job(tmp_path, CSV, config_text="seed: 1\nversion: v1\n")
    assert proc.returncode == 1 and "Missing config field: window" in m["error_message"]


def test_invalid_window(tmp_path):
    proc, m, _ = run_job(tmp_path, CSV, config_text="seed: 1\nwindow: 0\nversion: v1\n")
    assert proc.returncode == 1 and "window" in m["error_message"]


def test_missing_input_file(tmp_path):
    cfg = tmp_path / "c.yaml"; cfg.write_text("seed: 1\nwindow: 2\nversion: v1\n")
    out = tmp_path / "m.json"
    proc = subprocess.run([sys.executable, str(ROOT / "run.py"), "--input", str(tmp_path / "nope.csv"),
                           "--config", str(cfg), "--output", str(out), "--log-file", str(tmp_path / "l.log")],
                          capture_output=True, text=True)
    assert proc.returncode == 1 and json.loads(out.read_text())["status"] == "error"


def test_repo_dataset_runs():
    df = pd.read_csv(ROOT / "data.csv")
    assert "close" in df.columns and len(df) == 10000
