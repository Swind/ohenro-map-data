# min88 住宿資料擷取與標準化實作計畫

## 1. 目標

從「みんなのへんろ（宿）」日文住宿列表與詳細頁建立一條可重跑、可驗證、保留來源資料的離線管線：

```text
https://min88.jp/inn/list_ja/
        |
        v
列表 HTML snapshot -> index.json -> 詳細頁 HTML archive
                                      |
                                      v
                                  RawLodging JSONL
                                      |
                                      v
                               Min88LodgingV1 JSONL
                                      |
                                      v
                         optional Google Maps enrichment
```

第一階段的目標是建立獨立的 min88 provider dataset，不是立即與 Henroyado 或 OSM 合併。

核心原則：

1. HTML 是可重播的主要來源，解析器不依賴網站保持在線。
2. DOM extraction 與 semantic normalization 分離。
3. 所有正規化欄位保留原始文字與來源 URL。
4. 無法安全判斷時保留 `null` 並記 warning，不猜測。
5. 單一住宿或欄位失敗不得中止全量處理。
6. 座標只接受可證明為 place 的位置，不把 map viewport 或 Street View 相機位置當住宿座標。

## 2. 本次網站分析結果

分析日期：2026-08-19。

### 2.1 網站與 crawl topology

- 網站是 WordPress，`robots.txt` 只禁止 `/wp-admin/`，沒有禁止住宿列表或詳細頁。
- 日文列表是單一頁面：`https://min88.jp/inn/list_ja/`。
- 沒有 pagination、`rel=next`、`/page/N/` 或 load-more。
- 頁面依四縣排列，anchor 分別為 `#tokushima`、`#kochi`、`#ehime`、`#kagawa`。
- 頁面有完整 88 個札所 header，數量為德島 23、高知 16、愛媛 27、香川 22。
- 列表中觀察到 651 個住宿連結 occurrence、650 個 distinct numeric post ID。
- 唯一重複 ID 是 `13232`，第二個 occurrence 是空文字 anchor，應排除。
- 詳細頁 canonical URL 是 `https://min88.jp/inn/<post-id>/`，數字就是穩定 WordPress post ID。
- WordPress REST 目前共有 2,142 posts，但混合日、英、中頁面及其他文章，不能代替日文住宿列表的 membership。

目前四縣列表觀察值：

| Prefecture | Unique lodging IDs | Temple headers | `休業･閉業` markers |
|---|---:|---:|---:|
| Tokushima | 124 | 23 | 13 |
| Kochi | 239 | 16 | 21 |
| Ehime | 182 | 27 | 13 |
| Kagawa | 105 | 22 | 8 |
| Total | 650 | 88 | 55 |

這些數字只作首次 crawl baseline 與 drift report，不應永久 hard-code 成 parser 條件。每次 crawl 的一致性應以當次 `index.json` 為準。

### 2.2 列表頁結構

主要內容位於：

```css
#article > .post_content
```

札所 header：

```html
<div class="icon-with-text">
  <img data-src=".../02.png">
  <div class="icon-with-text-text">
    <p>極楽寺</p>
    <small>鳴門市大麻町</small>
  </div>
</div>
```

札所號碼通常只存在 icon filename `01.png` 至 `88.png`；名稱與所在地是文字。住宿主要是 paragraph 中的 numeric detail link：

```html
<p class="wp-block-paragraph">
  ┗ 《休業･閉業》<a href="https://min88.jp/inn/76/">極楽寺（宿坊）</a>
</p>
```

另有 20 筆 online booking variant：

```html
<div class="route-inn-row">
  <span class="route-distance">⬇ 7.0km</span>
  <a class="route-online-inn" href="https://min88.jp/inn/132/">
    <span class="route-online-badge">24時間受付</span>
    <span class="route-inn-name">Guest House チャンネルカン</span>
  </a>
</div>
```

列表頁的主要風險：

- 一個 paragraph 可能以 `<br>` 放多筆住宿、距離與區間總長。
- 札所與 route segment 沒有完整 wrapper，只能依 DOM 順序保存 context。
- `《休業･閉業》` 合併了休業與閉業，不能映射成明確的 temporary/permanent status。
- 頁面混有大量 `script`、`style`、廣告及 malformed nested HTML。
- lazy-loaded resource 的真實 URL 常在 `data-src`，`src` 可能只是 base64 placeholder。

