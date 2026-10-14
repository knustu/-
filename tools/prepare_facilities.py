"""추가 8개 시설 분야의 출처가 있는 위치 관측을 생성한다.

prepare.py에서 호출한다. raw는 읽기만 하며 등록된 출처 카드의 해시를 검사한다.
읍면 배정·밀도·민원 점수는 생성하지 않는다. 출처 미확인 경계는 사용하지 않는다.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

CATEGORIES = (
    "교통시설", "폐기물 수거시설", "배수시설", "안전시설",
    "체육·문화시설", "쉼터·놀이시설", "재난대피시설", "공공보건시설",
)
CUTOFF = "2025-01-01"


def prepare_additional_facilities(root: Path) -> dict:
    sources = {s["id"]: s for s in json.loads(
        (root / "data/sources.json").read_text(encoding="utf-8"))["sources"]}
    records = []
    checked = set()
    excluded = Counter()

    def raw_file(source_id, filename=None, suffix=".csv"):
        source = sources[source_id]
        folder = root / source["raw_dir"]
        meta = json.loads((folder / "_meta.json").read_text(encoding="utf-8"))
        assert meta["source_id"] in [source_id] + source.get("raw_source_ids", []), (
            f"{source_id}: 출처 카드 ID 불일치")
        assert meta["url"] == source["url"], f"{source_id}: 원출처 URL 불일치"
        assert meta["provenance"] == "verified", f"{source_id}: 공식 원본 확인 필요"
        if folder not in checked:
            for name, info in meta["files"].items():
                b = (folder / name).read_bytes()
                assert hashlib.sha256(b).hexdigest() == info["sha256"], (
                    f"{source_id}/{name}: 동결 원본 해시 불일치")
                assert len(b) == info["bytes"]
            checked.add(folder)
        if filename:
            path = folder / filename
        else:
            paths = sorted(folder.glob("*" + suffix))
            assert len(paths) == 1, f"{source_id}: 입력파일을 명시해야 함"
            path = paths[0]
        assert path.name in meta["files"], f"{source_id}: 미등록 파일"
        return path, meta

    def csv_rows(sid, filename=None):
        path, meta = raw_file(sid, filename)
        text = path.read_bytes().decode(meta.get("encoding", "utf-8-sig"))
        return path, list(csv.DictReader(io.StringIO(text)))

    def add(sid, path, row_no, row, category, kind, name, *,
            ref=None, address=None, lat=None, lon=None, notes="", proxy=False,
            attributes=None):
        ref = ref or row.get("데이터기준일자") or row.get("REFERENCE_DATE")
        assert ref and ref[:4].isdigit() and int(ref[:4]) >= 2025, (
            f"{sid}/{row_no}: 2025년 이전 또는 기준일 미확인")
        if address is None:
            address = row.get("소재지도로명주소") or row.get("소재지지번주소") or ""
        if lat is None:
            lat = row.get("위도") or row.get("WGS84위도") or None
        if lon is None:
            lon = row.get("경도") or row.get("WGS84경도") or None
        assert bool(lat) == bool(lon), f"{sid}/{row_no}: 좌표 쌍 누락"
        reported_lat, reported_lon = lat, lon
        lat, lon = (float(lat), float(lon)) if lat else (None, None)
        coordinate_status = "원본값 사용" if lat is not None else "원본 좌표 없음"
        if lat is not None:
            # 넓은 오류 탐지 범위. 군 경계 안이라는 판정이나 좌표 보정에 쓰지 않는다.
            if not (35.9 <= lat <= 36.5 and 128.3 <= lon <= 128.9):
                coordinate_status = "범위 오류 후보·검토 필요"
                notes += " 원본 좌표는 넓은 군위 범위 밖. reported 좌표는 보존하고 지도용 좌표는 비움. 자동 보정하지 않음."
                lat, lon = None, None
        assert name.strip() and address.strip(), f"{sid}/{row_no}: 이름·주소 누락"
        records.append({
            "id": f"{sid}:{row_no}:{CATEGORIES.index(category) + 1}",
            "category": category, "facility_type": kind, "name": name,
            "address": address, "latitude": lat, "longitude": lon,
            "reported_latitude": reported_lat, "reported_longitude": reported_lon,
            "coordinate_status": coordinate_status,
            "reference_date": ref, "source_id": sid,
            "source_url": sources[sid]["url"],
            "source_raw_file": str(path.relative_to(root)),
            "source_record_number": row_no,
            "location_evidence": "보건시설 내 수거함 좌표(간접 근거)" if proxy else
                                 "원본 시설 좌표" if lat is not None else
                                 "원본 좌표 검토 필요·주소 사용" if reported_lat else "원본 주소만",
            "proxy_location": proxy, "notes": notes,
            "attributes": attributes or {},
        })

    sid = "DATAGOKR_GUNWI_PARKING"
    path, rows = csv_rows(sid)
    for i, row in enumerate(rows, 1):
        if row["주차장구분"] != "공영":
            excluded["민영 주차장"] += 1
            continue
        add(sid, path, i, row, CATEGORIES[0], "공영주차장", row["주차장명"],
            attributes={"주차구획수": row["주차구획수"], "관리기관명": row["관리기관명"]})

    sid = "GUNWI_MEDICINE_BINS"
    path, medicine = csv_rows(sid)
    for i, row in enumerate(medicine, 1):
        add(sid, path, i, row, CATEGORIES[1], "폐의약품수거함", row["설치장소명"],
            notes="약국 내 수거함도 포함. 공공 소유 건물 목록과 구분.",
            attributes={"세부위치": row["세부위치"]})
        if row["설치장소명"].endswith(("보건소", "보건지소", "보건진료소")):
            add(sid, path, i, row, CATEGORIES[7], "공공보건시설(수거함 소재지 근거)",
                row["설치장소명"], proxy=True,
                notes="공식 수거함 자료에 적힌 공공 보건시설명·주소. 좌표는 수거함 좌표이며 건물 중심좌표·운영대장 아님. 폐기물 분야와 같은 원본 행을 재사용하므로 중복 합산 금지.")
    sid = "GUNWI_RECYCLING"
    path, rows = csv_rows(sid)
    for i, row in enumerate(rows, 1):
        add(sid, path, i, row, CATEGORIES[1], "재활용센터", row["재활용센터명"],
            attributes={"주요취급품목정보": row["주요취급품목정보"]})

    sid = "DATAGOKR_GUNWI_SMALL_FACILITY_RISK"
    path, rows = csv_rows(sid)
    for i, row in enumerate(rows, 1):
        if row["시설유형"] != "세천":
            excluded["세천 이외 소규모시설"] += 1
            continue
        if row["위험시설해제일자"].strip():
            excluded["위험지정 해제 세천"] += 1
            continue
        add(sid, path, i, row, CATEGORIES[2], "세천 위험지정 지점", row["시설명"],
            notes="세천의 지정 위치이며 수로 전체 선형·빗물받이·맨홀 전수대장 아님. 원본 지정사유는 공란.",
            attributes={"위험시설지정일자": row["위험시설지정일자"],
                        "위험시설지정고시번호": row["위험시설지정고시번호"]})

    sid = "GUNWI_CCTV"
    path, rows = csv_rows(sid, "cctv_download.bin")
    for i, row in enumerate(rows, 1):
        if row["데이터기준일자"] < CUTOFF:
            excluded["2025년 이전 기준일 CCTV"] += 1
            continue
        add(sid, path, i, row, CATEGORIES[3], "CCTV", row["관리번호"],
            notes="관리번호를 이름으로 사용. 카메라 대수와 위치 행 수는 다른 개념.",
            attributes={"설치목적구분": row["설치목적구분"],
                        "카메라대수": row["카메라대수"],
                        "촬영방면정보": row["촬영방면정보"]})

    for sid in ["GUNWI_LIBRARIES", "GUNWI_EDUCATION_LIBRARY", "GUNWI_OPEN_FACILITIES"]:
        path, rows = csv_rows(sid)
        for i, row in enumerate(rows, 1):
            name = row.get("도서관명") or row["개방시설명"]
            kind = row.get("도서관유형") or row["개방시설유형구분"]
            add(sid, path, i, row, CATEGORIES[4], kind, name,
                notes="공공 이용 가능 시설. 개방 공연장·수영장은 같은 주소·좌표이며 부지 수로 합산 금지. 새마을문고는 군위군 새마을회 운영.")

    sid = "DATAGOKR_PARK"
    path, _ = raw_file(sid, "parks.json")
    for i, row in enumerate(json.loads(path.read_text(encoding="utf-8")), 1):
        add(sid, path, i, row, CATEGORIES[5], "어린이공원", row["PARK_NM"],
            address=row["RDNMADR"] or row["LNMADR"], lat=row["LATITUDE"], lon=row["LONGITUDE"],
            notes="공원 부지 좌표. 개별 놀이기구 위치·검사대장 및 무더위쉼터 전수자료 아님.",
            attributes={"유희시설": row["AMSMT_FCLTY"]})

    sid = "GUNWI_CIVIL_SHELTERS"
    path, _ = raw_file(sid, "shelter_202603_hwpx.hwpx")
    ns = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}
    shelters = []
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("Contents/section0.xml"))
        for table in doc.findall(".//hp:tbl", ns):
            for tr in table.findall("hp:tr", ns):
                cells = {int(tc.find("hp:cellAddr", ns).get("colAddr")):
                         "".join(tc.itertext()).strip() for tc in tr.findall("hp:tc", ns)}
                if cells.get(0, "").isdigit() and cells.get(2) and cells.get(3):
                    shelters.append(cells)
    assert len(shelters) == 5, "2026.3 대피시설 현황 행수 확인 필요"
    assert sum(int(s[5].replace(",", "")) for s in shelters) == 5319
    for cells in shelters:
        add(sid, path, int(cells[0]), {}, CATEGORIES[6], "민방위 주민대피시설",
            cells[2], ref=sources[sid]["reference_date"],
            address="대구광역시 군위군 " + cells[3],
            notes="공공용 대피시설. 기준일은 2026년 3월까지만 확인; 주소만 제공. 지정해제된 군위읍 행정복지센터 제외.",
            attributes={"면적㎡": int(cells[4].replace(",", "")),
                        "수용인원명": int(cells[5].replace(",", ""))})

    # CSV·GeoJSON은 '관측 행'이며 분야 간 같은 장소를 합산한 시설 수가 아니다.
    derived = root / "data/derived"
    derived.mkdir(parents=True, exist_ok=True)
    fields = [k for k in records[0] if k != "attributes"] + ["attributes"]
    with (derived / "additional_facilities.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({**row, "attributes": json.dumps(row["attributes"], ensure_ascii=False)})
    features = [{"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
                 "properties": r} for r in records if r["latitude"] is not None]
    gj = {"type": "FeatureCollection", "features": features,
          "_warning": "간접 보건시설 위치 포함(proxy_location=true). 동일 장소·원본 행을 분야별로 재사용하므로 합산 시설 수로 해석하지 말 것. 읍면 미배정."}
    (derived / "additional_facilities.geojson").write_text(
        json.dumps(gj, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {
        "cutoff": CUTOFF, "observation_count": len(records),
        "point_count": len(features),
        "address_only_count": sum(r["latitude"] is None for r in records),
        "proxy_location_count": sum(r["proxy_location"] for r in records),
        "coordinate_review": [{"id": r["id"], "source_id": r["source_id"],
                               "source_record_number": r["source_record_number"],
                               "reported_latitude": r["reported_latitude"],
                               "reported_longitude": r["reported_longitude"]}
                              for r in records if r["coordinate_status"] == "범위 오류 후보·검토 필요"],
        "categories": [{"name": c,
                        "observations": sum(r["category"] == c for r in records),
                        "points": sum(r["category"] == c and r["latitude"] is not None for r in records),
                        "source_ids": sorted({r["source_id"] for r in records if r["category"] == c})}
                       for c in CATEGORIES],
        "excluded": dict(excluded),
        "unavailable_latest_registers": ["신호등·횡단보도 전수 위치", "재활용 분리수거함 전수 위치",
            "빗물받이·맨홀 전수 위치", "AED·별도 안전비상벨 위치",
            "무더위쉼터 전수 위치", "지진옥외대피소 위치", "공공보건시설 운영대장"],
        "limitations": ["시설 수 합계 아님; 같은 장소의 별도 기능과 분야 간 재사용 포함",
                        "경계 출처 미확인 문제를 해결한 자료가 아님; 읍면별 배정·밀도 미생성",
                        "민원 건별 위치와 보수 이력 부족; 시설관리 필요도 및 종합 우선순위 미산출"],
    }
    (derived / "additional_facilities_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  추가 시설 관측 {len(records)}행 / 좌표 {len(features)}행 / 간접 위치 {report['proxy_location_count']}행")
    return report
