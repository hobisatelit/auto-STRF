#!/usr/bin/env python3
"""Smoke tests for the STRF automation pipeline core modules."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from modules import analysis, coordinate_converter, rffit_runner  # noqa: E402


class CoordinateConverterTests(unittest.TestCase):
    def test_parse_metadata_and_convert_pixels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "123.json"
            json_path.write_text(
                json.dumps(
                    {
                        "id": 123,
                        "start": "2023-01-01T00:00:00Z",
                        "end": "2023-01-01T00:10:00Z",
                        "f_min": 100.0,
                        "f_max": 200.0,
                        "img_width": 101,
                        "img_height": 11,
                        "ground_station": 1,
                    }
                ),
                encoding="utf-8",
            )

            metadata = coordinate_converter.parse_metadata(json_path)
            self.assertEqual(metadata["observation_id"], 123)
            self.assertEqual(metadata["delta_t"], 600.0)
            self.assertEqual(metadata["t_start"].tzinfo, timezone.utc)

            converted = coordinate_converter.pixels_to_freq_time(
                [(0, 0), (10, 100)], metadata
            )
            self.assertEqual(converted[0][0], 100.0)
            self.assertEqual(converted[1][0], 200.0)
            self.assertEqual((converted[1][1] - converted[0][1]).total_seconds(), 600.0)


class RffitRunnerTests(unittest.TestCase):
    def test_parse_batch_metrics(self):
        output = """
Loaded 1 orbits
BATCH_OBSERVATIONS 12
BATCH_RMSE_BEFORE_KHZ 0.613890
BATCH_RMSE_AFTER_KHZ 0.012353
BATCH_OUTPUT_TLE out.tle
"""
        self.assertEqual(
            rffit_runner._parse_batch_float(output, "BATCH_RMSE_BEFORE_KHZ"),
            0.613890,
        )
        self.assertEqual(
            rffit_runner._parse_batch_float(output, "BATCH_RMSE_AFTER_KHZ"),
            0.012353,
        )
        self.assertEqual(
            rffit_runner._parse_batch_metric(output, "BATCH_OBSERVATIONS"), "12"
        )


class AnalysisTests(unittest.TestCase):
    def test_compare_rmse(self):
        comparison = analysis.compare_rmse(
            [{"rmse_before": 2.0, "rmse_after": 1.0}],
            [{"rmse_before": 4.0, "rmse_after": 1.0}],
        )
        self.assertEqual(comparison["itera"]["n"], 1)
        self.assertEqual(comparison["global"]["n"], 1)
        self.assertEqual(comparison["itera"]["improvement_percent"], 50.0)
        self.assertEqual(comparison["global"]["improvement_percent"], 75.0)


if __name__ == "__main__":
    unittest.main()