### 2.3 詳細頁的可靠資料

以 `https://min88.jp/inn/85/` 為樣本：

- 名稱：`h1#post_title`。
- post ID：canonical URL、REST endpoint 及 shortlink 都是 `85`。
- 最後更新時間：頁面顯示 2026-06-20，REST `modified` 也是 `2026-06-20T10:14:50`。
- 分類：札所 `03 金泉寺`、縣別 `徳島`、住宿種類 `民宿･ゲストハウス`。
- 日、英、中 alternate IDs：`85`、`11726`、`30094`。
- featured image：public HTML 的 `og:image` 與 `#post_image img.wp-post-image`。

最重要的資料不是 JavaScript 產生後的可見區塊，而是 HTML 中的 hidden textarea：

```html
<textarea class="min88-basicdata-kv" aria-hidden="true">
address   = 徳島県板野郡板野町吹田平山93-11
tel       = 088-672-6171
website   = http://michishirube-yado.com/index.htm
parking   = 6台　無料（予約不要）
rooms     = 6室
price     = 素泊り：個室4,200円、ドミトリー2,625円|朝食付：+525円|夕食付：+1,050円|２食付：+1,575円
checkin   = 16:00～21:00
checkout  = 9:00前
wifi      = 未確認
laundry   = 洗濯機：未確認|乾燥機：未確認
payment   = 現金：可|クレジットカード：可|電子マネー：未確認
</textarea>
```

Selector：

```css
.min88-basicdata-pack > textarea.min88-basicdata-kv
```

解析規則：

- 每個非註解行以第一個 `=` 分成 key/value。
- key/value trim，但 raw value 完整保留。
- `|` 是來源使用的子項目 delimiter，不等於一般文字的 pipe。
- `#` 開頭是 template/comment，例如 `#emoney`，保存於 ignored lines，不當成有效住宿資料。
- 未知 key 不丟棄，存入 `extra_fields` 並記 warning。
- `.min88-basicdata-out` 在 raw HTML 中是空的，不應依賴 JavaScript-rendered DOM。

詳細頁另有結構化路線：

```html
<div id="route-lines">
  <div class="route-line"
       data-lnum="03" data-lname="金泉寺" data-lkm="1.2"
       data-rnum="04" data-rname="大日寺" data-rkm="5.3"></div>
</div>
```

應直接解析 `#route-lines .route-line` 的 `data-*`，不要解析 JavaScript 畫出的圖。

補充設施位於：

```css
h3#補足情報 + ul.wp-block-list > li
```

編輯介紹可從 `.min88-inn-intro__title` 與 `.min88-inn-intro__text` 保存為 editorial description，但不能用自然語言推導未出現在 basic data 的設施。

應排除：

- 廣告、affiliate/booking widget 與 `min88.official.ec` iframe。
- AI 產生的外部 review 摘要。
- analytics、share、click logging 及表單內容。
- header/footer/logo/language icon/basic-data icon。
- `（まだありません）` placeholder gallery。

### 2.4 Google Maps 判讀

樣本有兩個 `iframe[data-src]`：

1. Street View embed，含 panorama camera position `34.1527816, 134.4650229`。
2. Place/map embed，`pb=` 含 place token `0x35537411d96a5073:0x73fb3549162e85a0`，也含 viewport center `34.1525290, 134.4300063`。

兩組座標差距明顯，證明不能直接從 `pb` 中取任一 `!2d/!3d` 作住宿座標。

正確策略與目前 Henroyado geocode 一致：

- Raw 階段保存 place embed、Street View embed、walking directions URL。
- Base V1 使用來源地址，但 `coordinates` 保持 `null`。
- Optional enrichment 抓取 Google place embed response，僅接受 response 中的單一 place record 或 resolved URL 的 `!8m2!3d...!4d...` marker。
- 找不到 place 時，可以住宿名稱加來源地址建立 Google Maps search request，再使用同一 place-record parser；request URL 必須記錄並快取。
- 永不使用 viewport center 或 Street View camera position作住宿座標。
- 結果必須通過四國 bounds 檢查。

