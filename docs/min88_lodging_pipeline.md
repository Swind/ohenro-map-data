# min88 住宿資料管線

此管線將 `min88.jp` 日文住宿列表與詳細頁保存為可重播 archive，再離線產生
provider-specific Raw 與 `Min88LodgingV1` JSONL。詳細 schema 與保守解析規則見
`reference/min88-lodging-parser-standardization-plan.md`。

## Requirements

- Python 3.10+
- BeautifulSoup（現有專案 dependency）
- 網路只用於 crawl 與可選的 Google Maps enrichment

## Full Run

```bash
python3 -m min88_lodging crawl-all
python3 -m min88_lodging parse
python3 -m min88_lodging normalize
python3 -m min88_lodging geocode       # optional, uses network/cache
python3 -m min88_lodging verify
python3 -m min88_lodging report
```

預設 archive 是 `source/min88-lodging/`，產出是
`output/min88-lodging/{raw,v1,v1-geocoded}.jsonl` 與 `report.json`。相同 archive 的
parse 是 deterministic；archive 與 manifest 都不變時，normalize 與 report 亦為
byte-stable。retrieval metadata 以 manifest 為準，normalize 會把每頁 retrieval time 寫入
`source.retrieved_at`。

資料流如下；crawl/geocode 會連網，其餘步驟離線：

```text
list_ja HTML -> index.json -> records/<post-id>/page.html
                              -> raw.jsonl -> v1.jsonl -> optional v1-geocoded.jsonl
```

## Crawl Operations

```bash
python3 -m min88_lodging crawl-index
python3 -m min88_lodging crawl-details
python3 -m min88_lodging crawl-details --force
```

三個 crawl command 都支援 `--data-dir`、`--timeout`、`--delay`、`--force`；預設為
`source/min88-lodging/`、30 秒、0.3 秒、非 force。crawler 是單 worker，每個 request
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

`parse` 的預設 output 是 `output/min88-lodging/raw.jsonl`。`normalize` 與 `geocode` 可傳
positional input，預設分別為 `raw.jsonl`、`v1.jsonl`，並以 `--output` 改寫目的地。
`geocode` cache 預設為 `<data-dir>/google-maps/`，另支援 `--cache-dir`、`--timeout 30`、
`--delay 0.3`、`--force`。`verify`/`report` 以 `--output-dir` 指定 generated outputs；只有
`report` 另有 `--output` 可改 report 路徑。

## Verification And Reports

`verify` 完全離線檢查 index/manifest hashes、ID/URL/order、四縣、detail canonical
ID、crawl status accounting、Raw/V1 counts、JSONL 與 resolved coordinate provenance。
`report` 彙整縣別/類型/狀態、source field coverage、normalization coverage、map
status、warning examples、缺頁及 index drift。

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
python3 -m unittest discover min88_lodging/tests
python3 -m unittest discover henroyado/tests
```

Base V1 不含推測座標。Geocode 只接受 Google single-place record 或 resolved
`!8m2!3d...!4d...` marker，且結果必須位於四國 bounds；viewport 與 Street View
camera coordinates 不會使用。圖片只保存 URL，不下載 binary。
