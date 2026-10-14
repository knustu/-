# 군위군 생활불편 민원 기반 시설관리 우선지역 분석

군위군 8개 읍·면의 생활불편 민원과 공공시설 정보를 결합해 시설관리 우선지역을
도출하는 것이 목표다. 현재는 **민원 원자료를 확보하지 못해 인구·고령화율까지만
지도에 표시**하며, 민원 관련 지표는 "미확보"로 비활성 표시한다.

화면의 모든 숫자는 실제 공식 자료에서 나온 값이다. 샘플값이나 임의 생성값은 없다.

## 실행

```bash
npm ci                    # wrangler 하나
pip install -r requirements.txt

npm run prepare-data      # data/raw -> data/derived  (검증)
npm run dev               # 빌드 후 http://127.0.0.1:8787
```

| 명령 | 하는 일 |
|---|---|
| `npm run prepare-data` | 원자료 검증·정제 → `data/derived/` |
| `npm run build` | `data/derived/` → `public/data/` |
| `npm test` | 검증 로직이 살아 있는지 확인 |
| `npm run deploy` | 빌드 후 Cloudflare 배포 |

`deploy` 와 `dev` 에 빌드가 붙어 있어 **빌드를 깜빡할 수 없다.** 원자료가 바뀌면
`prepare-data` 를 다시 돌린다.

## 데이터 흐름

```
[다운로드]  tools/add_source.py
     ↓
data/raw/          받은 그대로. 동결. _meta.json 에 출처·수집일·sha256
     ↓             tools/prepare.py   <- assert 검증 관문
data/derived/      정제·검증 통과분                커밋 O   공개 X
     ↓             tools/build.py     <- 공개 결정 지점
public/data/       화면용                          커밋 X   공개 O
     ↓
public/index.html  브라우저가 런타임에 fetch 해서 region_code 로 조인
```

HTML 에는 데이터가 박히지 않는다. 빈 껍데기를 받고 브라우저가 JSON 을 가져와
Leaflet 으로 그린다.

## 폴더

```
data/sources.json    출처 레지스트리 — 유일한 진실. public/data/sources.json 이 여기서 생성된다
data/raw/            원자료 + _meta.json(출처 카드) + capture.html(원본 페이지 증빙)
data/derived/        prepare.py 출력
tools/               add_source.py / prepare.py / build.py / tests
public/              배포되는 폴더. "여기 넣은 건 공개"
docs/methodology.md  산식 근거. 공식 기준과 프로젝트 파생지표의 구분
```

## 지금 지도에서 보이는 것

**표시됨** — 읍면 8개 고령화율 코로플레스 / 총인구 / 4개 시점 전환
(2023-12, 2024-12, 2025-12, 2026-08) / 도시공원 3건 마커 / 읍면 순위·상세 /
데이터 출처 패널

**비활성(원자료 미확보)** — 민원발생률 · 반복민원율 · 처리지연율 ·
시설관리 필요도 · 종합 우선순위

## 알려진 과제

1. **경계 GeoJSON 출처 미확인** — 지도 전체가 출처 기록 없는 파일 위에 있다.
   SGIS 에서 재취득해 대조할 것. 화면에 경고 배너가 뜬다. → `CLAUDE.md`
2. **민원 건별 원자료 요청 미발송** — 군청 자료요청이 아직 발송되지 않았다.
   이게 들어오면 3개 지표가 한꺼번에 풀린다. → `data/sources.json`
3. **종합 우선순위 가중치 근거 없음** → `docs/methodology.md`

## 이 저장소를 새로 판 이유

기존 두 저장소(`gunwi-knu/gunwi-civic-map`, `dohun3540-crypto/deltalab`)는
배포 폴더가 소스이자 산출물이어서 데이터 생성 단계가 들어갈 자리가 없었다.
그 결과 원자료를 정성껏 정리해도 웹에 반영되지 않았고, 출처 레지스트리와
웹 사본이 15개 항목 전부 어긋났다. 이 저장소는 `raw → derived → public` 을
분리해 그 단절을 없앤 것이다.

옛 저장소에서 계승한 것: 검증 assert 로직, 원본 페이지 캡처, 함정 목록,
출처 스키마. 버린 것: 샘플 지표값, 손으로 옮겨 적던 웹 사본, 워크플로 5개,
문서 7개, 실행 불가 빌드 스크립트.

## 추가 수집 자료와 출처

기존 수집 저장소의 모든 파일과 커밋 이력을 이 저장소로 통합했다.

- [기존 시설·소방·도로·공개민원 자료 안내](FACILITY_DATA_README.md)
- [추가 8개 공공시설 분야 조사](docs/facility-data-survey.md)
- [CLAUDE.md 기준 정리·출처 점검 보고서](docs/claude-compliance-report.md)
- [전체 공식 출처 레지스트리](data/sources.json)
- [이관 파일별 출처·해시](data/gunwi/_meta.json)
- [공유용 압축파일](downloads/)

새 정제자료는 실제 자료 기준일이 2025년 이후인 행만 사용한다. 원본 증빙에
구자료가 섞여 있으면 동결 원본은 보존하고 정제 단계에서 제외한다. 기존 앱의
과거 인구·민원 원본은 삭제하지 않는다. 시설 위치자료는 `prepare-data`가
`data/derived/additional_facilities.*`로 생성한다. 지도 표시는 현재 공원 3건이며,
추가 시설 지도 연동과 민원 지표 산출은 별도 작업이다.

## 공유용 폴더

[군위군 공유자료 ZIP](downloads/군위군_공유자료.zip)을 압축 해제하면 `군위군` 폴더가 생긴다.
점검 보고서·추가 8개 분야 CSV/GeoJSON·동결 원본·전체 출처를 포함한다.
Google Drive에서는 폴더를 업로드한 뒤 `공유 → 링크가 있는 모든 사용자 → 뷰어`로
설정해 폴더 링크를 공유할 수 있다. Drive 업로드와 공유 권한 설정은 아직 실행하지 않았다.