## 3. 範圍

### 3.1 Phase 1 包含

- 抓取與保存日文列表 HTML。
- 從列表建立 deterministic `index.json`。
- 抓取並保存每個日文住宿詳細頁 HTML。
- resume、retry、rate limit、atomic write 與 `--force`。
- 離線 HTML extraction 到 provider-specific Raw JSONL。
- 保守正規化到 `Min88LodgingV1` JSONL。
- 保存來源地址、聯絡方式、房間、價格、時間、付款、停車、設施、札所路線、圖片 URL 與語言 alternate URL。
- Optional Google Maps place enrichment。
- manifest、verify、report、fixtures 與 tests。

### 3.2 Phase 1 不包含

- 不下載圖片 binary。
- 不抓英語與中文詳細頁；只保存 alternate URL/ID。
- 不處理預約、捐款、電話 click tracking 或表單。
- 不把 AI review 當來源事實。
- 不與 Henroyado/OSM 去重或合併。
- 不做名稱 fuzzy matching、地址修正或外部資料補正。
- 不建立 app SQLite、GeoJSON、PMTiles 或 UI。
- 不建立通用 crawler framework；只抽出第二個 provider 已實際共用的純函式。

## 4. 建議目錄與 CLI

```text
min88_lodging/
├── __main__.py
├── cli/
├── crawler/
├── html_parser/
├── model/
├── normalize/
├── geocode.py
└── tests/
    └── fixtures/

source/min88-lodging/
├── index/
│   └── page.html
├── records/
│   └── <post-id>/
│       └── page.html
├── google-maps/
│   └── <sha256>.html
├── index.json
└── manifest.json

output/min88-lodging/
├── raw.jsonl
├── v1.jsonl
├── v1-geocoded.jsonl
└── report.json
```

實作時將 `source/min88-lodging/` 與 Google Maps cache 加入 `.gitignore`；程式、fixtures 與計畫文件進版控。`output/min88-lodging/` 是否進版控依全量檔案大小與既有 output policy 決定，不在 crawler 內硬編碼。

建議 CLI：

```bash
python3 -m min88_lodging crawl-index
python3 -m min88_lodging crawl-details
python3 -m min88_lodging crawl-all
python3 -m min88_lodging parse
python3 -m min88_lodging normalize
python3 -m min88_lodging geocode
python3 -m min88_lodging verify
python3 -m min88_lodging report
```

共同參數：

```text
--data-dir source/min88-lodging
--output <path>
--timeout 30
--delay 0.3
--force
```

第一版使用 Python stdlib `urllib`、`json`、`hashlib`、`dataclasses` 與現有 BeautifulSoup dependency，不新增 HTTP/crawler framework。

## 5. Crawl 設計

### 5.1 `crawl-index`

1. GET `https://min88.jp/inn/list_ja/`。
2. 驗證 HTTP 200、body 非空、canonical/list content 存在。
3. atomic write 到 `index/page.html`。
4. 僅在四縣 anchor 範圍與 `#article > .post_content` 解析 link。
5. detail URL 必須符合 `^https://min88\.jp/inn/([0-9]+)/?$`。
6. 排除 normalized anchor text 為空的 link。
7. 依 post ID 去重，但保存 occurrence 與 source order 供診斷。
8. 產生 deterministic `index.json`，不放 crawl timestamp；時間與 HTTP metadata 放 `manifest.json`。

`index.json` record 建議欄位：

```json
{
  "source_id": "85",
  "source_url": "https://min88.jp/inn/85/",
  "name": "旅人の宿・道しるべ",
  "prefecture": "tokushima",
  "list_order": 12,
  "temple_context": {
    "number": 3,
    "name": "金泉寺",
    "locality": "板野郡板野町"
  },
  "distance_text": "⬇ 1.2km",
  "closure_marker": null,
  "online_booking": false,
  "online_booking_label": null
}
```

列表的 `temple_context` 與距離只代表 source presentation context；詳細頁 `route-line` 才是路線正規化的優先來源。

