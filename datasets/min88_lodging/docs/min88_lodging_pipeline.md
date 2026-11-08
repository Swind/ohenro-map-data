# min88 住宿資料管線

此管線將 `min88.jp` 日文住宿列表與詳細頁保存為可重播 archive，再離線產生
provider-specific Raw 與 `Min88LodgingV1` JSONL。詳細 schema 與保守解析規則見
`datasets/min88_lodging/docs/min88-lodging-parser-standardization-plan.md`。

## Requirements

- Python 3.10+
- BeautifulSoup（現有專案 dependency）
- 網路用於列表/詳細頁 refresh 與 Google Maps enrichment；`run --local` 完全離線
- `tippecanoe`（或 Docker image `ohenro-elevation-visuals:latest`）與 `pmtiles` / `go-pmtiles`

## Full Run

```bash
python3 -m datasets.min88_lodging                 # refresh list/details, build all outputs and PMTiles
python3 -m datasets.min88_lodging fetch           # refresh complete primary source only
python3 -m datasets.min88_lodging build           # local source; reuse/fill Google response cache
python3 -m datasets.min88_lodging run --local     # local source and cached Google responses only
python3 -m datasets.min88_lodging run --force     # rebuild even when final hashes match
python3 -m datasets.min88_lodging validate        # source/cache/output hashes, schema, accounting, tiles
```

預設 archive 是 `datasets/min88_lodging/raw/`，完整抓取通過後才發布至
`raw/snapshots/<content-sha256>/`，並最後 atomic 更新 `raw/current.json`。每次正常 run
都重新下載列表與所有詳細頁，不把 resume cache 當成 refresh。任一失敗或不完整頁面均不會
取代目前 snapshot；舊 snapshot 保留。既有 flat archive 亦可用於 build / local run。

所有命令支援 `--raw-dir`、`--output-dir`、`--reports-dir`、`--cache-dir`、`--timeout`、
`--delay`；`--local` 只適用 run，`--force` 只適用 run/build。完整 pipeline 用 source-local
nonblocking `.pipeline.lock` 排除重複更新；低階 legacy commands 仍保留供手動操作。

完整產出為 `output/{raw,v1,v1-geocoded}.jsonl`、`map.geojson`、`report.json`、
`shikoku-min88-lodging.pmtiles`。PMTiles 使用 `lodging` layer、z6–14 與
`min88 lodging data © min88.jp` attribution。所有產出先在暫存目錄驗證，再逐檔 atomic
發布，最後寫 `reports/pipeline.json`，含原始頁/Google cache hashes、程式/settings、
coverage/warning accounting 與每個 final output hash。相同來源/config/cache/final hashes
會略過重建；修改或遺失任一 output 會重建。partial source/geocode/build failure 不發布產出。

完整 pipeline 的 derived records 不放 retrieval timestamp（`source.retrieved_at=null`）；
真實 HTTP retrieval provenance 保存在 snapshot `manifest.json`。正常保守 normalizer warnings
仍保留並逐項統計，不因 ambiguous price 等合法來源文字拒絕整批資料。Google fetch failure
則屬不完整 enrichment，不能發布；place-not-found/ambiguous/outside-Shikoku 保留原狀態，
不捏造座標。cache 在 `raw/google-maps/` 以單一 atomic JSON 保存 response HTML、request/final
URL（亦可讀取並遷移既有 `.html` + `.url` cache）；local run 缺 cache 會失敗而不連網。
`parse`／`normalize`／`verify`／`report` 的 `--data-dir` 若含 current selector，
會先解析並驗證所選 snapshot，不再誤讀過時的平面 archive。

```text
list_ja HTML -> complete detail snapshot -> raw.jsonl -> v1.jsonl
  -> cached Google single-place enrichment -> v1-geocoded.jsonl -> map.geojson -> PMTiles
```

## Crawl Operations

```bash
python3 -m datasets.min88_lodging crawl-index
python3 -m datasets.min88_lodging crawl-details
python3 -m datasets.min88_lodging crawl-details --force
```

三個 crawl command 都支援 `--data-dir`、`--timeout`、`--delay`、`--force`；預設為
`datasets/min88_lodging/raw/`、30 秒、0.3 秒、非 force。crawler 是單 worker，每個 request
最多 3 次；network error、429 與 5xx 使用有限 exponential backoff。

`crawl-index` 驗證既有 `index/page.html` 後預設直接重用，否則下載列表，再寫入
deterministic `index.json` 與 `manifest.json`。`crawl-details` 只依 `index.json`，逐筆保存
`records/<post-id>/page.html`；既有頁通過 canonical post ID 與 `h1#post_title` 驗證時跳過，
`--force` 才嘗試更新。單筆失敗會繼續；atomic write 不會讓失敗 response 覆蓋有效頁。

