import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from airpre.areas import AREAS, get_area, resolve_areas
from airpre.fetch import (
    JST,
    align_to_slot,
    dump_dataset,
    iter_slots,
    merge_observations,
    missing_slots,
    parse_jma_time_key,
    parse_jma_value,
    parse_point_payload,
    sync_archive,
    write_catalog,
)


class AreaRegistryTests(unittest.TestCase):
    def test_registry_has_unique_ids(self) -> None:
        self.assertGreaterEqual(len(AREAS), 1)
        self.assertEqual(len(AREAS), len(set(AREAS)))

    def test_resolve_areas_defaults_to_all(self) -> None:
        self.assertEqual(resolve_areas(None), list(AREAS.values()))

    def test_get_area_rejects_unknown_id(self) -> None:
        with self.assertRaises(ValueError):
            get_area("unknown-area")


class ParseTests(unittest.TestCase):
    def test_parse_jma_value(self) -> None:
        self.assertEqual(parse_jma_value([994.3, 0]), 994.3)
        self.assertIsNone(parse_jma_value([None, 5]))
        self.assertIsNone(parse_jma_value(None))

    def test_parse_jma_time_key_is_jst(self) -> None:
        moment = parse_jma_time_key("20260921115000")
        self.assertEqual(moment.isoformat(timespec="seconds"), "2026-09-21T11:50:00+09:00")

    def test_parse_point_payload_skips_null_pressure(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "point_sample.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        observations = parse_point_payload(payload)
        self.assertEqual(
            [item["time"] for item in observations],
            ["2026-09-21T11:40:00+09:00", "2026-09-21T11:50:00+09:00"],
        )
        self.assertEqual(observations[-1]["pressureMsl"], 999.2)


class MergeTests(unittest.TestCase):
    def test_merge_observations_overrides_same_time(self) -> None:
        existing = [{"time": "2026-09-21T11:40:00+09:00", "pressure": 994.7, "pressureMsl": 999.6}]
        incoming = [{"time": "2026-09-21T11:40:00+09:00", "pressure": 994.8, "pressureMsl": 999.7}]
        merged = merge_observations(existing, incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["pressure"], 994.8)

    def test_iter_slots_covers_inclusive_range(self) -> None:
        start = datetime(2026, 9, 21, 10, 5, tzinfo=JST)
        end = datetime(2026, 9, 21, 12, 0, tzinfo=JST)
        self.assertEqual(iter_slots(start, end), [("20260921", "09"), ("20260921", "12")])

    def test_align_to_slot(self) -> None:
        moment = datetime(2026, 9, 21, 11, 50, tzinfo=JST)
        self.assertEqual(align_to_slot(moment).hour, 9)

    def test_sync_archive_writes_daily_files(self) -> None:
        incoming = [
            {"time": "2026-09-20T23:50:00+09:00", "pressure": 1001.0, "pressureMsl": 1006.0},
            {"time": "2026-09-21T00:00:00+09:00", "pressure": 1000.5, "pressureMsl": 1005.5},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = Path(tmp) / "archive"
            merged = sync_archive(incoming, archive_dir, "46106")
            self.assertEqual(len(merged), 2)
            day = json.loads((archive_dir / "2026-09-21.json").read_text(encoding="utf-8"))
            self.assertEqual(day["date"], "2026-09-21")
            self.assertEqual(day["stationId"], "46106")
            self.assertEqual(len(day["observations"]), 1)

    def test_missing_slots_empty_when_complete(self) -> None:
        latest = datetime(2026, 9, 21, 12, 30, tzinfo=JST)
        existing = []
        moment = latest - timedelta(days=1)
        while moment <= latest:
            existing.append({"time": moment.isoformat(timespec="seconds")})
            moment += timedelta(minutes=10)
        self.assertEqual(missing_slots(existing, latest, lookback_days=1), [])

    def test_missing_slots_only_current_incomplete_slot(self) -> None:
        latest = datetime(2026, 9, 21, 12, 30, tzinfo=JST)
        existing = []
        moment = latest - timedelta(days=1)
        while moment <= datetime(2026, 9, 21, 11, 50, tzinfo=JST):
            existing.append({"time": moment.isoformat(timespec="seconds")})
            moment += timedelta(minutes=10)
        self.assertEqual(missing_slots(existing, latest, lookback_days=1), [("20260921", "12")])

    def test_missing_slots_detects_gap_in_past_slot(self) -> None:
        latest = datetime(2026, 9, 21, 12, 30, tzinfo=JST)
        gap = datetime(2026, 9, 21, 10, 20, tzinfo=JST)
        existing = []
        moment = latest - timedelta(days=1)
        while moment <= latest:
            if moment != gap:
                existing.append({"time": moment.isoformat(timespec="seconds")})
            moment += timedelta(minutes=10)
        self.assertEqual(missing_slots(existing, latest, lookback_days=1), [("20260921", "09")])

    def test_dump_dataset_includes_area(self) -> None:
        area = next(iter(AREAS.values()))
        payload = dump_dataset(area, [], datetime(2026, 9, 21, 12, 0, tzinfo=JST))
        self.assertEqual(payload["area"]["id"], area.id)
        self.assertEqual(payload["station"]["id"], area.station.id)

    def test_write_catalog_marks_areas_without_latest(self) -> None:
        area = next(iter(AREAS.values()))
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_catalog(data_dir, datetime(2026, 9, 21, 12, 0, tzinfo=JST))
            catalog = json.loads((data_dir / "areas.json").read_text(encoding="utf-8"))
            entry = next(item for item in catalog["areas"] if item["id"] == area.id)
            self.assertFalse(entry["hasData"])
            (data_dir / area.id).mkdir()
            (data_dir / area.id / "latest.json").write_text("{}", encoding="utf-8")
            write_catalog(data_dir, datetime(2026, 9, 21, 12, 0, tzinfo=JST))
            catalog = json.loads((data_dir / "areas.json").read_text(encoding="utf-8"))
            entry = next(item for item in catalog["areas"] if item["id"] == area.id)
            self.assertTrue(entry["hasData"])


if __name__ == "__main__":
    unittest.main()
