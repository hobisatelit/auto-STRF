#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STRF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
STATUS_OK=0
STATUS_WARN=0
STATUS_FAIL=0

ok() { echo "✓ $1"; STATUS_OK=$((STATUS_OK + 1)); }
warn() { echo "⚠ $1"; STATUS_WARN=$((STATUS_WARN + 1)); }
fail() { echo "✗ $1"; STATUS_FAIL=$((STATUS_FAIL + 1)); }

install_system_deps() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "Mendeteksi Debian/Ubuntu. Menginstal dependensi sistem..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip python3-venv git curl wget gcc gfortran make libopencv-dev libpng-dev libx11-dev libgsl-dev libfftw3-dev libsox-dev || return 1
  elif command -v pacman >/dev/null 2>&1; then
    echo "Mendeteksi Arch Linux. Menginstal dependensi sistem..."
    sudo pacman -Sy --needed python python-pip git curl wget gcc gcc-fortran make opencv gsl fftw libpng sox libx11 || return 1
  elif command -v brew >/dev/null 2>&1; then
    echo "Mendeteksi macOS/Homebrew. Menginstal dependensi sistem..."
    brew install python git curl wget gcc make opencv gsl fftw libpng sox pgplot || return 1
  else
    warn "Package manager tidak dikenali. Lewati instalasi dependensi sistem."
    return 0
  fi
}

create_venv() {
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" || return 1
  fi
  "$PYTHON_BIN" -m pip install --upgrade pip || return 1
  "$PIP_BIN" install opencv-python-headless numpy scipy requests rich astropy matplotlib tqdm sgp4 || return 1
}

compile_strf_if_needed() {
  if [ -x "$STRF_ROOT/rffit" ]; then
    ok "Binary rffit sudah tersedia"
    return 0
  fi

  warn "Binary rffit belum ada. Mencoba kompilasi STRF dengan make..."
  (cd "$STRF_ROOT" && make) || return 1

  if [ -x "$STRF_ROOT/rffit" ]; then
    ok "Binary rffit berhasil dibuat"
    return 0
  fi
  return 1
}

mkdir -p "$SCRIPT_DIR/data/waterfall" "$SCRIPT_DIR/data/metadata" "$SCRIPT_DIR/data/doppler_curves" "$SCRIPT_DIR/data/tle_output" "$SCRIPT_DIR/logs"
[ -f "$SCRIPT_DIR/logs/pipeline.log" ] || touch "$SCRIPT_DIR/logs/pipeline.log"
ok "Direktori data dan logs siap"

if install_system_deps; then
  ok "Dependensi sistem selesai dicek/diinstal"
else
  fail "Instalasi dependensi sistem gagal"
fi

if create_venv; then
  ok "Virtual environment dan paket Python siap di pipeline/venv"
else
  fail "Pembuatan venv atau instalasi paket Python gagal"
fi

if compile_strf_if_needed; then
  ok "Pemeriksaan binary STRF selesai"
else
  fail "Kompilasi STRF gagal. Cek dependensi PGPLOT/GSL/FFTW/SOX."
fi

cat <<EOF

Ringkasan instalasi:
  ✓ Berhasil : $STATUS_OK
  ⚠ Peringatan: $STATUS_WARN
  ✗ Gagal    : $STATUS_FAIL

Jalankan UI pipeline dengan:
  $PYTHON_BIN $SCRIPT_DIR/main.py
EOF

if [ "$STATUS_FAIL" -gt 0 ]; then
  exit 1
fi