`manifest.json` 是 retrieval ledger，不是 parser output。它保存 schema/parser version、
列表與每張 detail 的 URL、local path、status、HTTP/retrieval metadata、SHA-256，以及 index
縣別/札所/狀態 counts 和 `fetched + skipped + failed` summary。resume 時保留原
`retrieved_at`；若 refresh 失敗而已有有效 archive，舊成功項目與 hash 保留，最新失敗記在
`latest_fetch`。列表 records 改變時，前一版保存在 `previous_index_records` 供 report drift。

## Offline Parse Compatibility

`parse` 按 `index.json` source order 讀 archive，不讀 live 網站。新版頁優先解析
`.min88-basicdata-pack > textarea.min88-basicdata-kv` 的 key/value；沒有 textarea 時，亦支援
舊版「基本情報」heading 後的 table（住所、TEL、駐車場、部屋数、料金、HP、IN、OUT、
WiFi、ランドリー、支払い方法）。缺欄、unknown/duplicate key、名稱差異與不安全格式保留
raw value 並記 warning，不從 editorial prose 猜設施；圖片只保存 URL，不下載 binary。

`parse` 的預設 output 是 `datasets/min88_lodging/output/raw.jsonl`。`normalize` 與 `geocode` 可傳
positional input，預設分別為 `raw.jsonl`、`v1.jsonl`，並以 `--output` 改寫目的地。
`geocode` cache 預設為 `<data-dir>/google-maps/`，另支援 `--cache-dir`、`--timeout 30`、
`--delay 0.3`、`--force`。`verify`/`report` 以 `--output-dir` 指定 generated outputs；只有
`report` 另有 `--output` 可改 report 路徑。

## Verification And Reports

`verify` 完全離線檢查 index/manifest hashes、ID/URL/order、四縣、detail canonical
ID、crawl status accounting、Raw/V1 counts、JSONL 與 resolved coordinate provenance。
`report` 彙整縣別/類型/狀態、source field coverage、normalization coverage、map
status、warning examples、缺頁及 index drift。

## 2026-11-09 One-command Update

- 正常一鍵更新及獨立 validate/verify 通過：654 records/detail pages。
- 德島 124／高知 240／愛媛 185／香川 105；646 resolved map features、
  5 place_not_found、3 source_data_incomplete，0 geocode fetch errors。
- 112 warnings：94 UNRECOGNIZED_FORMAT、10 SOURCE_NAME_MISMATCH、
  3 MISSING_REQUIRED_FIELD、5 GOOGLE_MAPS_PLACE_NOT_FOUND；來源原文全保留。
- 60 tests 通過；同一 source/config/cache 下重跑不更動產出與報告。

## 2026-08-19 Live Archive

- 650 list records，650 張 detail 均可解析；tokushima 124 / kochi 239 / ehime 182 /
  kagawa 105。
- Raw 與 V1 各 650 筆；647 筆有 structured basic data，3 筆 source page 無可解析 textarea/table
  basic data（source IDs `25590`、`780`、`25646`）。
- `verify: OK`；missing detail 0、unknown basic-data key 0、unknown taxonomy 0。
- 共 98 warnings：3 `MISSING_REQUIRED_FIELD`、10 `SOURCE_NAME_MISMATCH`、85
  `UNRECOGNIZED_FORMAT`。後者是刻意保守拒絕推斷：60 個空白/不完整或 ambiguous price
  item、13 個 laundry 附註/空 keyed value、7 個 payment 空值/不完整值、4 個 malformed
  route distance、1 個 partial Wi-Fi 狀態；所有原文仍在 output。
- Optional geocode 尚未執行；base V1 為 647 `pending_geocode`、3
  `source_data_incomplete`，report 的 `geocoded_records` 為 0。不要把 base report 的
  `mapped: 650` 誤讀為已 geocode：沒有 enriched file 時 report 以 V1 作 mapped fallback。

```bash
python3 -m unittest discover datasets/min88_lodging/tests
python3 -m unittest discover datasets/henroyado/tests
```

Base V1 不含推測座標。Geocode 只接受 Google single-place record 或 resolved
`!8m2!3d...!4d...` marker，且結果必須位於四國 bounds；viewport 與 Street View
camera coordinates 不會使用。圖片只保存 URL，不下載 binary。

`export-map` 只輸出 `map_data_status=resolved` 的住宿為精簡 GeoJSON，供
`map-preview` 的 `VITE_MIN88_LODGING_URL` 載入；未 geocode 或無可靠座標的 record 會略過。
2026-08-19 archive 實際輸出 640 個 map features（另有 7 筆找不到單一 Google place、
3 筆來源資料不足）。
