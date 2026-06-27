#!/usr/bin/env python3
"""
Fully Automated STRF Pipeline for LAPAN-A2 TLE Optimization.
Script ini didesain untuk berjalan secara otomatis tanpa interaksi manual.
Cocok digunakan bersama cronjob atau systemd timer di stasiun bumi mana pun.

Pipeline Steps (sesuai Bab 3.4 Skripsi):
    1. Ambil observasi dari SatNOGS API (filter elevasi ≥ 30°)
    2. Download waterfall PNG + metadata JSON
    3. Ekstraksi kurva Doppler via OpenCV (Bab 3.4.2)
    4. Konversi piksel → frekuensi/waktu (Persamaan 2.6, 2.7)
    5. Fitting TLE via SGP4 + scipy.optimize (Persamaan 2.9, 2.10)
    6. Analisis dan laporan RMSE
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path

import config
from modules import (
    coordinate_converter,
    image_processor,
    rffit_runner,
    satnogs_api,
    analysis,
)

def load_processed_obs() -> set[str]:
    """Memuat daftar ID observasi yang sudah pernah diproses."""
    if not config.PROCESSED_OBS_PATH.exists():
        return set()
    try:
        data = json.loads(config.PROCESSED_OBS_PATH.read_text(encoding="utf-8"))
        return set(data)
    except Exception:
        return set()

def save_processed_obs(obs_set: set[str]) -> None:
    """Menyimpan daftar ID observasi yang sudah diproses."""
    config.PROCESSED_OBS_PATH.write_text(json.dumps(list(obs_set), indent=2), encoding="utf-8")

def setup_logging():
    config.ensure_directories()
    # Log ke file
    logging.basicConfig(
        filename=config.PIPELINE_LOG,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Log juga ke stdout agar terlihat di systemd/cron output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    console_handler.setFormatter(formatter)
    logging.getLogger().addHandler(console_handler)

def run_automated_pipeline():
    logger = logging.getLogger("STRF-Auto")
    logger.info("==================================================")
    logger.info("Memulai siklus automasi STRF Pipeline...")
    
    processed_obs = load_processed_obs()
    new_dat_files = []
    fit_results = []
    
    # 1. Fetch observasi dari SatNOGS API
    try:
        logger.info(f"Mengambil observasi terbaru untuk NORAD {config.NORAD_ID} dengan elevasi >= {config.MIN_ELEVATION_DEG}°...")
        observations = satnogs_api.get_observations(
            config.NORAD_ID,
            station_id=None,
            min_elevation=config.MIN_ELEVATION_DEG,
            limit=50,  # Proses 50 observasi terbaru tiap putaran
        )
    except Exception as e:
        logger.error(f"Gagal mengambil observasi: {e}")
        return

    if not observations:
        logger.info("Tidak ada data observasi yang memenuhi kriteria saat ini.")
        return

    logger.info(f"Ditemukan {len(observations)} observasi potensial.")
    
    for obs in observations:
        obs_id = str(obs.get("id") or obs.get("observation_id"))
        if obs_id in processed_obs:
            continue
            
        logger.info(f"Memproses observasi baru: {obs_id}")
        
        # 2. Download waterfall and metadata
        result = satnogs_api.download_waterfall(obs_id, config.DATA_DIR)
        if not result:
            logger.warning(f"Gagal mendownload data untuk observasi {obs_id}. Menandai sebagai processed.")
            processed_obs.add(obs_id)
            continue
            
        png_path = config.WATERFALL_DIR / f"{obs_id}.png"
        json_path = config.METADATA_DIR / f"{obs_id}.json"
        
        # 3. Extract Doppler Curve dengan OpenCV (Bab 3.4.2)
        logger.info(f"Mengekstrak kurva Doppler dari waterfall: {obs_id}")
        points = image_processor.process_waterfall(png_path, json_path, config.WATERFALL_MARKED_DIR, config)
        if not points:
            logger.warning(f"Kurva Doppler tidak valid/tidak ditemukan pada observasi {obs_id}.")
            logger.info("Menghapus data observasi yang tidak valid untuk menghemat penyimpanan.")
            if png_path.exists():
                png_path.unlink()
            if json_path.exists():
                json_path.unlink()
            processed_obs.add(obs_id)
            continue
            
        # 4. Konversi piksel ke frekuensi & waktu lalu simpan .dat (Persamaan 2.6, 2.7)
        try:
            metadata = coordinate_converter.parse_metadata(json_path)
            freq_time = coordinate_converter.pixels_to_freq_time(points, metadata)
            dat_path = coordinate_converter.save_doppler_file(
                freq_time,
                metadata["observation_id"],
                metadata["station_lat"],
                metadata["station_lon"],
                metadata["station_alt"],
                config.DOPPLER_DIR,
                station_id=metadata.get("station_id"),
                norad_id=config.NORAD_ID,
            )
            logger.info(f"Berhasil mengekstrak kurva Doppler: {dat_path.name}")
            new_dat_files.append(dat_path)
        except Exception as e:
            logger.error(f"Gagal mengonversi koordinat untuk {obs_id}: {e}")
            
        processed_obs.add(obs_id)
        
    save_processed_obs(processed_obs)
    
    # 5. Fit TLE menggunakan Python-native SGP4 fitter (Persamaan 2.9)
    if not new_dat_files:
        logger.info("Tidak ada data Doppler valid yang baru untuk di-fit.")
        return
        
    logger.info(f"Menyiapkan proses optimasi (fitting) TLE untuk {len(new_dat_files)} observasi baru...")
    tle_initial = config.TLE_OUTPUT_DIR / f"initial_{config.NORAD_ID}.tle"
    if not tle_initial.exists():
        logger.info("Mengambil TLE awal dari Celestrak sebagai referensi awal...")
        try:
            rffit_runner.fetch_initial_tle(config.NORAD_ID, tle_initial)
        except Exception as e:
            logger.error(f"Gagal mengambil TLE awal: {e}")
            return
            
    for dat_path in new_dat_files:
        obs_id = dat_path.stem
        output_tle = config.TLE_OUTPUT_DIR / f"{obs_id}_fitted.tle"
        
        logger.info(f"Menjalankan SGP4 fitter pada: {dat_path.name}")
        try:
            result = rffit_runner.run_rffit(
                [dat_path],
                tle_initial,
                output_tle,
                norad_id=config.NORAD_ID,
            )
            
            if result.get("converged"):
                rmse_before = result.get("rmse_before", "?")
                rmse_after = result.get("rmse_after", "?")
                logger.info(
                    f"Fitting berhasil! RMSE: {rmse_before} → {rmse_after} kHz. "
                    f"TLE tersimpan di {output_tle.name}"
                )
            else:
                rmse_before = result.get("rmse_before", "?")
                rmse_after = result.get("rmse_after", "?")
                logger.warning(
                    f"Fitting tidak memperbaiki RMSE untuk {obs_id}. "
                    f"RMSE: {rmse_before} → {rmse_after} kHz."
                )
            fit_results.append(result)
        except Exception as e:
            logger.error(f"Terjadi kesalahan saat fitting {obs_id}: {e}")
    
    # 6. Generate analysis report (Bab 3.5)
    if fit_results:
        _generate_summary(logger, fit_results)
    
    logger.info("Siklus automasi STRF Pipeline selesai.")
    logger.info("==================================================")


def _generate_summary(logger, fit_results: list[dict]):
    """Generate ringkasan hasil fitting."""
    report_path = config.DATA_DIR / "pipeline_report.txt"
    
    converged = [r for r in fit_results if r.get("converged")]
    failed = [r for r in fit_results if not r.get("converged")]
    
    rmse_before_vals = [r["rmse_before"] for r in fit_results if r.get("rmse_before") is not None]
    rmse_after_vals = [r["rmse_after"] for r in fit_results if r.get("rmse_after") is not None]
    
    avg_before = sum(rmse_before_vals) / len(rmse_before_vals) if rmse_before_vals else None
    avg_after = sum(rmse_after_vals) / len(rmse_after_vals) if rmse_after_vals else None
    
    summary_lines = [
        "=" * 60,
        "STRF Automation Pipeline — Ringkasan Hasil",
        f"Waktu: {datetime.now(timezone.utc).isoformat(timespec='seconds')} UTC",
        "=" * 60,
        f"Total observasi diproses  : {len(fit_results)}",
        f"Berhasil (RMSE turun)     : {len(converged)}",
        f"Tidak berhasil            : {len(failed)}",
        "",
    ]
    
    if avg_before is not None and avg_after is not None:
        improvement = ((avg_before - avg_after) / avg_before * 100) if avg_before > 0 else 0
        summary_lines.extend([
            f"RMSE rata-rata sebelum    : {avg_before:.3f} kHz",
            f"RMSE rata-rata sesudah    : {avg_after:.3f} kHz",
            f"Penurunan RMSE rata-rata  : {improvement:.1f}%",
        ])
    
    summary_lines.append("")
    summary_lines.append("Detail per observasi:")
    summary_lines.append("-" * 60)
    for r in fit_results:
        status = "✅" if r.get("converged") else "❌"
        obs_path = r.get("output_tle_path", "?")
        obs_name = Path(obs_path).stem if obs_path else "?"
        summary_lines.append(
            f"  {status} {obs_name}: "
            f"RMSE {r.get('rmse_before', '?')} → {r.get('rmse_after', '?')} kHz "
            f"({r.get('n_points', '?')} titik)"
        )
    
    report_text = "\n".join(summary_lines) + "\n"
    
    # Tulis ke file dan juga ke log
    report_path.write_text(report_text, encoding="utf-8")
    for line in summary_lines:
        logger.info(line)
    
    logger.info(f"Laporan tersimpan di: {report_path}")

    # Also generate the structured analysis report
    try:
        analysis.generate_report(
            fit_results,
            config.DATA_DIR / "analysis_report.txt",
        )
    except Exception as e:
        logger.warning(f"Gagal membuat laporan analisis terstruktur: {e}")


def clean_data(logger):
    """Menghapus semua data dari folder observasi."""
    logger.info("Mereset data. Menghapus waterfall, metadata, dan doppler_curves...")
    for path in [config.WATERFALL_DIR, config.WATERFALL_MARKED_DIR, config.METADATA_DIR, config.DOPPLER_DIR]:
        for file in path.glob("*"):
            if file.is_file():
                file.unlink()
    
    # Hapus tracker observasi
    if config.PROCESSED_OBS_PATH.exists():
        config.PROCESSED_OBS_PATH.unlink()
    logger.info("Penyimpanan berhasil dibersihkan.")

def parse_args():
    parser = argparse.ArgumentParser(
        description="STRF Automation Pipeline — LAPAN-A2 TLE Optimizer",
        epilog="""
Contoh Penggunaan:
  python3 main.py                  (Menjalankan pipeline secara default)
  python3 main.py --run-full       (Sama seperti default, menjalankan seluruh proses)
  python3 main.py --clean-data     (Menghapus seluruh file data untuk menghemat ruang atau reset)
        """,
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "--run-full", 
        action="store_true",
        help="Jalankan siklus pipeline penuh secara otomatis (Fetch -> Extract -> Fit -> Report)"
    )
    
    parser.add_argument(
        "--clean-data", 
        action="store_true",
        help="Hapus semua data waterfall, metadata, dan kurva doppler yang tersimpan (Hard Reset)"
    )
    
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging()
    
    logger = logging.getLogger("STRF-Auto")
    
    try:
        if args.clean_data:
            clean_data(logger)
        else:
            # Jika tidak ada argumen spesifik, atau menggunakan --run-full, jalankan mode default
            run_automated_pipeline()
    except Exception as exc:
        logger.exception("Kesalahan fatal saat mengeksekusi pipeline")
