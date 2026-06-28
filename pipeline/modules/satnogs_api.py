"""Pengambilan data observasi dan waterfall dari SatNOGS."""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from urllib.parse import urljoin

import config
import requests
from tqdm import tqdm  # type: ignore[import-untyped]

LOG = logging.getLogger(__name__)


def _headers() -> dict:
    headers = {"Accept": "application/json"}
    if config.SATNOGS_API_TOKEN:
        headers["Authorization"] = f"Token {config.SATNOGS_API_TOKEN}"
    return headers


def _normalize_results(payload):
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    return []


def _get_json(url: str, params: dict | None = None):
    response = requests.get(
        url,
        params=params,
        headers=_headers(),
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _observation_id(observation: dict):
    return (
        observation.get("id")
        or observation.get("observation_id")
        or observation.get("network_obs_id")
    )


def _ground_station_id(observation: dict):
    for key in ("ground_station", "ground_station_id", "station", "station_id"):
        value = observation.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _max_elevation(observation: dict):
    for key in (
        "max_elevation",
        "max_elevation_deg",
        "max_altitude",
        "min_max_altitude",
        "elevation_max",
        "elevation",
    ):
        value = observation.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


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


def _fetch_observation_detail(observation_id: int | str) -> dict:
    endpoints = [
        urljoin(
            config.SATNOGS_NETWORK_API_BASE.rstrip("/") + "/",
            f"observations/{observation_id}/",
        ),
        urljoin(
            config.SATNOGS_API_BASE.rstrip("/") + "/", f"observations/{observation_id}/"
        ),
    ]
    errors = []
    for endpoint in endpoints:
        try:
            payload = _get_json(endpoint)
            results = _normalize_results(payload)
            if results:
                return results[0]
        except requests.RequestException as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError("Gagal mengambil detail observasi SatNOGS: " + "; ".join(errors))


def get_observations(norad_id, station_id=None, min_elevation=30, limit=20):
    """Ambil daftar observasi SatNOGS berstatus baik untuk NORAD tertentu."""
    endpoint_candidates = [
        urljoin(config.SATNOGS_NETWORK_API_BASE.rstrip("/") + "/", "observations/"),
    ]
    filter_candidates = [
        {"norad_cat_id": norad_id},
    ]

    last_errors = []
    for endpoint in endpoint_candidates:
        for filter_params in filter_candidates:
            params = dict(filter_params)
            params.update(
                {"status": "good", "limit": max(limit * 3, limit), "ordering": "-start"}
            )
            if station_id is not None:
                params["ground_station"] = station_id
            try:
                observations = _normalize_results(_get_json(endpoint, params=params))
            except requests.RequestException as exc:
                last_errors.append(f"{endpoint} {filter_params}: {exc}")
                continue

            filtered = []
            for obs in observations:
                if station_id is not None and _ground_station_id(obs) not in (
                    None,
                    int(station_id),
                ):
                    continue
                elevation = _max_elevation(obs)
                if elevation is not None and elevation < float(min_elevation):
                    continue
                if obs.get("waterfall") or obs.get("waterfall_url"):
                    filtered.append(obs)
                elif _observation_id(obs) is not None:
                    filtered.append(obs)
                if len(filtered) >= limit:
                    return filtered
            if filtered:
                return filtered[:limit]

    raise RuntimeError(
        "Tidak ada observasi yang cocok atau API gagal: " + "; ".join(last_errors[-3:])
    )


def download_waterfall(observation_id, output_dir):
    """Download PNG waterfall dan JSON metadata untuk satu observasi."""
    base_dir = Path(output_dir)
    waterfall_dir = base_dir / "waterfall" if base_dir.name != "waterfall" else base_dir
    metadata_dir = (
        base_dir / "metadata"
        if base_dir.name != "metadata"
        else base_dir.parent / "metadata"
    )
    waterfall_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    try:
        observation = _fetch_observation_detail(observation_id)
        obs_id = _observation_id(observation) or observation_id
        waterfall_url = observation.get("waterfall") or observation.get("waterfall_url")
        if not waterfall_url:
            raise RuntimeError(f"Observasi {obs_id} tidak memiliki URL waterfall")

        png_path = waterfall_dir / f"{obs_id}.png"
        json_path = metadata_dir / f"{obs_id}.json"

        with requests.get(
            waterfall_url, stream=True, timeout=config.REQUEST_TIMEOUT_SECONDS
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            with (
                png_path.open("wb") as file_obj,
                tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    desc=f"Waterfall {obs_id}",
                ) as progress,
            ):
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file_obj.write(chunk)
                        progress.update(len(chunk))

        width, height = _png_dimensions(png_path)
        observation["_local_waterfall_path"] = str(png_path)
        observation["_local_metadata_path"] = str(json_path)
        observation["_local_image_width"] = width
        observation["_local_image_height"] = height
        with json_path.open("w", encoding="utf-8") as file_obj:
            json.dump(observation, file_obj, indent=2, ensure_ascii=False)

        LOG.info("Waterfall observasi %s disimpan ke %s", obs_id, png_path)
        return str(png_path), str(json_path)
    except Exception as exc:  # noqa: BLE001 - pesan error ditampilkan ke user/UI
        LOG.error("Gagal download waterfall %s: %s", observation_id, exc)
        return None


def get_itera_station_id():
    """Cari station_id Stasiun Bumi ITERA dari API SatNOGS."""
    endpoints = [
        urljoin(config.SATNOGS_NETWORK_API_BASE.rstrip("/") + "/", "stations/"),
        urljoin(config.SATNOGS_NETWORK_API_BASE.rstrip("/") + "/", "ground_stations/"),
        urljoin(config.SATNOGS_API_BASE.rstrip("/") + "/", "stations/"),
    ]
    for endpoint in endpoints:
        for query_name in ("search", "name", "name__icontains"):
            try:
                results = _normalize_results(
                    _get_json(endpoint, params={query_name: "ITERA", "limit": 20})
                )
            except requests.RequestException:
                continue
            for item in results:
                text = " ".join(
                    str(item.get(key, ""))
                    for key in ("name", "station_name", "description")
                )
                if "itera" in text.lower():
                    station_id = (
                        item.get("id")
                        or item.get("station_id")
                        or item.get("ground_station")
                    )
                    if station_id is None:
                        return None
                    try:
                        return int(station_id)
                    except (TypeError, ValueError):
                        return None
    return None


def batch_download(norad_id, n_observations=20, station_id=None):
    """Download batch observasi terbaru dan return daftar pasangan file berhasil."""
    downloaded = []
    skipped = 0
    observations = get_observations(
        norad_id=norad_id,
        station_id=station_id,
        min_elevation=config.MIN_ELEVATION_DEG,
        limit=n_observations,
    )
    for observation in observations:
        obs_id = _observation_id(observation)
        if obs_id is None:
            skipped += 1
            continue
        result = download_waterfall(obs_id, config.DATA_DIR)
        if result is None:
            skipped += 1
        else:
            downloaded.append(result)

    print(f"Ringkasan download: {len(downloaded)} berhasil, {skipped} dilewati/gagal")
    return downloaded
