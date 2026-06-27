"""Wrapper untuk fitting TLE dan utilitas terkait.

Pada pipeline otomatis, modul ini memanggil sgp4_fitter.fit_tle() secara
langsung (Python-native) tanpa memerlukan binary rffit atau PGPLOT/X11.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import requests

LOG = logging.getLogger(__name__)


def run_rffit(
    doppler_file_path,
    initial_tle_path,
    output_tle_path,
    strf_bin_path=None,
    norad_id=None,
    site_id=None,
    timeout_seconds=120,
):
    """Jalankan fitting TLE secara headless menggunakan Python-native SGP4 fitter.

    Menggantikan binary rffit yang memerlukan PGPLOT X11 interaktif.
    Memanggil sgp4_fitter.fit_tle() secara langsung.
    """
    from modules import sgp4_fitter

    norad_id = int(norad_id or config.NORAD_ID)
    output_tle = Path(output_tle_path)

    # Normalize doppler file paths
    if isinstance(doppler_file_path, list):
        dat_paths = [Path(p) for p in doppler_file_path]
    else:
        dat_paths = [Path(doppler_file_path)]

    # Validate inputs
    tle_file = Path(initial_tle_path)
    if not tle_file.exists():
        raise FileNotFoundError(f"File TLE awal tidak ditemukan: {tle_file}")

    for dp in dat_paths:
        if not dp.exists():
            raise FileNotFoundError(f"File Doppler tidak ditemukan: {dp}")

    # Determine sites.txt path
    sites_path = config.SITES_TXT
    if not sites_path.exists():
        # Try data/sites.txt
        alt_sites = config.DATA_DIR / "sites.txt"
        if alt_sites.exists():
            sites_path = alt_sites

    LOG.info(
        "Menjalankan Python-native SGP4 fitter untuk %d file Doppler",
        len(dat_paths),
    )

    # Get fitting parameters from config
    fit_params = getattr(config, "SGP4_FIT_PARAMS", None)
    max_iter = getattr(config, "FIT_MAX_ITERATIONS", 2000)
    tol = getattr(config, "FIT_TOLERANCE", 1e-10)

    result = sgp4_fitter.fit_tle(
        dat_paths=dat_paths,
        tle_path=tle_file,
        sites_path=sites_path,
        output_tle_path=output_tle,
        norad_id=norad_id,
        fit_params=fit_params,
        max_iterations=max_iter,
        tolerance=tol,
    )

    return result


def fetch_initial_tle(norad_id, output_path):
    """Ambil TLE terbaru dari Celestrak dan simpan sebagai file 3 baris."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    urls = [
        "https://amsat-id.org/tle.txt",
        f"https://www.space-track.org/basicspacedata/query/class/gp/NORAD_CAT_ID/{int(norad_id)}/orderby/TLE_LINE1%20ASC/format/tle",
        f"https://celestrak.org/NORAD/elements/gp.php?CATNR={int(norad_id)}&FORMAT=TLE",
        f"https://celestrak.org/SATCAT/TLE.php?CATNR={int(norad_id)}",
    ]
    last_error = None
    for url in urls:
        try:
            response = requests.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            lines = [
                line.strip() for line in response.text.splitlines() if line.strip()
            ]
            tle_lines = [
                line for line in lines if line.startswith("1 ") or line.startswith("2 ")
            ]
            name_lines = [
                line
                for line in lines
                if not line.startswith("1 ") and not line.startswith("2 ")
            ]
            if len(tle_lines) >= 2:
                name = name_lines[0] if name_lines else f"NORAD {norad_id}"
                output_path.write_text(
                    f"{name}\n{tle_lines[0]}\n{tle_lines[1]}\n", encoding="utf-8"
                )
                return str(output_path)
        except requests.RequestException as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Gagal mengambil TLE awal dari Celestrak: {last_error}")


def _tle_epoch_to_datetime(line1: str) -> datetime | None:
    try:
        year_short = int(line1[18:20])
        day_of_year = float(line1[20:32])
        year = 2000 + year_short if year_short < 57 else 1900 + year_short
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        return start + timedelta(days=day_of_year - 1.0)
    except Exception:
        return None


def read_tle_from_file(tle_path):
    """Baca file TLE dan return dict berisi nama, line1, line2, epoch."""
    tle_path = Path(tle_path)
    lines = [
        line.strip()
        for line in tle_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    line1 = next((line for line in lines if line.startswith("1 ")), None)
    line2 = next((line for line in lines if line.startswith("2 ")), None)
    if line1 is None or line2 is None:
        raise ValueError(f"File bukan TLE valid: {tle_path}")
    name_candidates = [
        line
        for line in lines
        if not line.startswith("1 ") and not line.startswith("2 ")
    ]
    return {
        "name": name_candidates[0] if name_candidates else "",
        "line1": line1,
        "line2": line2,
        "epoch": _tle_epoch_to_datetime(line1),
    }


def copy_initial_tle_if_needed(initial_tle_path, output_tle_path):
    """Utilitas eksplisit untuk menyalin TLE awal bila pengguna ingin baseline."""
    output_tle = Path(output_tle_path)
    output_tle.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(initial_tle_path, output_tle)
    return str(output_tle)
