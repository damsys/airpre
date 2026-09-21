"""気象庁 AMeDAS から地区ごとの気圧を取得し、リポジトリ内の JSON に蓄積する。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from airpre.areas import AREAS, Area, resolve_areas

JST = timezone(timedelta(hours=9))
LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
POINT_URL = "https://www.jma.go.jp/bosai/amedas/data/point/{station}/{stamp}.json"
USER_AGENT = "airpre/0.1 (+https://github.com/damsys/airpre)"
DEFAULT_LOOKBACK_DAYS = 7
LATEST_WINDOW_DAYS = 14
OBS_INTERVAL = timedelta(minutes=10)
HTTP_TIMEOUT_SEC = 30

LOGGER = logging.getLogger("airpre")


def parse_jma_value(raw: Any) -> float | None:
    if not isinstance(raw, list) or not raw:
        return None
    value = raw[0]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_jma_time_key(key: str) -> datetime:
    return datetime.strptime(key, "%Y%m%d%H%M%S").replace(tzinfo=JST)


def parse_point_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for key, row in payload.items():
        if not isinstance(row, dict):
            continue
        pressure = parse_jma_value(row.get("pressure"))
        pressure_msl = parse_jma_value(row.get("normalPressure"))
        if pressure is None and pressure_msl is None:
            continue
        observed_at = parse_jma_time_key(key)
        observations.append(
            {
                "time": observed_at.isoformat(timespec="seconds"),
                "pressure": pressure,
                "pressureMsl": pressure_msl,
            }
        )
    observations.sort(key=lambda item: item["time"])
    return observations


def merge_observations(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_time = {item["time"]: item for item in existing}
    by_time.update({item["time"]: item for item in incoming})
    return [by_time[key] for key in sorted(by_time)]


def align_to_slot(moment: datetime) -> datetime:
    local = moment.astimezone(JST).replace(minute=0, second=0, microsecond=0)
    hour = local.hour - (local.hour % 3)
    return local.replace(hour=hour)


def align_to_10min(moment: datetime) -> datetime:
    local = moment.astimezone(JST).replace(second=0, microsecond=0)
    return local.replace(minute=local.minute - local.minute % 10)


def iter_slots(start: datetime, end: datetime) -> list[tuple[str, str]]:
    current = align_to_slot(start)
    last = align_to_slot(end)
    slots: list[tuple[str, str]] = []
    while current <= last:
        slots.append((current.strftime("%Y%m%d"), f"{current.hour:02d}"))
        current += timedelta(hours=3)
    return slots


def slot_key(moment: datetime) -> tuple[str, str]:
    aligned = align_to_slot(moment)
    return aligned.strftime("%Y%m%d"), f"{aligned.hour:02d}"


def expected_observation_times(start: datetime, end: datetime) -> list[datetime]:
    current = align_to_10min(start)
    last = align_to_10min(end)
    times: list[datetime] = []
    while current <= last:
        times.append(current)
        current += OBS_INTERVAL
    return times


def load_archive_observations(archive_dir: Path) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    if not archive_dir.exists():
        return merged
    for path in sorted(archive_dir.glob("*.json")):
        merged = merge_observations(merged, load_day_file(path))
    return merged


def missing_slots(
    existing: list[dict[str, Any]],
    latest_time: datetime,
    lookback_days: int,
) -> list[tuple[str, str]]:
    have = {item["time"] for item in existing}
    start = latest_time - timedelta(days=lookback_days)
    slots: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for moment in expected_observation_times(start, latest_time):
        if moment.isoformat(timespec="seconds") in have:
            continue
        key = slot_key(moment)
        if key not in seen:
            seen.add(key)
            slots.append(key)
    return slots


def http_get(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            LOGGER.debug("not found: %s", url)
            return None
        raise


def fetch_latest_time() -> datetime:
    text = http_get(LATEST_TIME_URL)
    if text is None:
        raise RuntimeError("latest_time.txt を取得できませんでした")
    return datetime.fromisoformat(text.strip())


def fetch_slot(station_id: str, date: str, hour: str) -> list[dict[str, Any]]:
    stamp = f"{date}_{hour}"
    url = POINT_URL.format(station=station_id, stamp=stamp)
    body = http_get(url)
    if body is None:
        return []
    payload = json.loads(body)
    if not isinstance(payload, dict):
        return []
    return parse_point_payload(payload)


def observation_date(observation: dict[str, Any]) -> str:
    return datetime.fromisoformat(observation["time"]).astimezone(JST).date().isoformat()


def group_by_day(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        grouped.setdefault(observation_date(observation), []).append(observation)
    return grouped


def load_day_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    observations = payload.get("observations", [])
    return observations if isinstance(observations, list) else []


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def dump_dataset(
    area: Area,
    observations: list[dict[str, Any]],
    updated_at: datetime,
) -> dict[str, Any]:
    return {
        "area": area.as_json(),
        "station": area.station.as_json(),
        "timezone": "Asia/Tokyo",
        "updatedAt": updated_at.astimezone(JST).isoformat(timespec="seconds"),
        "source": {
            "name": "気象庁 AMeDAS",
            "url": "https://www.jma.go.jp/bosai/amedas/",
            "stationId": area.station.id,
        },
        "observations": observations,
    }


def rebuild_latest(area: Area, archive_dir: Path, latest_path: Path, updated_at: datetime) -> None:
    cutoff = updated_at.astimezone(JST) - timedelta(days=LATEST_WINDOW_DAYS)
    merged: list[dict[str, Any]] = []
    if archive_dir.exists():
        for path in sorted(archive_dir.glob("*.json")):
            merged = merge_observations(merged, load_day_file(path))
    windowed = [item for item in merged if datetime.fromisoformat(item["time"]) >= cutoff]
    write_json(latest_path, dump_dataset(area, windowed, updated_at))


def write_area_index(
    area: Area, area_dir: Path, archive_dir: Path, updated_at: datetime
) -> None:
    days = sorted(path.stem for path in archive_dir.glob("*.json")) if archive_dir.exists() else []
    write_json(
        area_dir / "index.json",
        {
            "areaId": area.id,
            "updatedAt": updated_at.astimezone(JST).isoformat(timespec="seconds"),
            "latest": f"data/{area.id}/latest.json",
            "days": days,
        },
    )


def write_catalog(data_dir: Path, updated_at: datetime) -> None:
    entries = []
    for area in AREAS.values():
        latest = data_dir / area.id / "latest.json"
        entries.append(
            {
                "id": area.id,
                "name": area.name,
                "hasData": latest.exists(),
                "latest": f"data/{area.id}/latest.json",
            }
        )
    write_json(
        data_dir / "areas.json",
        {
            "updatedAt": updated_at.astimezone(JST).isoformat(timespec="seconds"),
            "areas": entries,
        },
    )


def sync_archive(
    observations: list[dict[str, Any]],
    archive_dir: Path,
    station_id: str,
) -> list[dict[str, Any]]:
    grouped = group_by_day(observations)
    written: list[dict[str, Any]] = []
    for day in sorted(grouped):
        path = archive_dir / f"{day}.json"
        merged = merge_observations(load_day_file(path), grouped[day])
        write_json(
            path,
            {
                "date": day,
                "stationId": station_id,
                "observations": merged,
            },
        )
        written.extend(merged)
    return merge_observations([], written)


def collect_observations(
    area: Area,
    latest_time: datetime,
    lookback_days: int,
    archive_dir: Path,
) -> list[dict[str, Any]]:
    existing = load_archive_observations(archive_dir)
    slots = missing_slots(existing, latest_time, lookback_days)
    if not slots:
        LOGGER.info("%s: no missing slots", area.id)
        return []
    LOGGER.info("%s: fetching %s missing slots", area.id, len(slots))
    incoming: list[dict[str, Any]] = []
    for date, hour in slots:
        incoming = merge_observations(incoming, fetch_slot(area.station.id, date, hour))
        LOGGER.info("%s: fetched slot %s_%s (%s points)", area.id, date, hour, len(incoming))
    return incoming


def run_area(
    area: Area, data_dir: Path, latest_time: datetime, lookback_days: int
) -> tuple[int, bool]:
    area_dir = data_dir / area.id
    archive_dir = area_dir / "archive"
    incoming = collect_observations(area, latest_time, lookback_days, archive_dir)
    if not incoming:
        if load_archive_observations(archive_dir):
            return 0, False
        LOGGER.error("%s: 観測データを1件も取得できませんでした", area.id)
        return 1, False
    sync_archive(incoming, archive_dir, area.station.id)
    rebuild_latest(area, archive_dir, area_dir / "latest.json", latest_time)
    write_area_index(area, area_dir, archive_dir, latest_time)
    LOGGER.info(
        "%s: saved %s new observations through %s",
        area.id,
        len(incoming),
        latest_time.astimezone(JST).isoformat(timespec="minutes"),
    )
    return 0, True


def run(data_dir: Path, lookback_days: int, area_ids: list[str] | None) -> int:
    areas = resolve_areas(area_ids)
    latest_time = fetch_latest_time()
    failed = 0
    updated = False
    for area in areas:
        code, wrote = run_area(area, data_dir, latest_time, lookback_days)
        failed += code
        updated = updated or wrote
    if updated:
        write_catalog(data_dir, latest_time)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="気象庁から地区ごとの気圧を取得して data/ に保存する"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="保存先ディレクトリ（既定: ./data）",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="不足判定の対象にする遡及日数（既定: 7）",
    )
    parser.add_argument(
        "--area",
        action="append",
        dest="areas",
        help="取得する地区 ID。省略時は定義済みの全地区",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return run(args.data_dir, args.lookback_days, args.areas)
    except Exception:
        LOGGER.exception("気圧データの取得に失敗しました")
        return 1


if __name__ == "__main__":
    sys.exit(main())
