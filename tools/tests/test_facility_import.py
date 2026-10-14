"""이관 출처 추적, 오래된 행 제외, 간접·오류 좌표 취급을 검증한다."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_facilities import prepare_additional_facilities


@pytest.fixture
def generated(tmp_path):
    # 실제 동결 파일을 읽되 출력은 임시 폴더로 한정한다.
    (tmp_path / "data").mkdir()
    (tmp_path / "data/raw").symlink_to(ROOT / "data/raw", target_is_directory=True)
    shutil.copy2(ROOT / "data/sources.json", tmp_path / "data/sources.json")
    report = prepare_additional_facilities(tmp_path)
    with (tmp_path / "data/derived/additional_facilities.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    geojson = json.loads((tmp_path / "data/derived/additional_facilities.geojson").read_text())
    return report, rows, geojson


def test_imported_files_have_intact_bytes_and_canonical_sources():
    meta = json.loads((ROOT / "data/gunwi/_meta.json").read_text())
    sources = {s["id"]: s for s in json.loads((ROOT / "data/sources.json").read_text())["sources"]}
    assert len(meta["files"]) == 46
    assert meta["provenance"] == "verified_import"
    assert meta["original_government_bytes"] is False
    for path, info in meta["files"].items():
        b = (ROOT / path).read_bytes()
        assert hashlib.sha256(b).hexdigest() == info["sha256"], path
        assert len(b) == info["bytes"]
        assert info["source_ids"]
        for sid in info["source_ids"]:
            assert sources[sid]["url"] and sources[sid]["reference_date"]


def test_excludes_old_cctv_private_parking_and_released_stream(generated):
    report, rows, _ = generated
    assert len(report["categories"]) == 8
    assert all(int(r["reference_date"][:4]) >= 2025 for r in rows)
    assert report["excluded"]["2025년 이전 기준일 CCTV"] == 552
    assert report["excluded"]["민영 주차장"] == 1
    assert report["excluded"]["위험지정 해제 세천"] == 1
    assert not any(r["category"] == "배수시설" and r["name"] == "내량천" for r in rows)


def test_outlier_and_indirect_coordinates_are_explicit(generated):
    report, rows, geojson = generated
    outlier = next(r for r in rows if r["name"] == "202651410000800116")
    assert outlier["reported_latitude"] == "36.851755"
    assert outlier["reported_longitude"] == "128.6946508"
    assert not outlier["latitude"] and not outlier["longitude"]
    assert not any(f["properties"]["id"] == outlier["id"] for f in geojson["features"])
    proxies = [r for r in rows if r["proxy_location"] == "True"]
    assert len(proxies) == 18
    for r in proxies:
        assert r["category"] == "공공보건시설"
        same_source = [x for x in rows if x["category"] == "폐기물 수거시설"
                       and x["source_raw_file"] == r["source_raw_file"]
                       and x["source_record_number"] == r["source_record_number"]]
        assert len(same_source) == 1
        assert same_source[0]["latitude"] == r["latitude"]
        assert same_source[0]["longitude"] == r["longitude"]
    assert report["observation_count"] == 259
    assert report["point_count"] == 251


def test_hwpx_merged_columns_preserve_address_and_capacity(generated):
    _, rows, _ = generated
    shelters = [r for r in rows if r["category"] == "재난대피시설"]
    assert len(shelters) == 5
    assert sum(json.loads(r["attributes"])["수용인원명"] for r in shelters) == 5319
    assert next(r for r in shelters if r["name"] == "농협군위유통센터")["address"] == (
        "대구광역시 군위군 효령면 경북대로 2185")
    assert all(not r["latitude"] for r in shelters)
    assert all(r["reference_date"] == "2026-03" for r in shelters)


def test_changed_raw_file_stops_pipeline(tmp_path):
    registry = json.loads((ROOT / "data/sources.json").read_text())
    parking = next(s for s in registry["sources"] if s["id"] == "DATAGOKR_GUNWI_PARKING")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/sources.json").write_text(json.dumps(registry))
    folder = tmp_path / parking["raw_dir"]
    shutil.copytree(ROOT / parking["raw_dir"], folder)
    path = next(folder.glob("*.csv"))
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(AssertionError, match="해시 불일치"):
        prepare_additional_facilities(tmp_path)
