"""Ekstraksi kurva Doppler dari citra waterfall SatNOGS.

Waterfall PNG dari SatNOGS adalah plot matplotlib lengkap yang mengandung
label sumbu, tick marks, colorbar, dan margin. Modul ini mendeteksi batas
area plot secara otomatis lalu mengekstrak sinyal Doppler dari area data
yang sebenarnya.

Metodologi sesuai Bab 3.4.2 Draft Tugas Akhir:
    1. Grayscale (cv2.cvtColor BGR2GRAY)
    2. Gaussian blur (cv2.GaussianBlur)
    3. Otsu's threshold (Persamaan 2.3)
    4. Intensity centroid per baris (Persamaan 2.4)
    5. N_min filtering (Persamaan 2.5)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

LOG = logging.getLogger(__name__)


def _load_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV belum terinstal. Jalankan pipeline/install.sh terlebih dahulu."
        ) from exc


def _detect_plot_bounds(gray: np.ndarray) -> tuple[int, int, int, int]:
    """Deteksi batas area plot di dalam gambar matplotlib.

    Matplotlib menggambar frame hitam (nilai ~0) di sekeliling area plot.
    Kita scan dari masing-masing sisi sepanjang garis tengah untuk menemukan
    piksel hitam pertama (= frame border), lalu area plot adalah 1 piksel
    di dalamnya.

    Returns:
        (x_left, x_right, y_top, y_bottom) — koordinat piksel inklusif
        dari area data di dalam frame plot.
    """
    h, w = gray.shape
    black_threshold = 10  # matplotlib frame line memiliki nilai ~0

    mid_row = gray[h // 2, :]  # baris tengah gambar
    mid_col = gray[:, w // 4]  # kolom di ~25% lebar (pasti di dalam plot)

    # Scan dari kiri: cari piksel hitam pertama
    x_left = 0
    for i in range(w // 2):
        if mid_row[i] <= black_threshold:
            x_left = i + 1  # 1 piksel di dalam frame
            break

    # Scan dari tengah ke kanan: cari piksel hitam pertama (= batas kanan plot)
    # Ini menemukan tepi kanan frame plot, BUKAN colorbar
    x_right = w - 1
    for i in range(w // 2, w):
        if mid_row[i] <= black_threshold:
            x_right = i - 1
            break

    # Scan dari atas: cari piksel hitam pertama
    y_top = 0
    for i in range(h // 2):
        if mid_col[i] <= black_threshold:
            y_top = i + 1
            break

    # Scan dari bawah
    y_bottom = h - 1
    for i in range(h - 1, h // 2, -1):
        if mid_col[i] <= black_threshold:
            y_bottom = i - 1
            break

    # Sanity check: plot area harus minimal 30% dari gambar
    plot_w = x_right - x_left
    plot_h = y_bottom - y_top
    if plot_w < w * 0.3 or plot_h < h * 0.3:
        # Fallback ke persentase default untuk SatNOGS waterfall
        LOG.warning("Deteksi batas plot gagal, gunakan fallback persentase")
        x_left = int(w * 0.09)
        x_right = int(w * 0.81)
        y_top = int(h * 0.01)
        y_bottom = int(h * 0.97)

    LOG.debug("Plot bounds: x=[%d, %d], y=[%d, %d]", x_left, x_right, y_top, y_bottom)
    return x_left, x_right, y_top, y_bottom


def process_waterfall(png_path, json_path, output_dir, config):
    """Proses waterfall PNG dan return list koordinat dalam fraksi area plot.

    Tahapan sesuai Bab 3.4.2 skripsi:
        1. Grayscale conversion
        2. Gaussian blur
        3. Otsu's thresholding (Persamaan 2.3)
        4. Intensity centroid extraction (Persamaan 2.4)
        5. N_min pixel filtering (Persamaan 2.5)

    Returns:
        List of (frac_y, frac_x) di mana frac_y dan frac_x adalah posisi
        relatif (0.0 - 1.0) di dalam area plot, atau None jika gagal.
        frac_y=0.0 = baris teratas plot, frac_y=1.0 = baris terbawah.
        frac_x=0.0 = kolom paling kiri plot, frac_x=1.0 = kolom paling kanan.
    """
    cv2 = _load_cv2()

    png_path = Path(png_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        img_bgr = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise RuntimeError(f"Citra tidak dapat dibaca: {png_path}")

        # ── Langkah 1: Grayscale (Bab 3.4.2 paragraf 5) ──
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # ── Deteksi batas area plot (crop matplotlib frame) ──
        x_left, x_right, y_top, y_bottom = _detect_plot_bounds(gray)
        plot_w = x_right - x_left
        plot_h = y_bottom - y_top

        if plot_w <= 0 or plot_h <= 0:
            LOG.error("Area plot tidak valid: w=%d h=%d", plot_w, plot_h)
            return None

        # Crop area plot saja untuk pemrosesan
        plot_region = gray[y_top:y_bottom + 1, x_left:x_right + 1]

        # ── Langkah 2: Gaussian blur (Bab 3.4.2 paragraf 6) ──
        blurred = cv2.GaussianBlur(plot_region, config.GAUSSIAN_KERNEL_SIZE, 0)

        # ── Langkah 3: Otsu's thresholding (Persamaan 2.2 & 2.3) ──
        # Menggunakan metode Otsu untuk menentukan threshold secara adaptif
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        LOG.info(
            "Plot area terdeteksi: x=[%d,%d] y=[%d,%d], ukuran plot: %dx%d",
            x_left, x_right, y_top, y_bottom, plot_w, plot_h,
        )

        doppler_points = []

        # ── Langkah 4 & 5: Intensity centroid + N_min filter ──
        # (Persamaan 2.4 dan Persamaan 2.5)
        n_min = getattr(config, "N_MIN_PIXELS", 5)

        for row_idx in range(thresh.shape[0]):
            row_binary = thresh[row_idx, :]

            # Persamaan 2.5: S(y) = sum(B(x,y)) >= N_min * 255
            n_signal_pixels = np.count_nonzero(row_binary)
            if n_signal_pixels < n_min:
                continue  # SNR terlalu rendah, lewati baris ini

            # Persamaan 2.4: Intensity centroid (pusat massa intensitas)
            row_float = row_binary.astype(float)
            total_intensity = np.sum(row_float)
            if total_intensity == 0:
                continue

            x_indices = np.arange(len(row_float))
            centroid_x = np.sum(x_indices * row_float) / total_intensity

            # Konversi ke fraksi terhadap plot area
            frac_x = float(centroid_x) / float(plot_w)
            frac_y = float(row_idx) / float(plot_h)

            # Clamp ke [0, 1]
            frac_x = max(0.0, min(1.0, frac_x))
            frac_y = max(0.0, min(1.0, frac_y))

            doppler_points.append((frac_y, frac_x))

        obs_id = Path(png_path).stem
        img_debug = img_bgr.copy()

        # Evaluasi: minimal 20 titik untuk kurva valid
        min_points = 20
        if len(doppler_points) >= min_points:
            # Terapkan Savitzky-Golay filter jika titik cukup banyak
            try:
                from scipy.signal import savgol_filter
                if len(doppler_points) > 51:
                    xs = [p[1] for p in doppler_points]
                    # Haluskan sumbu X (frekuensi)
                    xs_smooth = savgol_filter(xs, window_length=51, polyorder=3)
                    # Update titik doppler
                    doppler_points = [
                        (doppler_points[i][0], max(0.0, min(1.0, xs_smooth[i])))
                        for i in range(len(doppler_points))
                    ]
            except ImportError:
                LOG.warning("scipy tidak terinstal, melewati tahap Savitzky-Golay filter.")

            # Validasi Bentuk Kurva
            arr_x = np.array([p[1] for p in doppler_points])
            arr_y = np.array([p[0] for p in doppler_points])

            # 1. Uji Ayunan Frekuensi (Swing)
            freq_swing = np.max(arr_x) - np.min(arr_x)
            if freq_swing < 0.005:
                LOG.warning(
                    "Kurva %s ditolak: Frekuensi swing terlalu kecil (%.3f). Kemungkinan noise terestrial.",
                    png_path.name, freq_swing
                )
                return []

            # 2. Uji Korelasi Linear (Trend)
            # Kurva Doppler yang bersih pasti memiliki korelasi linear yang kuat (entah positif atau negatif, tergantung orientasi Y).
            correlation = np.corrcoef(arr_y, arr_x)[0, 1]
            if abs(correlation) < 0.3:
                LOG.warning(
                    "Kurva %s ditolak: Korelasi linear sangat lemah (%.3f). Kemungkinan noise acak.",
                    png_path.name, correlation
                )
                return []

            # Gambar titik deteksi pada debug image
            for frac_y, frac_x in doppler_points:
                px_x = int(x_left + frac_x * plot_w)
                px_y = int(y_top + frac_y * plot_h)
                cv2.circle(img_debug, (px_x, px_y), 2, (0, 255, 0), -1)

            # Gambar batas plot area (kotak hijau)
            cv2.rectangle(img_debug, (x_left, y_top), (x_right, y_bottom), (0, 255, 0), 1)

            debug_path = output_dir / f"{obs_id}_debug.png"
            cv2.imwrite(str(debug_path), img_debug)
            LOG.info(
                "Berhasil! %d titik terdeteksi. Debug overlay: %s",
                len(doppler_points), debug_path,
            )

            return doppler_points
        else:
            LOG.warning(
                "Kurva %s tidak valid: Titik terlalu sedikit (%d) dari minimum %d.",
                png_path.name, len(doppler_points), min_points,
            )

            # Simpan debug image meskipun gagal
            for frac_y, frac_x in doppler_points:
                px_x = int(x_left + frac_x * plot_w)
                px_y = int(y_top + frac_y * plot_h)
                cv2.circle(img_debug, (px_x, px_y), 2, (0, 0, 255), -1)
            cv2.rectangle(img_debug, (x_left, y_top), (x_right, y_bottom), (0, 255, 0), 1)
            debug_path = output_dir / f"{obs_id}_debug.png"
            cv2.imwrite(str(debug_path), img_debug)

            return None

    except Exception as exc:  # noqa: BLE001
        LOG.error("Gagal memproses waterfall %s: %s", png_path, exc)
        return None
