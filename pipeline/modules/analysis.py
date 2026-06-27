"""Analisis komparatif hasil fitting TLE."""

from __future__ import annotations

import statistics
from datetime import datetime
from pathlib import Path


def _mean(values):
    clean = [float(value) for value in values if value is not None]
    return statistics.fmean(clean) if clean else None


def _percent_drop(before, after):
    if before is None or after is None or before == 0:
        return None
    return 100.0 * (before - after) / before


def compare_rmse(results_itera, results_global):
    """Bandingkan RMSE antara hasil ITERA dan global SatNOGS."""
    itera_before = _mean([result.get("rmse_before") for result in results_itera])
    itera_after = _mean([result.get("rmse_after") for result in results_itera])
    global_before = _mean([result.get("rmse_before") for result in results_global])
    global_after = _mean([result.get("rmse_after") for result in results_global])

    return {
        "itera": {
            "n": len(results_itera),
            "rmse_before_avg": itera_before,
            "rmse_after_avg": itera_after,
            "improvement_percent": _percent_drop(itera_before, itera_after),
            "position_error_after_km": rmse_to_position_error_km(itera_after)
            if itera_after is not None
            else None,
        },
        "global": {
            "n": len(results_global),
            "rmse_before_avg": global_before,
            "rmse_after_avg": global_after,
            "improvement_percent": _percent_drop(global_before, global_after),
            "position_error_after_km": rmse_to_position_error_km(global_after)
            if global_after is not None
            else None,
        },
    }


def _extract_tle_lines(path):
    lines = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    line1 = next((line for line in lines if line.startswith("1 ")), None)
    line2 = next((line for line in lines if line.startswith("2 ")), None)
    if line1 is None or line2 is None:
        raise ValueError(f"File TLE tidak valid: {path}")
    return line1, line2


def _parse_line2(line2: str) -> dict:
    # Format TLE line 2 fixed-width: satno inc raan ecc argp ma mean_motion rev
    return {
        "inclination_deg": float(line2[8:16]),
        "raan_deg": float(line2[17:25]),
        "eccentricity": float("0." + line2[26:33].strip()),
        "arg_perigee_deg": float(line2[34:42]),
        "mean_anomaly_deg": float(line2[43:51]),
        "mean_motion_rev_day": float(line2[52:63]),
    }


def _angle_diff_deg(a, b):
    return ((a - b + 180.0) % 360.0) - 180.0


def validate_against_spacetrack(fitted_tle_path, reference_tle_path):
    """Bandingkan parameter orbital TLE hasil automasi dengan TLE referensi."""
    _, fitted_line2 = _extract_tle_lines(fitted_tle_path)
    _, reference_line2 = _extract_tle_lines(reference_tle_path)
    fitted = _parse_line2(fitted_line2)
    reference = _parse_line2(reference_line2)

    return {
        "inclination_deg": fitted["inclination_deg"] - reference["inclination_deg"],
        "eccentricity": fitted["eccentricity"] - reference["eccentricity"],
        "mean_motion_rev_day": fitted["mean_motion_rev_day"]
        - reference["mean_motion_rev_day"],
        "raan_deg": _angle_diff_deg(fitted["raan_deg"], reference["raan_deg"]),
        "arg_perigee_deg": _angle_diff_deg(
            fitted["arg_perigee_deg"], reference["arg_perigee_deg"]
        ),
        "mean_anomaly_deg": _angle_diff_deg(
            fitted["mean_anomaly_deg"], reference["mean_anomaly_deg"]
        ),
    }


def rmse_to_position_error_km(rmse_khz, beacon_freq_mhz=435.88):
    """Konversi RMSE frekuensi kHz ke estimasi error posisi kilometer."""
    if rmse_khz is None:
        return None
    # Faktor LAPAN-A2 sesuai parameter skripsi: sekitar 644 km/kHz.
    return float(rmse_khz) * 644.0


def generate_report(all_results, output_path):
    """Buat laporan teks ringkas hasil pipeline."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results = (
        all_results if isinstance(all_results, list) else all_results.get("results", [])
    )
    comparison = (
        all_results.get("comparison") if isinstance(all_results, dict) else None
    )

    before_avg = _mean([result.get("rmse_before") for result in results])
    after_avg = _mean([result.get("rmse_after") for result in results])

    lines = [
        "STRF Automation Pipeline — Laporan Hasil",
        f"Dibuat: {datetime.utcnow().isoformat(timespec='seconds')} UTC",
        "",
        f"Jumlah observasi diproses: {len(results)}",
        f"RMSE rata-rata sebelum fitting: {before_avg if before_avg is not None else 'n/a'} kHz",
        f"RMSE rata-rata sesudah fitting: {after_avg if after_avg is not None else 'n/a'} kHz",
    ]

    if before_avg is not None and after_avg is not None:
        lines.append(f"Penurunan RMSE: {_percent_drop(before_avg, after_avg):.2f}%")
        lines.append(
            f"Estimasi error posisi akhir: {rmse_to_position_error_km(after_avg):.2f} km"
        )

    if comparison:
        lines.extend(["", "Komparasi ITERA vs Global:"])
        for label, data in comparison.items():
            lines.append(
                f"- {label}: n={data.get('n')}, sebelum={data.get('rmse_before_avg')}, "
                f"sesudah={data.get('rmse_after_avg')}, peningkatan={data.get('improvement_percent')}%"
            )

    if isinstance(all_results, dict) and all_results.get("validation"):
        lines.extend(["", "Validasi TLE referensi:"])
        for key, value in all_results["validation"].items():
            lines.append(f"- {key}: {value}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(output_path)
