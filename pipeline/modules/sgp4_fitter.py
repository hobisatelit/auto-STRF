"""Python-native SGP4 TLE fitter — headless replacement for rffit.

Reimplements the core fitting algorithm from rffit.c (fit_curve + compute_rms)
using the sgp4 Python library and scipy.optimize.minimize, so the entire
fitting process can run without PGPLOT / X11 / any GUI.

References:
    - rffit.c  lines 1630-1748 (fit_curve, compute_rms)
    - Draft Tugas Akhir, Persamaan 2.1, 2.9, 2.10
"""

from __future__ import annotations

import copy
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]
from sgp4.api import Satrec, WGS72  # type: ignore[import-untyped]
from sgp4.earth_gravity import wgs72  # type: ignore[import-untyped]
from sgp4 import exporter  # type: ignore[import-untyped]

LOG = logging.getLogger(__name__)

# ----- Constants (matching rffit.c) -----
C_KM_S = 299792.458  # speed of light in km/s


class DopplerPoint(NamedTuple):
    """A single Doppler measurement."""
    mjd: float
    freq_hz: float  # in kHz (as stored in STRF .dat files — actually Hz)
    flux: float
    site_id: int


class SiteInfo(NamedTuple):
    """Ground station coordinates."""
    site_id: int
    lat_deg: float
    lon_deg: float
    alt_m: float


class FitResult(NamedTuple):
    """Result of TLE fitting."""
    converged: bool
    rmse_before: float  # kHz
    rmse_after: float  # kHz
    tle_line1: str
    tle_line2: str
    tle_name: str
    iterations: int
    n_points: int


# ──────────────────────────────────────────────────────────────────────
# Data I/O
# ──────────────────────────────────────────────────────────────────────

def read_dat_file(dat_path: Path) -> list[DopplerPoint]:
    """Read STRF .dat file: MJD  freq_kHz  flux  site_id."""
    points: list[DopplerPoint] = []
    with dat_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                mjd = float(parts[0])
                freq = float(parts[1])  # Hz
                flux = float(parts[2])
                sid = int(parts[3])
                points.append(DopplerPoint(mjd, freq, flux, sid))
            except (ValueError, IndexError):
                continue
    return points


