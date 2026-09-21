"""表示・取得対象の地区定義。

新しい地区を足すときは AREAS にエントリを追加する。取得ジョブは定義された地区を順に処理する。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Station:
    id: str
    name: str
    name_kana: str
    en_name: str
    latitude: float
    longitude: float
    altitude_m: int
    office: str
    place: str
    note: str

    def as_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "nameKana": self.name_kana,
            "enName": self.en_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitudeM": self.altitude_m,
            "office": self.office,
            "place": self.place,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Area:
    id: str
    name: str
    station: Station

    def as_json(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name}


AREAS: dict[str, Area] = {
    "yokohama": Area(
        id="yokohama",
        name="横浜市",
        station=Station(
            id="46106",
            name="横浜",
            name_kana="ヨコハマ",
            en_name="Yokohama",
            latitude=35 + 26.3 / 60,
            longitude=139 + 39.1 / 60,
            altitude_m=39,
            office="横浜地方気象台",
            place="横浜市中区山手町",
            note="気象庁・横浜地方気象台の10分値を使用する。",
        ),
    ),
}


def get_area(area_id: str) -> Area:
    try:
        return AREAS[area_id]
    except KeyError as error:
        known = ", ".join(AREAS) or "(none)"
        raise ValueError(f"未知の地区です: {area_id}（定義済み: {known}）") from error


def resolve_areas(area_ids: list[str] | None) -> list[Area]:
    if not area_ids:
        return list(AREAS.values())
    return [get_area(area_id) for area_id in area_ids]
