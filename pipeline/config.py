"""Konfigurasi global STRF Automation Pipeline.

Semua path dibuat relatif terhadap direktori `pipeline/` agar tidak bergantung
pada lokasi absolut komputer pengguna.
"""

from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
STRF_ROOT = PIPELINE_ROOT.parent
DATA_DIR = PIPELINE_ROOT / "data"
LOG_DIR = PIPELINE_ROOT / "logs"

WATERFALL_DIR = DATA_DIR / "waterfall"
WATERFALL_MARKED_DIR = DATA_DIR / "waterfall_marked"
METADATA_DIR = DATA_DIR / "metadata"
DOPPLER_DIR = DATA_DIR / "doppler_curves"
TLE_OUTPUT_DIR = DATA_DIR / "tle_output"
SITES_TXT = DATA_DIR / "sites.txt"
PIPELINE_LOG = LOG_DIR / "pipeline.log"
PROCESSED_OBS_PATH = LOG_DIR / "processed_obs.json"

# Parameter teknis LAPAN-A2
NORAD_ID = 40931
SATELLITE_NAME = "LAPAN-A2"
BEACON_FREQ_HZ = 435_880_000
DOPPLER_MAX_KHZ = 3.5
MIN_ELEVATION_DEG = 30

# Koordinat Stasiun Bumi ITERA, Lampung Selatan
ITERA_LAT = -5.121
ITERA_LON = 105.309
ITERA_ALT = 96
DEFAULT_STRF_SITE_ID = 9999
SATNOGS_STRF_SITE_PREFIX = 7000

# Parameter OpenCV untuk waterfall SatNOGS (Bab 3.4.2)
GAUSSIAN_KERNEL_SIZE = (5, 5)
N_MIN_PIXELS = 5  # Persamaan 2.5: batas minimum piksel sinyal per baris

# Validasi kurva
MIN_VALID_CURVE_FRACTION = 0.10
MAX_CURVE_GAP_FRACTION = 0.20

# Rentang waterfall SatNOGS sering berupa 48 kHz di sekitar frekuensi pusat.
# Nilai ini dipakai bila metadata tidak menyediakan f_min/f_max eksplisit.
WATERFALL_BANDWIDTH_HZ = 48_000
INVERT_WATERFALL_TIME_AXIS = True

# SatNOGS API
SATNOGS_API_BASE = "https://db.satnogs.org/api"
SATNOGS_NETWORK_API_BASE = "https://network.satnogs.org/api"
SATNOGS_API_TOKEN = ""
REQUEST_TIMEOUT_SECONDS = 30

# ── SGP4 Python-Native Fitter Parameters ──
# Parameter mana yang di-fit: [incl, raan, ecc, argp, ma, mm, bstar]
# Default: fit mean anomaly + mean motion (paling aman untuk single-pass LEO)
SGP4_FIT_PARAMS = [False, False, False, False, True, True, False]
FIT_MAX_ITERATIONS = 2000
FIT_TOLERANCE = 1e-10

# Referensi TLE
TLE_REFERENCE_SOURCE = "https://amsat-id.org/tle.txt"
SPACETRACK_BASE = "https://www.space-track.org"

PYTHON_PACKAGES = [
    "opencv-python-headless",
    "numpy",
    "scipy",
    "requests",
    "rich",
    "astropy",
    "matplotlib",
    "tqdm",
    "sgp4",
]


def ensure_directories() -> None:
    """Buat direktori output pipeline jika belum ada."""
    for path in [WATERFALL_DIR, WATERFALL_MARKED_DIR, METADATA_DIR, DOPPLER_DIR, TLE_OUTPUT_DIR, LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def as_dict() -> dict:
    """Return konfigurasi utama untuk ditampilkan di UI."""
    return {
        "NORAD_ID": NORAD_ID,
        "SATELLITE_NAME": SATELLITE_NAME,
        "BEACON_FREQ_HZ": BEACON_FREQ_HZ,
        "DOPPLER_MAX_KHZ": DOPPLER_MAX_KHZ,
        "MIN_ELEVATION_DEG": MIN_ELEVATION_DEG,
        "ITERA_LAT": ITERA_LAT,
        "ITERA_LON": ITERA_LON,
        "ITERA_ALT": ITERA_ALT,
        "DEFAULT_STRF_SITE_ID": DEFAULT_STRF_SITE_ID,
        "GAUSSIAN_KERNEL_SIZE": GAUSSIAN_KERNEL_SIZE,
        "N_MIN_PIXELS": N_MIN_PIXELS,
        "WATERFALL_BANDWIDTH_HZ": WATERFALL_BANDWIDTH_HZ,
        "SATNOGS_API_BASE": SATNOGS_API_BASE,
        "SATNOGS_NETWORK_API_BASE": SATNOGS_NETWORK_API_BASE,
        "SGP4_FIT_PARAMS": SGP4_FIT_PARAMS,
        "FIT_MAX_ITERATIONS": FIT_MAX_ITERATIONS,
        "FIT_TOLERANCE": FIT_TOLERANCE,
    }