### 5.2 `crawl-details`

- 只讀 `index.json`，不重新解析 live list。
- 每筆保存 `records/<post-id>/page.html`。
- 已存在且基本驗證成功時跳過；`--force` 才重抓。
- 預設單 worker 與 0.3 秒 request delay；先求穩定及降低站方負載，不先做 concurrency。
- 對 timeout、429、5xx 做有限次 exponential backoff；404 記錄但不重試到無限。
- HTTP body 先寫 `.tmp`，flush/fsync 後 `os.replace()`，失敗不覆蓋既有有效檔。
- 每頁驗證 canonical post ID 與要求的 ID 相同，且存在 `h1#post_title`。
- redirect 到其他 post、登入頁或錯誤頁視為失敗。
- 所有錯誤寫 manifest，繼續下一筆。

### 5.3 REST API 的角色

public HTML 是 primary archive。REST API 只用於 verify 或診斷：

```text
GET /inn/wp-json/wp/v2/pages/15767
GET /inn/wp-json/wp/v2/posts/<id>?_fields=id,link,modified,title,categories,category2,featured_media
```

理由：REST 可提供穩定 modified/taxonomy/media ID，且 `content.rendered` 保留 hidden textarea；但 featured image URL、head metadata 與 theme output 不完整。Phase 1 不應為每筆強制多發一次 REST request。

## 6. Raw extraction

### 6.1 Raw record

`RawMin88Lodging` 應貼近網站表示，不在這一步解讀 `可`、`未確認`、價格或時間：

```json
{
  "source_context": {
    "source_id": "85",
    "source_url": "https://min88.jp/inn/85/",
    "list_name": "旅人の宿・道しるべ",
    "prefecture": "tokushima",
    "list_order": 12,
    "temple_context": {},
    "distance_text": "...",
    "closure_marker": null,
    "online_booking_label": null
  },
  "name": "旅人の宿・道しるべ",
  "modified_text": "最終更新日：2026年6月20日",
  "categories": ["03 金泉寺", "徳島"],
  "lodging_types": ["民宿･ゲストハウス"],
  "route_lines": [],
  "basic_data": {
    "address": "...",
    "tel": "...",
    "website": "...",
    "parking": "...",
    "rooms": "...",
    "price": "...",
    "checkin": "...",
    "checkout": "...",
    "wifi": "...",
    "laundry": "...",
    "payment": "..."
  },
  "basic_data_ignored_lines": [],
  "extra_fields": [],
  "supplemental_facilities": [],
  "editorial_title": null,
  "editorial_description": null,
  "featured_image_url": null,
  "gallery_image_urls": [],
  "google_maps_place_embed_url": null,
  "google_street_view_embed_url": null,
  "google_maps_directions_url": null,
  "alternate_languages": [],
  "parser_warnings": []
}
```

### 6.2 Extraction invariants

- Missing scalar 一律 `null`，missing collection 一律 `[]`。
- DOM/source order 必須保留。
- URL 用 `urljoin(source_url, value)` 轉 absolute URL。
- 所有文字保留 `<br>` 為換行，其餘 whitespace 收斂。
- hidden textarea 可有 duplicate key；不得靜默覆蓋，保留全部 occurrence 並 warning。
- 詳細頁名稱、post ID 與 list record 不一致時保留兩者並 warning。
- unknown basic-data key 與未知 section 不丟棄。
- featured image 優先 `og:image` 原圖；保留 rendered derivative 為 original/display metadata，不抓 binary。

## 7. `Min88LodgingV1` schema

欄位名稱盡量與 `HenroyadoInnV1` 對齊，讓未來 reconciliation 較簡單；但 provider-specific `raw` 不強塞入 Henroyado model。

