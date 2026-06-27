# Cara Pakai Pipeline Automasi STRF — LAPAN-A2

Pipeline ini mengotomasi seluruh proses pembaruan TLE (Two-Line Element) satelit
LAPAN-A2 menggunakan data Doppler dari jaringan stasiun bumi SatNOGS.

---

## Daftar Isi

1. [Persyaratan Sistem](#1-persyaratan-sistem)
2. [Instalasi](#2-instalasi)
3. [Menjalankan Pipeline](#3-menjalankan-pipeline)
4. [Menjadwalkan Otomatis (Cron)](#4-menjadwalkan-otomatis-cron)
5. [Memahami Output](#5-memahami-output)
6. [Konfigurasi Lanjutan](#6-konfigurasi-lanjutan)
7. [Troubleshooting](#7-troubleshooting)
8. [Alur Kerja Pipeline](#8-alur-kerja-pipeline)

---

## 1. Persyaratan Sistem

| Komponen | Versi Minimum |
|----------|---------------|
| OS | Linux (Ubuntu 20.04+, Arch, atau macOS) |
| Python | 3.10+ |
| RAM | 2 GB |
| Disk | 500 MB (untuk data waterfall) |
| Internet | Diperlukan (download dari SatNOGS API) |

**Tidak diperlukan:** PGPLOT, X11 display, atau GUI — pipeline berjalan sepenuhnya
headless.

---

## 2. Instalasi

### Cara Cepat (Satu Perintah)

```bash
cd pipeline
bash install.sh
```

Script ini akan:
- Menginstal dependensi sistem (gcc, python3-venv, dll.)
- Membuat Python virtual environment di `pipeline/venv/`
- Menginstal semua paket Python (OpenCV, NumPy, SciPy, sgp4, dll.)
- Membuat direktori data yang diperlukan

### Instalasi Manual (Jika install.sh Gagal)

```bash
# 1. Buat virtual environment
cd pipeline
python3 -m venv venv

# 2. Aktifkan
source venv/bin/activate

# 3. Install paket
pip install -r requirements.txt
```

### Verifikasi Instalasi

```bash
venv/bin/python3 -c "
import cv2, numpy, scipy, sgp4, requests, astropy
print('Semua dependensi terinstal dengan benar!')
"
```

---

## 3. Menjalankan Pipeline

### Menjalankan Sekali (Manual)

```bash
cd pipeline
venv/bin/python3 main.py
```

Pipeline akan:
1. Mengambil 50 observasi terbaru LAPAN-A2 dari SatNOGS
2. Mendownload waterfall PNG dan metadata JSON
3. Mengekstrak kurva Doppler dengan OpenCV
4. Mengonversi piksel ke frekuensi/waktu
5. Melakukan fitting TLE dengan SGP4 optimizer
6. Menyimpan TLE terkoreksi dan laporan RMSE

### Contoh Output yang Diharapkan

```
2026-06-27 01:51:20 INFO: Memulai siklus automasi STRF Pipeline...
2026-06-27 01:51:23 INFO: Ditemukan 19 observasi potensial.
2026-06-27 01:51:29 INFO: Mengekstrak kurva Doppler dari waterfall: 14385058
2026-06-27 01:51:29 INFO: Plot area terdeteksi: x=[76,675] y=[9,1554]
2026-06-27 01:51:30 INFO: Berhasil! 1546 titik terdeteksi.
2026-06-27 01:54:09 INFO: Fitting 2 parameter(s): ['ma', 'mm']
2026-06-27 01:55:13 INFO: ✅ Fitting berhasil! RMSE: 0.201 → 0.043 kHz
2026-06-27 01:55:13 INFO: Penurunan RMSE rata-rata: 78.7%
```

---

## 4. Menjadwalkan Otomatis (Cron)

Agar pipeline berjalan otomatis setiap jam:

```bash
cd pipeline
bash cron_setup.sh
```

Atau tambahkan secara manual ke crontab:

```bash
crontab -e
# Tambahkan baris berikut (ganti path sesuai lokasi Anda):
0 * * * * cd /path/to/pipeline && venv/bin/python3 main.py >> logs/cron.log 2>&1
```

### Mengecek Apakah Cron Berjalan

```bash
# Lihat crontab aktif
crontab -l

# Lihat log pipeline
tail -f pipeline/logs/pipeline.log

# Lihat log cron
tail -f pipeline/logs/cron.log
```

### Menghentikan Cron

```bash
crontab -l | grep -v "main.py" | crontab -
```

---

## 5. Memahami Output

### Struktur Direktori Output

```
pipeline/data/
├── waterfall/              # Citra waterfall PNG dari SatNOGS
│   ├── 14385058.png
│   └── ...
├── metadata/               # Metadata JSON observasi
│   ├── 14385058.json
│   └── ...
├── doppler_curves/         # Kurva Doppler yang diekstrak
│   ├── 14385058.dat        # Data MJD + frekuensi untuk fitting
│   ├── 14385058_debug.png  # Overlay visual kurva Doppler
│   ├── 14385058.meta.json  # Metadata stasiun & observasi
│   └── sites.txt           # Daftar stasiun bumi
├── tle_output/             # Hasil fitting TLE
│   ├── initial_40931.tle   # TLE awal (dari Celestrak)
│   ├── 14385058_fitted.tle # TLE terkoreksi hasil fitting
│   └── ...
├── pipeline_report.txt     # Ringkasan hasil per-run
└── analysis_report.txt     # Laporan analisis RMSE
```

### Format File .dat (Kurva Doppler)

```
# MJD            Frekuensi(Hz)    Flux   SiteID
61217.781366     401199895.890    1.000  7158
61217.781368     401199886.951    1.000  7158
```

### Format File TLE

```
LAPAN-A2
1 40931U 00000    26168.09809028  .00000000  00000-0 -12415-2 0    05
2 40931   5.9979 170.2307 0012596   0.3925 270.8382 10.40371810 33696
```

### Debug Overlay Image

File `*_debug.png` menampilkan overlay titik-titik hijau di atas waterfall asli.
Titik hijau menunjukkan posisi kurva Doppler yang berhasil diekstrak.
Gunakan file ini untuk memverifikasi secara visual apakah ekstraksi benar.

---

## 6. Konfigurasi Lanjutan

Semua konfigurasi ada di file `pipeline/config.py`.

### Parameter Satelit

```python
NORAD_ID = 40931              # NORAD ID LAPAN-A2
BEACON_FREQ_HZ = 435_880_000  # Frekuensi beacon (Hz)
MIN_ELEVATION_DEG = 30         # Elevasi minimum (derajat)
```

### Parameter OpenCV (Ekstraksi Kurva)

```python
GAUSSIAN_KERNEL_SIZE = (5, 5)  # Ukuran kernel Gaussian blur
N_MIN_PIXELS = 5               # Minimum piksel sinyal per baris
```

### Parameter Fitting TLE

```python
# Parameter orbital mana yang dioptimasi:
# [incl, raan, ecc, argp, mean_anomaly, mean_motion, bstar]
SGP4_FIT_PARAMS = [False, False, False, False, True, True, False]

FIT_MAX_ITERATIONS = 2000  # Maks iterasi optimizer
FIT_TOLERANCE = 1e-10      # Toleransi konvergensi
```

#### Memilih Parameter Fitting

| Parameter | Kapan Diaktifkan |
|-----------|------------------|
| Mean Anomaly (ma) | **Selalu** — posisi satelit di orbit |
| Mean Motion (mm) | **Selalu** — kecepatan orbit |
| Inclination (incl) | Jika data dari banyak stasiun di lintang berbeda |
| RAAN (raan) | Jika data mencakup beberapa orbit/hari |
| Eccentricity (ecc) | Untuk orbit sangat elips saja |
| Arg. Perigee (argp) | Jarang — hanya untuk orbit elips |
| B* drag (bstar) | Jika data mencakup beberapa minggu |

### Token SatNOGS API (Opsional)

```python
SATNOGS_API_TOKEN = ""  # Kosong = akses publik (cukup untuk kebanyakan kasus)
```

Jika terlalu banyak request gagal (rate limited), daftarkan akun di
[network.satnogs.org](https://network.satnogs.org) dan isi token di sini.

### Koordinat Stasiun ITERA

```python
ITERA_LAT = -5.121   # Lintang (derajat)
ITERA_LON = 105.309  # Bujur (derajat)
ITERA_ALT = 96       # Ketinggian (meter)
```

---

## 7. Troubleshooting

### "Tidak ada data observasi yang memenuhi kriteria"

- SatNOGS mungkin sedang tidak ada observasi baru untuk LAPAN-A2
- Coba turunkan `MIN_ELEVATION_DEG` dari 30 ke 20 di `config.py`
- Pipeline akan otomatis mencoba lagi di putaran berikutnya

### "Kurva Doppler tidak valid" / "Frekuensi swing terlalu kecil"

- Sinyal satelit terlalu lemah atau tidak ada transmisi aktif
- Ini normal — LAPAN-A2 bertransmisi secara intermiten
- Pipeline hanya memproses observasi dengan sinyal Doppler yang jelas

### "Fitting tidak memperbaiki RMSE"

- Data Doppler mungkin terlalu noisy atau terlalu sedikit titik
- Coba aktifkan lebih banyak parameter fitting di `SGP4_FIT_PARAMS`
- Cek debug overlay (`*_debug.png`) untuk verifikasi visual

### "Gagal mengambil TLE awal"

- Periksa koneksi internet
- Celestrak atau AMSAT-ID mungkin sedang down
- TLE awal hanya perlu diambil sekali, setelah itu disimpan lokal

### Melihat Log Lengkap

```bash
# Log pipeline
cat pipeline/logs/pipeline.log

# Observasi yang sudah diproses (tidak akan diproses ulang)
cat pipeline/logs/processed_obs.json

# Reset agar semua observasi diproses ulang
echo "[]" > pipeline/logs/processed_obs.json
```

---

## 8. Alur Kerja Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                    main.py (Pipeline)                    │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  1. satnogs_api.py         │
        │  Ambil observasi LAPAN-A2  │
        │  dari SatNOGS Network API  │
        │  (filter: elevasi ≥ 30°)   │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  2. satnogs_api.py         │
        │  Download waterfall PNG    │
        │  + metadata JSON           │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  3. image_processor.py     │
        │  Ekstraksi kurva Doppler:  │
        │  Grayscale → Gaussian →    │
        │  Otsu threshold → Centroid │
        │  → Validasi bentuk kurva   │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  4. coordinate_converter.py│
        │  Piksel → Frekuensi (Hz)   │
        │  Piksel → Waktu (MJD UTC)  │
        │  Simpan file .dat          │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  5. sgp4_fitter.py         │
        │  Optimasi TLE:             │
        │  SGP4 propagation →        │
        │  Hitung Doppler prediksi → │
        │  Minimasi χ² (Nelder-Mead) │
        │  → Simpan TLE terkoreksi   │
        └─────────────┬──────────────┘
                      │
        ┌─────────────▼──────────────┐
        │  6. Laporan                │
        │  RMSE sebelum vs sesudah   │
        │  Pipeline report           │
        └────────────────────────────┘
```

Setiap observasi yang sudah diproses dicatat di `logs/processed_obs.json`
sehingga tidak akan diproses ulang pada putaran berikutnya.

---

## Catatan Penting

- Pipeline ini **tidak memerlukan PGPLOT atau X11** — sepenuhnya headless
- Fitting dilakukan dengan Python-native SGP4 (bukan binary `rffit`)
- Hasil TLE dapat divalidasi secara manual dengan membuka `rffit` interaktif
  jika diperlukan:
  ```bash
  cd .. && ./rffit -d pipeline/data/doppler_curves/OBS_ID.dat \
                   -c pipeline/data/tle_output/OBS_ID_fitted.tle \
                   -i 40931
  ```
