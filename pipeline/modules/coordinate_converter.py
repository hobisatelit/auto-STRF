"""Konversi koordinat piksel waterfall ke data Doppler STRF."""

from __future__ import annotations

import json
import logging
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import config

LOG = logging.getLogger(__name__)


def _parse_time(value) -> datetime:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    if value is None:
        raise ValueError("Metadata tidak memiliki waktu observasi")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(text)
            else:
                dt = datetime.strptime(text, fmt)
            return (
                dt.replace(tzinfo=timezone.utc)
                if dt.tzinfo is None
                else dt.astimezone(timezone.utc)
            )
        except ValueError:
            continue
    raise ValueError(f"Format waktu tidak didukung: {value}")


def _datetime_to_mjd(dt: datetime) -> float:
    try:
        from astropy.time import Time  # type: ignore

        return cast(float, Time(dt).mjd)
    except Exception:
        epoch = datetime(1858, 11, 17, tzinfo=timezone.utc)
        return (dt.astimezone(timezone.utc) - epoch).total_seconds() / 86400.0


def _png_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with path.open("rb") as file_obj:
            header = file_obj.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return None, None
        width, height = struct.unpack(">II", header[16:24])
        return int(width), int(height)
    except OSError:
        return None, None


def _first_present(data: dict, keys: tuple[str, ...]):
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _frequency_range(data: dict) -> tuple[float, float]:
    explicit_min = _first_present(
        data, ("f_min", "frequency_min", "waterfall_frequency_min")
    )
    explicit_max = _first_present(
        data, ("f_max", "frequency_max", "waterfall_frequency_max")
    )
    if explicit_min is not None and explicit_max is not None:
        return float(explicit_min), float(explicit_max)

    low = _first_present(data, ("transmitter_downlink_low", "downlink_low"))
    high = _first_present(data, ("transmitter_downlink_high", "downlink_high"))
    center = _first_present(
        data,
        (
            "transmitter_downlink_frequency",
            "transmitter_downlink_center",
            "frequency",
            "center_frequency",
        ),
    )
    bandwidth = _first_present(
        data, ("transmitter_downlink_bandwidth", "bandwidth", "waterfall_bandwidth")
    )

    if low is not None and high is not None and float(high) > float(low):
        return float(low), float(high)
    if center is None and low is not None:
        center = low
    if center is None:
        center = config.BEACON_FREQ_HZ
    bw = (
        float(bandwidth)
        if bandwidth is not None and float(bandwidth) > 0
        else float(config.WATERFALL_BANDWIDTH_HZ)
    )
    center_f = float(center)
    return center_f - bw / 2.0, center_f + bw / 2.0


def _image_dimensions(data: dict, json_path: Path) -> tuple[int, int]:
    width = _first_present(
        data, ("img_width", "image_width", "width", "_local_image_width")
    )
    height = _first_present(
        data, ("img_height", "image_height", "height", "_local_image_height")
    )
    if width and height:
        return int(width), int(height)

    png_path = data.get("_local_waterfall_path")
    candidates = []
    if png_path:
        candidates.append(Path(png_path))
    candidates.append(json_path.parent.parent / "waterfall" / f"{json_path.stem}.png")
    candidates.append(json_path.with_suffix(".png"))

    for candidate in candidates:
        width, height = _png_dimensions(candidate)
        if width and height:
            return width, height
    raise ValueError(
        "Dimensi citra tidak ditemukan di metadata dan PNG pasangan tidak tersedia"
    )


def parse_metadata(json_path):
    """Baca metadata SatNOGS dan ekstrak waktu, frekuensi, durasi, dan dimensi."""
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)

    start_value = _first_present(data, ("start", "time_start", "start_time", "t_start"))
    end_value = _first_present(data, ("end", "time_end", "end_time", "t_end"))
    t_start = _parse_time(start_value)
    if end_value is not None:
        t_end = _parse_time(end_value)
        delta_t = (t_end - t_start).total_seconds()
    else:
        duration = _first_present(data, ("duration", "duration_seconds", "delta_t"))
        if duration is None:
            raise ValueError("Metadata tidak memiliki waktu selesai atau durasi")
        delta_t = float(duration)
    if delta_t <= 0:
        raise ValueError("Durasi observasi tidak valid")

    f_min, f_max = _frequency_range(data)
    img_width, img_height = _image_dimensions(data, json_path)

    return {
        "observation_id": data.get("id")
        or data.get("observation_id")
        or json_path.stem,
        "raw": data,
        "t_start": t_start,
        "f_min": f_min,
        "f_max": f_max,
        "delta_t": delta_t,
        "img_width": img_width,
        "img_height": img_height,
        "station_id": data.get("ground_station")
        or data.get("station_id")
        or data.get("ground_station_id"),
        "station_lat": data.get("station_lat", config.ITERA_LAT),
        "station_lon": data.get(
            "station_lng", data.get("station_lon", config.ITERA_LON)
        ),
        "station_alt": data.get("station_alt", config.ITERA_ALT),
    }