def read_tle_file(tle_path: Path) -> tuple[str, str, str]:
    """Read a 3-line TLE file → (name, line1, line2)."""
    lines = [
        l.strip()
        for l in tle_path.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    line1 = next((l for l in lines if l.startswith("1 ")), None)
    line2 = next((l for l in lines if l.startswith("2 ")), None)
    if line1 is None or line2 is None:
        raise ValueError(f"Invalid TLE file: {tle_path}")
    name_candidates = [
        l for l in lines if not l.startswith("1 ") and not l.startswith("2 ")
    ]
    name = name_candidates[0] if name_candidates else "UNKNOWN"
    return name, line1, line2


def read_sites_file(sites_path: Path) -> dict[int, SiteInfo]:
    """Read sites.txt → dict of site_id → SiteInfo."""
    sites: dict[int, SiteInfo] = {}
    if not sites_path.exists():
        return sites
    for line in sites_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            sid = int(parts[0])
            lat = float(parts[2])
            lon = float(parts[3])
            alt = float(parts[4])
            sites[sid] = SiteInfo(sid, lat, lon, alt)
        except (ValueError, IndexError):
            continue
    return sites


def write_tle_file(name: str, line1: str, line2: str, output_path: Path) -> None:
    """Write a 3-line TLE file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{name}\n{line1}\n{line2}\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# MJD / time helpers
# ──────────────────────────────────────────────────────────────────────

def mjd_to_jd(mjd: float) -> float:
    """Convert Modified Julian Date to Julian Date."""
    return mjd + 2400000.5


def mjd_to_datetime(mjd: float) -> datetime:
    """Convert MJD to a UTC datetime."""
    jd = mjd_to_jd(mjd)
    # JD 2451545.0 = 2000-01-01T12:00:00 UTC
    delta = jd - 2451545.0
    return datetime(2000, 1, 12, tzinfo=timezone.utc) + timedelta(days=delta)


# ──────────────────────────────────────────────────────────────────────
# SGP4 velocity computation
# ──────────────────────────────────────────────────────────────────────

def _site_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> np.ndarray:
    """Convert geodetic lat/lon/alt to ECEF (km) using WGS72 ellipsoid."""
    a = 6378.135  # WGS72 semi-major axis in km
    f = 1.0 / 298.26  # WGS72 flattening
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    alt_km = alt_m / 1000.0

    e2 = 2 * f - f * f
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    N = a / math.sqrt(1.0 - e2 * sin_lat ** 2)

    x = (N + alt_km) * cos_lat * math.cos(lon)
    y = (N + alt_km) * cos_lat * math.sin(lon)
    z = (N * (1 - e2) + alt_km) * sin_lat
    return np.array([x, y, z])


def _gmst_rad(jd: float) -> float:
    """Greenwich Mean Sidereal Time in radians (IAU simplified)."""
    T = (jd - 2451545.0) / 36525.0
    gmst_deg = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + \
               0.000387933 * T * T - T * T * T / 38710000.0
    return math.radians(gmst_deg % 360.0)


def _site_eci(lat_deg: float, lon_deg: float, alt_m: float, jd: float) -> np.ndarray:
    """Convert site geodetic coords to ECI at given Julian Date."""
    ecef = _site_ecef(lat_deg, lon_deg, alt_m)
    gmst = _gmst_rad(jd)
    cos_g = math.cos(gmst)
    sin_g = math.sin(gmst)
    # Rotate from ECEF to ECI
    eci = np.array([
        cos_g * ecef[0] - sin_g * ecef[1],
        sin_g * ecef[0] + cos_g * ecef[1],
        ecef[2],
    ])
    return eci


def _site_velocity_eci(lat_deg: float, lon_deg: float, alt_m: float, jd: float) -> np.ndarray:
    """Velocity of site in ECI frame (km/s) due to Earth rotation."""
    omega_earth = 7.2921151467e-5  # rad/s
    ecef = _site_ecef(lat_deg, lon_deg, alt_m)
    gmst = _gmst_rad(jd)
    cos_g = math.cos(gmst)
    sin_g = math.sin(gmst)
    # v = omega × r  in ECI
    vx = -omega_earth * (sin_g * ecef[0] + cos_g * ecef[1])
    vy = omega_earth * (cos_g * ecef[0] - sin_g * ecef[1])
    vz = 0.0
    return np.array([vx, vy, vz])


def compute_radial_velocity(satrec: Satrec, mjd: float, site: SiteInfo) -> float:
    """Compute radial velocity (km/s) of satellite relative to ground site.

    Positive = receding (redshift), negative = approaching (blueshift).
    This matches the convention in rffit.c velocity().
    """
    jd = mjd_to_jd(mjd)
    fr = 0.0  # fractional day

    # SGP4 propagation
    e, r_teme, v_teme = satrec.sgp4(jd, fr)
    if e != 0:
        LOG.warning("SGP4 error code %d at MJD %.6f", e, mjd)
        return 0.0

    r_sat = np.array(r_teme)  # km in TEME ≈ ECI for our purposes
    v_sat = np.array(v_teme)  # km/s

    # Site position and velocity in ECI
    r_site = _site_eci(site.lat_deg, site.lon_deg, site.alt_m, jd)
    v_site = _site_velocity_eci(site.lat_deg, site.lon_deg, site.alt_m, jd)

    # Relative position and velocity
    dr = r_sat - r_site
    dv = v_sat - v_site
    dist = np.linalg.norm(dr)
    if dist < 1e-6:
        return 0.0

    # Radial velocity = projection of relative velocity onto line of sight
    v_radial = float(np.dot(dv, dr) / dist)
    return v_radial


# ──────────────────────────────────────────────────────────────────────
# TLE ↔ orbital parameter vector
# ──────────────────────────────────────────────────────────────────────

def _tle_to_satrec(line1: str, line2: str) -> Satrec:
    """Parse TLE lines into a Satrec object."""
    return Satrec.twoline2rv(line1, line2, WGS72)


def _orbital_params_from_tle(line1: str, line2: str) -> np.ndarray:
    """Extract 7 fitting parameters from TLE lines.

    a[0] = inclination (deg)
    a[1] = RAAN (deg)
    a[2] = eccentricity
    a[3] = argument of perigee (deg)
    a[4] = mean anomaly (deg)
    a[5] = mean motion (rev/day)
    a[6] = B* drag term
    """
    incl = float(line2[8:16])
    raan = float(line2[17:25])
    ecc = float("0." + line2[26:33].strip())
    argp = float(line2[34:42])
    ma = float(line2[43:51])
    mm = float(line2[52:63])
    # B* from line1 cols 54-61
    bstar_str = line1[53:61].strip()
    bstar = _parse_bstar(bstar_str)
    return np.array([incl, raan, ecc, argp, ma, mm, bstar])


def _parse_bstar(s: str) -> float:
    """Parse STRF/NORAD B* format: e.g. ' 12345-4' → 0.12345e-4."""
    s = s.strip()
    if not s or s == "0" or s == "00000-0" or s == " 00000-0":
        return 0.0
    # Handle sign
    sign = 1.0
    if s.startswith("-"):
        sign = -1.0
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    # Format: NNNNN±E  meaning 0.NNNNN × 10^(±E)
    match = re.match(r"(\d+)([+-]\d)", s)
    if match:
        mantissa = float("0." + match.group(1))
        exponent = int(match.group(2))
        return sign * mantissa * (10.0 ** exponent)
    try:
        return sign * float(s)
    except ValueError:
        return 0.0


def _format_bstar(bstar: float) -> str:
    """Format B* drag term in TLE notation."""
    if bstar == 0.0:
        return " 00000-0"
    sign = " " if bstar >= 0 else "-"
    val = abs(bstar)
    exp = 0
    if val >= 1.0:
        while val >= 1.0:
            val /= 10.0
            exp += 1
    elif val < 0.1:
        while val < 0.1 and exp > -9:
            val *= 10.0
            exp -= 1
    mantissa = int(round(val * 100000))
    if mantissa >= 100000:
        mantissa = 99999
    return f"{sign}{mantissa:05d}{exp:+d}"


def _params_to_tle(params: np.ndarray, line1_template: str, line2_template: str) -> tuple[str, str]:
    """Rebuild TLE lines from 7 fitting parameters, preserving other fields."""
    incl = params[0] % 360.0
    raan = params[1] % 360.0
    ecc = max(0.0, min(0.9999999, params[2]))
    argp = params[3] % 360.0
    ma = params[4] % 360.0
    mm = max(0.05, params[5])
    bstar = params[6]

    # Rebuild line 1 with updated B*
    bstar_str = _format_bstar(bstar)
    l1 = line1_template[:53] + bstar_str + line1_template[61:]
    # Fix checksum
    l1 = l1[:68] + str(_tle_checksum(l1[:68]))

    # Rebuild line 2
    ecc_str = f"{ecc:.7f}"[2:]  # remove "0."
    l2 = (
        line2_template[:8]
        + f"{incl:8.4f}"
        + " "
        + f"{raan:8.4f}"
        + " "
        + ecc_str
        + " "
        + f"{argp:8.4f}"
        + " "
        + f"{ma:8.4f}"
        + " "
        + f"{mm:11.8f}"
        + line2_template[63:68]
    )
    l2 = l2[:68] + str(_tle_checksum(l2[:68]))

    return l1, l2


def _tle_checksum(line: str) -> int:
    """Compute TLE checksum (mod 10 of digit sum, minus=1)."""
    s = 0
    for ch in line:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return s % 10


# ──────────────────────────────────────────────────────────────────────
# Core fitting algorithm (matches rffit.c fit_curve + compute_rms)
# ──────────────────────────────────────────────────────────────────────

def compute_rms_khz(
    satrec: Satrec,
    points: list[DopplerPoint],
    site: SiteInfo,
    f_fit_khz: float,
) -> float:
    """Compute RMS residual in kHz between observed and predicted frequencies.

    Matches rffit.c compute_rms() — Persamaan 2.10 skripsi.
    """
    if not points:
        return float("inf")

    sum_sq = 0.0
    n = 0
    for pt in points:
        v_rad = compute_radial_velocity(satrec, pt.mjd, site)
        # f_predicted = (1 - v/c) * f_fit  (Persamaan 2.1)
        f_pred_khz = (1.0 - v_rad / C_KM_S) * f_fit_khz
        f_obs_khz = pt.freq_hz / 1000.0  # Hz → kHz
        residual = f_obs_khz - f_pred_khz
        sum_sq += residual ** 2
        n += 1

    if n == 0:
        return float("inf")
    return math.sqrt(sum_sq / n)


def estimate_ffit(
    satrec: Satrec,
    points: list[DopplerPoint],
    site: SiteInfo,
) -> float:
    """Estimate best-fit transmit frequency (kHz).

    Matches rffit.c fit_curve() frequency estimation (lines 1679-1696):
    f_fit = sum(fac * freq) / sum(fac²)  where fac = 1 - v/c
    """
    sum1 = 0.0
    sum2 = 0.0
    for pt in points:
        v_rad = compute_radial_velocity(satrec, pt.mjd, site)
        fac = 1.0 - v_rad / C_KM_S
        f_obs_khz = pt.freq_hz / 1000.0
        sum1 += fac * f_obs_khz
        sum2 += fac * fac
    if sum2 == 0:
        return 435880.0  # fallback to LAPAN-A2 beacon
    return sum1 / sum2


def _objective(
    params: np.ndarray,
    points: list[DopplerPoint],
    site: SiteInfo,
    line1_template: str,
    line2_template: str,
    fit_mask: list[bool],
    base_params: np.ndarray,
) -> float:
    """Objective function for scipy.optimize — chi-squared (Persamaan 2.9).

    Only varies parameters where fit_mask[i] is True.
    """
    # Merge fitted params back into full parameter vector
    full_params = base_params.copy()
    j = 0
    for i in range(7):
        if fit_mask[i]:
            full_params[i] = params[j]
            j += 1

    # Clamp eccentricity
    full_params[2] = max(0.0, min(0.9999, full_params[2]))
    # Clamp mean motion
    full_params[5] = max(0.05, full_params[5])

    try:
        l1, l2 = _params_to_tle(full_params, line1_template, line2_template)
        satrec = _tle_to_satrec(l1, l2)
    except Exception:
        return 1e12

    # Estimate f_fit for current orbital params
    f_fit = estimate_ffit(satrec, points, site)

    # Compute chi-squared
    chisq = 0.0
    for pt in points:
        v_rad = compute_radial_velocity(satrec, pt.mjd, site)
        f_pred = (1.0 - v_rad / C_KM_S) * f_fit
        f_obs = pt.freq_hz / 1000.0
        chisq += (f_obs - f_pred) ** 2

    return chisq


def fit_tle(
    dat_paths: list[Path],
    tle_path: Path,
    sites_path: Path,
    output_tle_path: Path,
    norad_id: int = 40931,
    fit_params: list[bool] | None = None,
    max_iterations: int = 2000,
    tolerance: float = 1e-10,
) -> dict:
    """Run full TLE fitting pipeline — headless replacement for rffit.

    Args:
        dat_paths: List of .dat files with Doppler measurements
        tle_path: Path to initial TLE file (3-line format)
        sites_path: Path to sites.txt
        output_tle_path: Where to write the fitted TLE
        norad_id: NORAD catalog ID
        fit_params: 7-element bool list for which params to optimize.
                    Default: [False, False, False, False, True, True, False]
                    (mean anomaly + mean motion)
        max_iterations: Max optimizer iterations
        tolerance: Convergence tolerance

    Returns:
        Dict with converged, rmse_before, rmse_after, etc.
    """
    # Default: fit mean anomaly (4) and mean motion (5) — the safest for
    # single-pass Doppler fitting (LAPAN-A2 LEO)
    if fit_params is None:
        fit_params = [False, False, False, False, True, True, False]

    # Read all data
    all_points: list[DopplerPoint] = []
    for dp in dat_paths:
        all_points.extend(read_dat_file(dp))
    if not all_points:
        LOG.error("No Doppler data points found in %s", dat_paths)
        return {
            "converged": False, "rmse_before": None, "rmse_after": None,
            "output_tle_path": str(output_tle_path), "n_points": 0,
        }

    LOG.info("Loaded %d Doppler data points from %d file(s)", len(all_points), len(dat_paths))

    # Read TLE
    name, line1, line2 = read_tle_file(tle_path)
    satrec_initial = _tle_to_satrec(line1, line2)

    # Read sites
    sites = read_sites_file(sites_path)

    # Determine site from data
    site_ids = set(pt.site_id for pt in all_points)
    primary_site_id = all_points[0].site_id
    if primary_site_id in sites:
        site = sites[primary_site_id]
    else:
        LOG.warning(
            "Site %d not found in sites.txt, using first available or default ITERA",
            primary_site_id,
        )
        if sites:
            site = next(iter(sites.values()))
        else:
            # Fallback to ITERA coordinates
            site = SiteInfo(primary_site_id, -5.121, 105.309, 96.0)

    # Compute RMSE before fitting
    f_fit_before = estimate_ffit(satrec_initial, all_points, site)
    rmse_before = compute_rms_khz(satrec_initial, all_points, site, f_fit_before)
    LOG.info("RMSE sebelum fitting: %.3f kHz (f_fit=%.3f MHz)", rmse_before, f_fit_before / 1000.0)

    # Extract orbital parameters
    base_params = _orbital_params_from_tle(line1, line2)

    # Build subset of params to optimize
    active_indices = [i for i, active in enumerate(fit_params) if active]
    if not active_indices:
        LOG.warning("Tidak ada parameter yang dipilih untuk fitting, mengaktifkan mean anomaly + mean motion")
        fit_params[4] = True
        fit_params[5] = True
        active_indices = [4, 5]

    x0 = np.array([base_params[i] for i in active_indices])

    LOG.info(
        "Fitting %d parameter(s): %s",
        len(active_indices),
        [["incl", "raan", "ecc", "argp", "ma", "mm", "bstar"][i] for i in active_indices],
    )

    # Run optimizer (Nelder-Mead, same as versafit simplex)
    result = minimize(
        _objective,
        x0,
        args=(all_points, site, line1, line2, fit_params, base_params),
        method="Nelder-Mead",
        options={
            "maxiter": max_iterations,
            "xatol": tolerance,
            "fatol": tolerance,
            "adaptive": True,
        },
    )

    # Reconstruct final TLE
    final_params = base_params.copy()
    j = 0
    for i in range(7):
        if fit_params[i]:
            final_params[i] = result.x[j]
            j += 1

    final_l1, final_l2 = _params_to_tle(final_params, line1, line2)

    # Compute RMSE after fitting
    satrec_final = _tle_to_satrec(final_l1, final_l2)
    f_fit_after = estimate_ffit(satrec_final, all_points, site)
    rmse_after = compute_rms_khz(satrec_final, all_points, site, f_fit_after)

    converged = rmse_after < rmse_before
    LOG.info(
        "RMSE sesudah fitting: %.3f kHz (f_fit=%.3f MHz) — %s",
        rmse_after,
        f_fit_after / 1000.0,
        "IMPROVED ✅" if converged else "NOT IMPROVED ❌",
    )

    # Write output TLE
    write_tle_file(name, final_l1, final_l2, output_tle_path)
    LOG.info("TLE tersimpan ke %s", output_tle_path)

    return {
        "converged": converged,
        "rmse_before": round(rmse_before, 6),
        "rmse_after": round(rmse_after, 6),
        "f_fit_mhz": round(f_fit_after / 1000.0, 6),
        "output_tle_path": str(output_tle_path),
        "tle_line1": final_l1,
        "tle_line2": final_l2,
        "iterations": result.nit if hasattr(result, "nit") else 0,
        "n_points": len(all_points),
        "optimizer_success": result.success,
        "optimizer_message": result.message,
    }