```json
{
  "schema_version": 1,
  "source": {
    "provider": "min88",
    "source_id": "85",
    "source_url": "https://min88.jp/inn/85/",
    "list_url": "https://min88.jp/inn/list_ja/",
    "retrieved_at": "2026-08-19T00:00:00Z",
    "source_modified_at": "2026-06-20"
  },
  "identity": {
    "name": "旅人の宿・道しるべ",
    "name_kana": null
  },
  "business_status": null,
  "description": {
    "title": null,
    "text": null,
    "provenance": "min88_editorial"
  },
  "henro": {
    "previous_temple": {"number": 3, "name": "金泉寺", "distance_km": 1.2},
    "next_temple": {"number": 4, "name": "大日寺", "distance_km": 5.3},
    "raw_route_data": []
  },
  "lodging_types": ["guesthouse"],
  "rooms": {
    "types": [],
    "room_count": 6,
    "raw_text": "6室"
  },
  "pricing": {
    "items": [],
    "raw_text": "..."
  },
  "check_in": {
    "time": "16:00-21:00",
    "start": "16:00",
    "end": "21:00",
    "notes": null,
    "raw_text": "16:00～21:00"
  },
  "check_out": {
    "time": "09:00",
    "start": null,
    "end": "09:00",
    "notes": "before",
    "raw_text": "9:00前"
  },
  "parking": {},
  "facilities": [],
  "payment": {},
  "contact": {},
  "location": {},
  "images": [],
  "alternate_languages": [],
  "raw": {},
  "_warnings": []
}
```

### 7.1 正規化規則

#### Status

- list 無 marker：`business_status = null`，不代表營業中。
- `《休業･閉業》`：`business_status = "closed_or_suspended"`。
- 不自行拆成 temporary/permanent；原文保留於 `raw.status`。
- online booking unavailable 不是營業狀態。

#### Temple route

- 優先解析 detail `route-line data-*`。
- temple number 去 leading zero 後轉 integer。
- distance 只接受純 decimal km；失敗保留 raw 並 warning。
- list temple context 只作 fallback，且必須標示 provenance。

#### Rooms and lodging type

- `6室` 可安全轉 `room_count = 6`。
- 房型只從明確 raw price/room text 或 taxonomy 建立，不從 editorial prose 推導。
- 先建立 min88 taxonomy mapping table，未知 term 保留原文並 warning。

#### Time

- 重用 Henroyado 已測試的全形數字、colon、range parser。
- 增加 min88-specific `前`/`まで` 語義，例如 `9:00前` 是 end/deadline，不是 check-out start。
- 解析結果永遠保留 `raw_text`。

#### Tri-state facilities

`可`、`不可`、`未確認` 與欄位缺失不能混為一談：

```text
可       -> available
不可     -> unavailable
未確認   -> unknown
欄位缺失 -> not_provided
```

適用於 Wi-Fi、洗衣機、乾燥機、現金、信用卡、電子支付等。補足情報 list 只表示 source 宣稱 available，不反推缺少的項目 unavailable。

#### Parking

保留 raw text，僅解析明確項目：space count、fee status、reservation requirement。未知文字放 notes。

#### Pricing

- 先以 `|` 拆 source item，再保存每個 raw item。
- 只在明確 `N円` 時抽 integer `amount_yen`，移除 comma/full-width digit。
- `+525円` 標成 surcharge，不算完整住宿價格。
- 個室/ドミトリー、素泊り/朝食付/夕食付/２食付只使用明確詞彙 mapping。
- 不推斷 per-person、tax included、日期或 season；來源沒寫就 `null`。
- 一行含多個價格時可拆多 item，但任何 ambiguity 都保留完整 raw item。

#### Images

- 保存原始 image URL 及去 query 的 canonical URL。
- featured 與 gallery 分開標示 role。
- 不下載 binary，不使用廣告或 generic theme image。

#### Location

Base V1：

```json
{
  "prefecture": "徳島県",
  "address": "徳島県板野郡板野町吹田平山93-11",
  "coordinates": null,
  "map_data_status": "pending_geocode",
  "google_maps_place_embed_url": "...",
  "google_street_view_embed_url": "...",
  "google_maps_directions_url": "..."
}
```

地址是 min88 source fact，可以直接使用；座標仍需獨立 provenance。

## 8. Google Maps enrichment

先把 `henroyado/geocode.py` 中與 provider 無關的最小部分抽到共用模組，保留 Henroyado 現有 tests：

