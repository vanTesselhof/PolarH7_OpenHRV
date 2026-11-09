"""Transparent time-domain analysis with raw RR values preserved separately."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

# Five minutes is the conventional stationary short-term HRV window.
MIN_RECORDING_SECONDS = 300.0
MIN_VALID_INTERVALS = 30
MAX_ARTIFACT_FRACTION = 0.20
PHYSIOLOGICAL_RANGE_MS = (300.0, 2000.0)
LOCAL_DEVIATION_FRACTION = 0.20
LOCAL_DEVIATION_FLOOR_MS = 200.0


def _read_raw(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"rr_ms", "relative_time_s"}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError("Die Datei enthält keine auswertbaren RR-Daten.")
    return frame.to_dict(orient="records")


def mark_artifacts(rr_values: list[float]) -> list[str]:
    """Flag physiological extremes and isolated local deviations; never alter values."""
    flags = [""] * len(rr_values)
    low, high = PHYSIOLOGICAL_RANGE_MS
    for index, value in enumerate(rr_values):
        if not math.isfinite(value) or not low <= value <= high:
            flags[index] = "outside_300_2000_ms"
            continue
        neighbors = [rr_values[j] for j in range(max(0, index - 2), min(len(rr_values), index + 3))
                     if j != index and math.isfinite(rr_values[j]) and low <= rr_values[j] <= high]
        if len(neighbors) >= 2:
            baseline = median(neighbors)
            threshold = max(LOCAL_DEVIATION_FLOOR_MS, baseline * LOCAL_DEVIATION_FRACTION)
            if abs(value - baseline) > threshold:
                flags[index] = "local_deviation_over_20pct_or_200_ms"
    return flags


def _write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ("metric", "value", "unit", "status", "valid_intervals", "artifact_intervals",
              "artifact_fraction", "measurement_duration_s", "method")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plot_rr(path: Path, times: list[float], rr_values: list[float], flags: list[str]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    good_x = [t for t, flag in zip(times, flags) if not flag]
    good_y = [v for v, flag in zip(rr_values, flags) if not flag]
    bad_x = [t for t, flag in zip(times, flags) if flag]
    bad_y = [v for v, flag in zip(rr_values, flags) if flag]
    fig, ax = plt.subplots(figsize=(11, 4.5), constrained_layout=True)
    if good_x:
        ax.plot(good_x, good_y, color="#167d9a", linewidth=0.9, marker=".", markersize=3,
                label="Rohintervall (nicht markiert)")
    if bad_x:
        ax.scatter(bad_x, bad_y, color="#d7443e", marker="x", s=28, label="Artefaktmarkierung")
    ax.set(title="RR-Intervalle", xlabel="Zeit seit Messbeginn (s)", ylabel="RR-Intervall (ms)")
    ax.grid(True, alpha=0.25)
    if good_x or bad_x:
        ax.legend()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def analyze_session(raw_csv: Path) -> dict[str, Any]:
    """Create analysis_rr.csv, hrv_results.csv, rr_plot.png and return a summary."""
    raw_csv = Path(raw_csv)
    session_dir = raw_csv.parent
    source_rows = _read_raw(raw_csv)
    rr_values = [float(row["rr_ms"]) for row in source_rows]
    times = [float(row["relative_time_s"]) for row in source_rows]
    flags = mark_artifacts(rr_values)
    valid_indices = [i for i, flag in enumerate(flags) if not flag]
    artifact_count = len(flags) - len(valid_indices)
    artifact_fraction = artifact_count / len(flags)
    duration_s = max(times) - min(times) if len(times) > 1 else 0.0
    qualified = (len(valid_indices) >= MIN_VALID_INTERVALS
                 and duration_s >= MIN_RECORDING_SECONDS
                 and artifact_fraction <= MAX_ARTIFACT_FRACTION)

    analysis_path = session_dir / "analysis_rr.csv"
    fields = ("sequence", "relative_time_s", "raw_rr_ms", "artifact_flag", "analysis_rr_ms",
              "correction_method")
    with analysis_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source, rr, flag in zip(source_rows, rr_values, flags):
            writer.writerow({"sequence": source.get("sequence", ""),
                             "relative_time_s": source.get("relative_time_s", ""),
                             "raw_rr_ms": f"{rr:.3f}",
                             "artifact_flag": flag,
                             "analysis_rr_ms": "" if flag else f"{rr:.3f}",
                             "correction_method": "flag_only; raw value unchanged"})

    method = ("Mean instantaneous HR = mean(60000 / accepted NN ms); SDNN = sample standard deviation; "
              "RMSSD and pNN50 use adjacent pairs only when both intervals are accepted. "
              "Artifacts are flagged and excluded, never corrected or interpolated.")
    status = ("minimum_thresholds_met_stationarity_unassessed" if qualified
              else "insufficient_quality_or_duration")
    accepted = np.asarray([rr_values[i] for i in valid_indices], dtype=float)
    metric_values: dict[str, tuple[float | None, str]] = {
        "mean_hr_bpm": (float(np.mean(60_000.0 / accepted)) if len(accepted) else None, "bpm"),
        "mean_nn_ms": (float(np.mean(accepted)) if len(accepted) else None, "ms"),
        "sdnn_ms": (float(np.std(accepted, ddof=1)) if len(accepted) >= 2 else None, "ms"),
    }
    adjacent_diffs = [abs(rr_values[i] - rr_values[i - 1]) for i in range(1, len(rr_values))
                      if not flags[i] and not flags[i - 1]]
    differences = np.asarray(adjacent_diffs, dtype=float)
    metric_values["rmssd_ms"] = (float(np.sqrt(np.mean(np.square(differences))))
                                 if len(differences) else None, "ms")
    metric_values["pnn50_percent"] = (float(np.mean(differences > 50.0) * 100.0)
                                      if len(differences) else None, "%")
    summary_rows: list[dict[str, Any]] = []
    for metric, (value, unit) in metric_values.items():
        summary_rows.append({"metric": metric,
                             "value": (f"{value:.6f}" if value is not None and qualified else ""),
                             "unit": unit, "status": status if qualified else "suppressed_by_quality_gate",
                             "valid_intervals": len(valid_indices), "artifact_intervals": artifact_count,
                             "artifact_fraction": f"{artifact_fraction:.6f}",
                             "measurement_duration_s": f"{duration_s:.3f}", "method": method})
    summary_rows.append({"metric": "artifact_fraction", "value": f"{artifact_fraction:.6f}",
                         "unit": "fraction", "status": "reported", "valid_intervals": len(valid_indices),
                         "artifact_intervals": artifact_count, "artifact_fraction": f"{artifact_fraction:.6f}",
                         "measurement_duration_s": f"{duration_s:.3f}",
                         "method": "Flagged count / total count using documented rules in README."})
    _write_results(session_dir / "hrv_results.csv", summary_rows)
    _plot_rr(session_dir / "rr_plot.png", times, rr_values, flags)
    return {"status": status, "valid_intervals": len(valid_indices), "artifact_intervals": artifact_count,
            "artifact_fraction": artifact_fraction, "duration_s": duration_s,
            "metrics": {key: (value if qualified else None) for key, (value, _) in metric_values.items()},
            "directory": session_dir}