def pixels_to_freq_time(pixel_points, metadata):
    """Konversi `(frac_y, frac_x)` menjadi `(frequency_hz, timestamp_utc)`.

    Input berupa fraksi area plot (0.0 - 1.0) yang dikembalikan oleh
    image_processor.process_waterfall(). frac_y=0.0 adalah baris teratas
    plot (waktu paling awal), frac_x=0.0 adalah kolom paling kiri (frekuensi
    terendah).
    """
    f_min = float(metadata["f_min"])
    f_max = float(metadata["f_max"])
    t_start = metadata["t_start"]
    delta_t = float(metadata["delta_t"])

    converted = []
    for frac_y, frac_x in sorted(pixel_points, key=lambda item: item[0]):
        fy = float(frac_y)
        fx = float(frac_x)

        if config.INVERT_WATERFALL_TIME_AXIS:
            fy = 1.0 - fy

        frequency_hz = f_min + fx * (f_max - f_min)
        timestamp_utc = t_start + timedelta(seconds=fy * delta_t)
        converted.append((float(frequency_hz), timestamp_utc))
    return converted


def _strf_site_id(station_id=None) -> int:
    if station_id is None or station_id == "":
        return int(config.DEFAULT_STRF_SITE_ID)
    try:
        satnogs_id = int(station_id)
    except (TypeError, ValueError):
        return int(config.DEFAULT_STRF_SITE_ID)
    if 0 < satnogs_id < 1000:
        return int(config.SATNOGS_STRF_SITE_PREFIX + satnogs_id)
    return satnogs_id


def _ensure_site_file(
    site_id: int, station_lat, station_lon, station_alt, output_dir: Path
) -> Path:
    site_file = (
        output_dir.parent / "sites.txt"
        if output_dir.name == "doppler_curves"
        else config.SITES_TXT
    )
    site_file.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        site_file.read_text(encoding="utf-8")
        if site_file.exists()
        else "# No ID   Latitude Longitude   Elev   Observer\n"
    )
    prefix = f"{site_id:04d} "
    if any(line.startswith(prefix) for line in existing.splitlines()):
        return site_file
    with site_file.open("a", encoding="utf-8") as file_obj:
        file_obj.write(
            f"{site_id:04d} SN   {float(station_lat):8.4f} {float(station_lon):9.4f} {float(station_alt):6.0f}   SatNOGS/ITERA Pipeline\n"
        )
    return site_file


def save_doppler_file(
    freq_time_points,
    observation_id,
    station_lat,
    station_lon,
    station_alt,
    output_dir,
    station_id=None,
    norad_id=None,
):
    """Simpan kurva Doppler dalam format `.dat` yang dibaca `rffit`.

    `rffit.c` tidak melewati baris komentar saat membaca file, sehingga header
    skripsi disimpan sebagai sidecar `{obs_id}.meta.json`, bukan di `.dat`.
    Format `.dat`: `MJD  frekuensi_Hz  flux  site_id`.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    site_id = _strf_site_id(station_id)
    _ensure_site_file(site_id, station_lat, station_lon, station_alt, output_dir)

    dat_path = output_dir / f"{observation_id}.dat"
    with dat_path.open("w", encoding="utf-8") as file_obj:
        for frequency_hz, timestamp_utc in sorted(
            freq_time_points, key=lambda item: item[1]
        ):
            mjd = _datetime_to_mjd(timestamp_utc)
            file_obj.write(
                f"{mjd:.6f}\t{float(frequency_hz):14.3f}\t{1.0:8.3f}\t{site_id:04d}\n"
            )

    meta_path = output_dir / f"{observation_id}.meta.json"
    with meta_path.open("w", encoding="utf-8") as file_obj:
        json.dump(
            {
                "norad_id": norad_id or config.NORAD_ID,
                "station": {
                    "site_id": site_id,
                    "lat": station_lat,
                    "lon": station_lon,
                    "alt": station_alt,
                },
                "observation_id": observation_id,
                "n_points": len(freq_time_points),
                "format": "MJD frequency_hz flux site_id",
            },
            file_obj,
            indent=2,
            ensure_ascii=False,
        )

    LOG.info("File Doppler STRF disimpan ke %s", dat_path)
    return dat_path