- `parse_place()`。
- `is_in_shikoku()`。
- SHA-256 request cache。
- atomic enriched JSONL writer 的通用邏輯。

不要建立 crawler inheritance hierarchy 或 provider framework。min88 adapter 只負責選 request URL 與寫回自己的 location fields。

處理順序：

1. 使用來源的 Google place embed URL。
2. fetch response，解析單一 place record。
3. 若無 place record，以 `name + address` 產生明確 search URL，再走相同 embed parser。
4. 找到多筆、找不到、fetch failed 或結果在四國外，均不寫 coordinates。
5. 所有 request body 存 `source/min88-lodging/google-maps/<sha256>.html`。
6. 已有 cache 預設不重抓，`--force` 才更新。

`map_data_status`：

```text
source_data_incomplete
pending_geocode
resolved
place_not_found
place_ambiguous
place_outside_shikoku
fetch_failed
```

Resolved coordinate：

```json
{
  "latitude": 34.0,
  "longitude": 134.0,
  "source": "google_maps_embed_place"
}
```

同時保存 Google place ID、CID、正規化名稱、地址與實際 request URL。

## 9. Warning 與錯誤模型

每筆 warning：

```json
{
  "field": "pricing.items",
  "code": "UNRECOGNIZED_FORMAT",
  "message": "Could not safely normalize price item.",
  "raw_value": "..."
}
```

預計 warning code：

```text
SOURCE_ID_MISMATCH
SOURCE_NAME_MISMATCH
DUPLICATE_BASIC_DATA_KEY
UNKNOWN_BASIC_DATA_KEY
UNKNOWN_TAXONOMY
UNRECOGNIZED_FORMAT
MISSING_REQUIRED_FIELD
GOOGLE_MAPS_FETCH_FAILED
GOOGLE_MAPS_PLACE_NOT_FOUND
GOOGLE_MAPS_PLACE_AMBIGUOUS
GOOGLE_MAPS_PLACE_OUTSIDE_SHIKOKU
```

Fatal 僅限無法建立 corpus 的狀況，例如 list 無法解析、四縣 section 全缺、沒有任何 valid detail link、output 無法 atomic write。單筆 detail 404、欄位缺失或 malformed HTML 都是 record/crawl warning。

## 10. Manifest、verify 與 report

`manifest.json` 記錄：

- list URL、retrieved time、HTTP status、SHA-256。
- 當次 unique post count、prefecture/temple/status counts。
- 每個 detail URL、local path、status、retrieved time、SHA-256、error。
- parser/version identifier。

`verify` 至少檢查：

- `index/page.html` hash 與 manifest 相符。
- `index.json` source IDs unique、URL 與 ID 一致、order deterministic。
- 四縣 section 都存在，札所號碼落在 1..88。
- 每個成功 detail archive hash 正確，canonical ID 一致。
- fetched + skipped + failed 等於 index total。
- Raw count 等於可解析 detail count。
- V1 count 等於 Raw count，source ID 不重複。
- `resolved` coordinates 在四國 bounds 內且有 provenance。
- JSONL 每行是合法 JSON，output 使用 UTF-8。

`report.json` 提供：

- records by prefecture/type/status。
- source field coverage。
- room/time/price/payment/facility normalization coverage。
- map status 與 coordinate source counts。
- warning counts 與代表性 source IDs。
- list/detail name mismatch、missing page、unknown key/taxonomy。
- 與前次 baseline 的 added/removed/changed IDs；只報告 drift，不自動刪除歷史 archive。

## 11. Tests

使用現有 `unittest` 風格：

```bash
python3 -m unittest discover min88_lodging/tests
```

### 11.1 Real HTML fixtures

從 archive 擷取最小但真實的 list/detail fragment，至少涵蓋：

- `85`：完整 basic data、route、featured image、兩種 map iframe。
- 一筆 `《休業･閉業》`。
- 一筆 `.route-inn-row` online booking variant。
- 一個 paragraph 多筆住宿與 `<br>`。
- 缺 basic-data textarea 的 detail。
- unknown/duplicate basic-data key。
- `未確認`、`不可`、`前`、全形數字與多段價格。
- 有 gallery 與沒有 gallery。
- 同名不同 ID。
- alternate language 缺少其中一種。

