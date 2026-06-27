#!/bin/bash
# Script untuk mendaftarkan pipeline STRF ke cronjob Linux
# Berjalan setiap 1 jam untuk mengecek observasi terbaru secara otomatis.

set -e

PIPELINE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
MAIN_SCRIPT="${PIPELINE_DIR}/main.py"
LOG_FILE="${PIPELINE_DIR}/logs/cron.log"
VENV_PYTHON="${PIPELINE_DIR}/venv/bin/python3"

# Pastikan venv ada
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Python Virtual Environment tidak ditemukan. Menggunakan sistem python3."
    PYTHON_EXEC="python3"
else
    PYTHON_EXEC="$VENV_PYTHON"
fi

CRON_CMD="0 * * * * cd $PIPELINE_DIR && $PYTHON_EXEC $MAIN_SCRIPT >> $LOG_FILE 2>&1"

# Mengecek apakah sudah ada cron yang sama
if crontab -l 2>/dev/null | grep -q "$MAIN_SCRIPT"; then
    echo "Cronjob untuk $MAIN_SCRIPT sudah ada di sistem."
else
    # Tambahkan cronjob baru
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "Berhasil menambahkan cronjob:"
    echo "$CRON_CMD"
    echo "Pipeline akan berjalan setiap jam secara otomatis (100% full automation)."
fi
