"""data/raw -> data/derived

원자료를 검증하고 정제해 derived/에 쓴다. raw/는 절대 수정하지 않는다.
검증에 실패하면 assert로 멈춘다 - 조용히 넘어가지 않는다.

  python tools/prepare.py
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"

# 주민등록 인구 파일이 제공하는 기준시점별 폴더
MOIS_PERIODS = ["2023-12", "2024-12", "2025-12", "2026-08"]

GUNWI_CODE = "2772000000"        # 군 합계 행. 읍면과 절대 함께 더하지 않는다
ELDERLY_FROM_BUCKET = 13         # 5세 구간 인덱스 13 == 65세
SEX_BLOCKS = {"total": 0, "male": 23, "female": 46}
GUNWI_BBOX = (128.3, 35.9, 128.9, 36.5)   # lon_min, lat_min, lon_max, lat_max


def _num(value) -> int:
    return int(str(value).replace(",", "").strip())


def read_meta(folder: str) -> dict:
    meta = json.loads((RAW / folder / "_meta.json").read_text(encoding="utf-8"))
    assert meta.get("provenance"), f"{folder}: provenance 필드 없음"
    return meta


# ---------------------------------------------------------------- 인구

def prepare_population():
    """행정안전부 연령별 인구. 4개 시점 x (군 합계 1 + 읍면 8) = 36행."""
    records = []
    name_by_code = {}

    for period in MOIS_PERIODS:
        folder = f"mois-age-{period}"
        meta = read_meta(folder)
        rows = json.loads((RAW / folder / "age.json").read_text(encoding="utf-8"))

        assert len(rows) == 9, f"{folder}: 9행이어야 하는데 {len(rows)}행"

        gunwi_total = None
        eupmyeon_total = 0
        for row in rows:
            code, name = row[0], row[1]
            nums = [_num(v) for v in row[2:]]
            assert len(nums) == 69, f"{folder}/{name}: 69칸이어야 하는데 {len(nums)}칸"

            # 성별 블록마다 5세 구간 21개의 합이 그 블록 총계와 같아야 한다
            block = {}
            for label, off in SEX_BLOCKS.items():
                buckets = nums[off + 2: off + 23]
                assert len(buckets) == 21
                assert nums[off] == sum(buckets), (
                    f"{folder}/{name}/{label}: 구간합 != 총계")
                block[label] = nums[off]

            assert block["total"] == block["male"] + block["female"], (
                f"{folder}/{name}: 남+여 != 계")

            elderly = sum(nums[2 + ELDERLY_FROM_BUCKET: 2 + 21])
            is_gunwi = code == GUNWI_CODE

            records.append({
                "period": period,
                "reference_date": meta["reference_date"],
                "region_code": code,
                "region_name": name,
                "level": "gun" if is_gunwi else "eupmyeon",
                "population": block["total"],
                "male": block["male"],
                "female": block["female"],
                "elderly": elderly,
            })

            if is_gunwi:
                gunwi_total = block["total"]
            else:
                eupmyeon_total += block["total"]
                name_by_code[code] = name

        assert gunwi_total is not None, f"{folder}: 군 합계 행이 없다"
        assert eupmyeon_total == gunwi_total, (
            f"{folder}: 읍면 합계 {eupmyeon_total} != 군 합계 {gunwi_total}")

    assert len(name_by_code) == 8, f"읍면이 8개가 아님: {len(name_by_code)}"
    assert len(records) == len(MOIS_PERIODS) * 9
    return records, name_by_code


# ---------------------------------------------------------------- 공원

def prepare_parks():
    folder = "datagokr-park-2026-03-05"
    read_meta(folder)
    rows = json.loads((RAW / folder / "parks.json").read_text(encoding="utf-8"))
    header = json.loads((RAW / folder / "header.json").read_text(encoding="utf-8"))
    labels = {h["columCode"]: h["columNm"] for h in header["columList"]}

    assert len({r["MANAGE_NO"] for r in rows}) == len(rows), "관리번호 중복"

    lon_min, lat_min, lon_max, lat_max = GUNWI_BBOX
    parks = []
    for r in rows:
        lon, lat = float(r["LONGITUDE"]), float(r["LATITUDE"])
        assert lon_min <= lon <= lon_max and lat_min <= lat <= lat_max, (
            f"{r['PARK_NM']}: 군위군 범위 밖 좌표 ({lon}, {lat})")
        parks.append({
            "manage_no": r["MANAGE_NO"],
            "name": r["PARK_NM"],
            "category": r["PARK_SE"],
            "address": r["RDNMADR"],
            "lon": lon,
            "lat": lat,
            "area_sqm": float(r["PARK_AR"]) if r["PARK_AR"] else None,
            "reference_date": r["REFERENCE_DATE"],
        })
    return parks, labels


# ---------------------------------------------------------- 행정리 과거인구

def prepare_village_history() -> dict:
    """2008~2021 행정리 인구. 원본 품질 문제를 '보존한 채로' 기록한다."""
    folder = "gunwi-village-population-2008-2021"
    meta = read_meta(folder)
    text = (RAW / folder / "population.csv").read_bytes().decode(meta["encoding"])
    raw_rows = list(csv.reader(io.StringIO(text)))
    header, body = raw_rows[0], raw_rows[1:]

    rows = []
    for r in body:
        rows.append({
            "year": int(r[0]),
            "village": r[1].strip(),
            "male": _num(r[2]),
            "female": _num(r[3]),
            "total": _num(r[4]),
            "households": _num(r[5]),
        })

    sum_mismatch = [x for x in rows if x["male"] + x["female"] != x["total"]]
    dup_keys = Counter((x["year"], x["village"]) for x in rows)
    duplicates = {f"{y}/{v}": n for (y, v), n in dup_keys.items() if n > 1}

    return {
        "_warning": (
            "자동 교정하지 않은 원본이다. 최신 인구 분모로 사용 금지. "
            "읍면코드가 없어 리명만으로 결합 금지."),
        "header": header,
        "row_count": len(rows),
        "years": sorted({x["year"] for x in rows}),
        "sum_mismatch_count": len(sum_mismatch),
        "duplicate_key_count": len(duplicates),
        "duplicate_keys": duplicates,
        "rows": rows,
    }


# ---------------------------------------------------------------- 경계

def prepare_boundary(name_by_code: dict) -> dict:
    """읍면 경계에 region_code를 심는다.

    원본 피처는 ADM_CD(22520111 계열)를 갖는데 인구 데이터의 행정기관코드
    (2772025000 계열)와 다른 체계다. 지역명으로 여기서 한 번만 맞춰 코드를
    심고, 이후 웹에서는 코드만 쓴다 - 런타임 이름 매칭을 없앤다.
    """
    folder = "boundary-eupmyeon-2025-06-30"
    meta = read_meta(folder)
    gj = json.loads((RAW / folder / "eupmyeon.geojson").read_text(encoding="utf-8"))

    assert len(gj["features"]) == 8, (
        f"경계 피처가 8개가 아님: {len(gj['features'])}")

    code_by_name = {v: k for k, v in name_by_code.items()}
    assert len(code_by_name) == 8, "읍면 이름이 중복됨"

    seen = set()
    for feat in gj["features"]:
        props = feat["properties"]
        raw_name = str(props.get("ADM_NM") or props.get("adm_nm") or "")
        name = raw_name.split()[-1] if raw_name else ""
        assert name in code_by_name, f"인구 데이터에 없는 읍면: {raw_name!r}"
        code = code_by_name[name]
        assert code not in seen, f"경계 피처 중복: {name}"
        seen.add(code)
        feat["properties"] = {
            "region_code": code,
            "region_name": name,
            "source_adm_cd": props.get("ADM_CD"),
            "base_date": props.get("BASE_DATE"),
        }

    assert seen == set(name_by_code), "경계와 인구의 읍면 집합이 다름"

    gj["_provenance"] = meta["provenance"]
    if meta["provenance"] != "verified":
        print(f"  ! 경계 출처 미확인 ({meta['provenance']}) "
              "- 화면에 경고가 표시됩니다")
    return gj


# ---------------------------------------------------------------- main

def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)

    population, name_by_code = prepare_population()
    parks, park_labels = prepare_parks()
    history = prepare_village_history()
    boundary = prepare_boundary(name_by_code)

    def write(name: str, obj) -> None:
        path = DERIVED / name
        # 좌표 덩어리는 사람이 읽을 게 아니므로 압축해서 쓴다
        indent = None if name.endswith(".geojson") else 2
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n",
                        encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size:,} bytes)")

    print("PASS: 검증 통과. derived/ 생성:")
    write("population.json", {
        "generated_at": date.today().isoformat(),
        "periods": MOIS_PERIODS,
        "records": population,
    })
    write("parks.json", {"column_labels": park_labels, "parks": parks})
    write("village_history.json", history)
    write("eupmyeon.geojson", boundary)

    print(f"\n  인구 {len(population)}행 / 공원 {len(parks)}건 / "
          f"행정리 {history['row_count']}행 "
          f"(합계불일치 {history['sum_mismatch_count']}행, "
          f"중복키 {history['duplicate_key_count']}개)")


if __name__ == "__main__":
    main()