### 11.2 Pure unit tests

- numeric detail URL 與 source ID extraction。
- list context state machine 與 empty-anchor exclusion。
- textarea first-`=` parsing、comment、`|`、duplicate key。
- room count、price、time、tri-state、parking、payment。
- taxonomy mapping。
- place/Street View iframe classification。
- Google place parsing及拒絕 viewport/Street View coordinates。
- Shikoku bounds。

### 11.3 Frozen pipeline tests

```text
index fixture + detail fixture
        -> RawMin88Lodging
        -> Min88LodgingV1
        == fixtures/expected/<source-id>.json
```

`retrieved_at` 在 fixture 中固定為 `null`，避免 nondeterministic expected output。更新 expected JSON 前必須人工 review diff。

### 11.4 Crawler I/O tests

用 stdlib mock HTTP response 測試：

- resume 不重抓有效檔。
- `--force` 更新。
- 429/5xx retry。
- 404 記錄後繼續。
- canonical mismatch 拒收。
- interrupted write 不破壞既有 archive。

## 12. 實作階段

### Step 1：Index crawler 與 detector

- 建立 package/CLI。
- 更新 `.gitignore`，排除可重建的 raw archive/cache。
- 抓取 list snapshot。
- 實作四縣、札所 context、ordinary/online link detection。
- 產生 `index.json` 與 baseline report。

完成條件：當次實站可重現約 650 distinct IDs、88 temple headers，且 ID `13232` 空 anchor 不形成第二筆 record。

### Step 2：Detail archive

- resume/retry/delay/atomic write。
- canonical validation 與 manifest。
- 完成全量日文 detail archive。

完成條件：每個 index ID 都明確落在 success 或 error，無 silent omission。

### Step 3：Raw parser

- 實作 identity/category/basic data/route/facility/image/maps/language extraction。
- unknown fields 與 parser warnings。
- 輸出 deterministic `raw.jsonl`。

完成條件：單頁錯誤不停止全量；所有 hidden textarea raw values 可在 Raw output 找回。

### Step 4：V1 normalizer

- 實作 status、route、room、time、tri-state、parking、price、payment、image normalization。
- 僅抽取已驗證的 Henroyado common helpers，保持既有 output/tests 不變。
- 輸出 `v1.jsonl` 與 report。

完成條件：Raw/V1 record count 一致，所有 structured value 有 raw provenance。

### Step 5：Google Maps enrichment

- 共用 place parser/cache。
- place embed 優先、name+address search fallback。
- 輸出 `v1-geocoded.jsonl`。

完成條件：沒有 viewport 或 Street View coordinate 被標成 lodging coordinate；所有 resolved 點在四國 bounds 內。

### Step 6：Regression 與操作文件

- real fixtures、pure tests、frozen expected、crawler I/O tests。
- `verify`、`report`。
- 更新 `AGENTS.md` 與操作文件，加入完整命令、實際 counts 與已知例外。

## 13. 最終驗收標準

- 從空的 `source/min88-lodging/` 可用 `crawl-all` 建立完整 archive。
- 離線執行 `parse`、`normalize`、`verify` 不連網。
- `index.json` 對當次 list 無漏掉 valid numeric Japanese detail link。
- 每筆 V1 有 provider、stable source ID、source URL、名稱與 raw provenance。
- basic-data unknown key 不會丟失或造成全量失敗。
- status、unknown、not-provided 語義不混用。
- Base V1 不包含猜測座標。
- Geocoded V1 只包含有 place provenance 且位於四國的座標。
- 重跑相同 archive 產生 byte-stable Raw/V1/report（retrieval metadata 除外）。
- 全部 tests 與 `verify` 通過。

## 14. 後續階段

Phase 1 穩定後再另立 reconciliation 計畫：

```text
HenroyadoInnV1 ----+
Min88LodgingV1 ----+--> canonical lodging candidates --> reviewed matches
OSM lodging -------+
```

跨 provider matching 必須使用名稱、地址、座標、電話與人工可審核 evidence；不得在 min88 crawler 內順便做模糊去重。
