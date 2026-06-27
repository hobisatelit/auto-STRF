# STRF Automation Pipeline

Pipeline ini mengotomasi alur SatNOGS → ekstraksi kurva Doppler → fitting TLE dengan `rffit` STRF.

## Instalasi

Dari root repository STRF:

```bash
bash pipeline/install.sh
```

Installer akan:

- membuat `pipeline/venv/`
- menginstal dependency Python
- mengecek/mengompilasi binary STRF `rffit`
- membuat direktori `pipeline/data/*` dan `pipeline/logs/`

Jalankan pipeline menggunakan Python dari virtual environment:

```bash
pipeline/venv/bin/python pipeline/main.py
```

## Mode otomatis penuh

Contoh menjalankan download, ekstraksi, fitting, dan penyimpanan hasil tanpa menu interaktif:

```bash
pipeline/venv/bin/python pipeline/main.py \
  --run-full \
  --norad-id 40931 \
  --n-observations 20 \
  --min-elevation 30 \
  --yes
```

Filter stasiun tertentu:

```bash
pipeline/venv/bin/python pipeline/main.py \
  --run-full \
  --norad-id 40931 \
  --station-id 1234 \
  --n-observations 10 \
  --yes
```

Filter ITERA bila nama stasiun ditemukan di SatNOGS:

```bash
pipeline/venv/bin/python pipeline/main.py --run-full --itera-only --yes
```

## Mode per tahap

```bash
# Cek status sistem
pipeline/venv/bin/python pipeline/main.py --status

# Download observasi saja
pipeline/venv/bin/python pipeline/main.py --download --norad-id 40931 --n-observations 20

# Ekstrak waterfall lokal yang belum diproses
pipeline/venv/bin/python pipeline/main.py --extract

# Fitting semua file .dat lokal dengan rffit batch/headless
pipeline/venv/bin/python pipeline/main.py --fit

# Buat laporan dari hasil terakhir
pipeline/venv/bin/python pipeline/main.py --analyze
```

## Output

File keluaran utama:

- `pipeline/data/waterfall/{obs_id}.png` — waterfall SatNOGS yang diunduh
- `pipeline/data/metadata/{obs_id}.json` — metadata observasi
- `pipeline/data/doppler_curves/{obs_id}.dat` — data Doppler format STRF
- `pipeline/data/doppler_curves/{obs_id}.meta.json` — metadata sidecar untuk `.dat`
- `pipeline/data/doppler_curves/{obs_id}_debug.png` — overlay debug ekstraksi kurva
- `pipeline/data/tle_output/initial_{NORAD}.tle` — TLE awal dari Celestrak
- `pipeline/data/tle_output/{obs_id}_fitted.tle` — TLE hasil fitting otomatis
- `pipeline/logs/last_results.json` — ringkasan hasil fitting terakhir
- `pipeline/logs/report_*.txt` — laporan analisis

## `rffit` batch/headless

Repository ini menambahkan mode batch ke `rffit`:

```bash
./rffit -B \
  -d pipeline/data/doppler_curves/OBS.dat \
  -c pipeline/data/tle_output/initial_40931.tle \
  -i 40931 \
  -s 9999 \
  -o pipeline/data/tle_output/OBS_fitted.tle \
  -a 256
```

Arti `-a`:

- `1` inclination
- `2` RAAN
- `3` eccentricity
- `4` argument of perigee
- `5` mean anomaly
- `6` mean motion
- `7` B* drag

Default pipeline: `256` (RAAN, mean anomaly, mean motion). Frekuensi carrier tetap di-fit otomatis oleh `rffit`.

Output batch mencetak metrik machine-readable:

```text
BATCH_OBSERVATIONS 12
BATCH_FIT_PARAMETERS 256
BATCH_FREQUENCY_MHZ 435.880123456
BATCH_RMSE_BEFORE_KHZ 1.234567
BATCH_RMSE_AFTER_KHZ 0.123456
BATCH_OUTPUT_TLE pipeline/data/tle_output/OBS_fitted.tle
```

## Validasi lokal

```bash
python3 -m compileall pipeline
python3 -m unittest discover -s pipeline/tests
make rffit
```

## Catatan kualitas data

Automasi ini tetap bergantung pada kualitas waterfall SatNOGS. Untuk data sangat noisy, multi-sinyal, atau metadata frekuensi tidak lengkap, periksa file debug overlay `{obs_id}_debug.png` dan nilai RMSE pada `last_results.json` sebelum memakai TLE hasil fitting sebagai hasil ilmiah final.
