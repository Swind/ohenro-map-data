Shikoku Nature Trail 爬蟲實作規劃

1. 目標

實作一個可重複執行、可增量更新、可驗證完整性的爬蟲工具，蒐集：

https://shikoku-nature-trail.com/ 四國自然步道網站的四縣 Course 資料

Course 列表頁原始 HTML

每個 Course 詳細頁原始 HTML

詳細頁中的圖片

詳細頁內嵌 Google My Maps 的 Map ID

對應 Google My Maps KML

基本索引資訊與下載 metadata

本階段的核心原則是：

先完整保存原始資料（Raw Archive），暫時不要做過度正規化、POI 合併、GIS geometry 整理或 App DB 匯入。

後續再以本階段保存的 HTML、圖片與 KML 為輸入，建立第二階段的 parser / normalization pipeline。

2. 本階段範圍

2.1 要做

發現四個縣的 Course 列表頁

解析每個列表中的 Course

保存列表中可直接取得的 metadata

下載每個 Course 詳細頁 HTML

從詳細頁找出：

Google My Maps iframe

Google My Maps mid

頁面內圖片 URL

下載圖片

使用 mid 下載 KML

保存 HTTP / checksum / crawl metadata

支援重跑、resume、incremental update

產生 crawl report，確認資料是否抓完整

2.2 暫時不要做

第一階段不要處理：

KML → GeoJSON

LineString / MultiLineString 統一

POI 座標去重

OSM 資料合併

四國遍路 route 合併

DEM / elevation profile

SQLite App schema

圖片縮圖與壓縮

內容翻譯

景點分類

自動判斷通行狀態

PMTiles

Android App 匯入

這些留到第二階段。

3. 網站資料結構

網站主要可以視為：

shikoku-nature-trail.com
│
├── 四縣 Course List
│   ├── 徳島
│   ├── 香川
│   ├── 愛媛
│   └── 高知
│
└── Course Detail
    ├── Course 說明
    ├── 特徵 / 難度等資料
    ├── 圖片
    ├── 撮影ポイント
    ├── 近隣の観光SPOT
    └── Google My Maps
        └── KML

Course 詳細頁 URL 為類似：

https://shikoku-nature-trail.com/archives/119

Google My Maps iframe 類似：

https://www.google.com/maps/d/embed?...&mid=<MAP_ID>

KML 可使用：

https://www.google.com/maps/d/kml?mid=<MAP_ID>&forcekml=1

4. 建議技術

建議使用 Rust。

4.1 主要 crate

reqwest
tokio
scraper
serde
serde_json
url
sha2
chrono
anyhow
thiserror
clap
tracing
tracing-subscriber

可選：

mime
mime_guess
uuid
indicatif

第一階段 不需要 KML parser。

目前只需要把 KML 原始檔下載保存即可。

5. 專案結構

建議：

shikoku-nature-trail-crawler/
├── Cargo.toml
├── README.md
├── src/
│   ├── main.rs
│   ├── cli.rs
│   │
│   ├── crawler/
│   │   ├── mod.rs
│   │   ├── client.rs
│   │   ├── index.rs
│   │   ├── detail.rs
│   │   ├── assets.rs
│   │   └── kml.rs
│   │
│   ├── parser/
│   │   ├── mod.rs
│   │   ├── course_list.rs
│   │   └── course_detail.rs
│   │
│   ├── model/
│   │   ├── mod.rs
│   │   ├── course.rs
│   │   ├── asset.rs
│   │   └── crawl.rs
│   │
│   ├── storage/
│   │   ├── mod.rs
│   │   ├── filesystem.rs
│   │   └── manifest.rs
│   │
│   └── report.rs
│
├── data/
│   ├── raw/
│   └── reports/
│
└── tests/
    ├── fixtures/
    └── parser/

6. Raw Data 目錄設計

推薦：

data/
└── raw/
    └── shikoku-nature-trail/
        │
        ├── indexes/
        │   ├── tokushima.html
        │   ├── kagawa.html
        │   ├── ehime.html
        │   └── kochi.html
        │
        ├── courses/
        │   ├── 119/
        │   │   ├── page.html
        │   │   ├── metadata.json
        │   │   ├── assets.json
        │   │   │
        │   │   ├── images/
        │   │   │   ├── 001.jpg
        │   │   │   ├── 002.jpg
        │   │   │   └── ...
        │   │   │
        │   │   └── map/
        │   │       ├── map.kml
        │   │       └── metadata.json
        │   │
        │   └── ...
        │
        ├── course-index.json
        ├── manifest.json
        └── crawl-state.json

Course 目錄優先使用網站原始：

post_id

例如：

/archives/119

就使用：

courses/119/

不要一開始就依賴自己生成的：

ehime-003

因為網站原始 ID 是最穩定的 source identifier。

7. Course Index

Course list 中可先保存：

{
  "source_post_id": 119,
  "prefecture": "ehime",
  "course_number": "3",
  "name_ja": "三間盆地2ヵ寺参りのみち",
  "features": [
    "寺",
    "遍路"
  ],
  "location_raw": "宇和島市三間町迫目～西予市宇和町下川",
  "distance_raw": "9.0km",
  "section_raw": "務田駅～第41番龍光寺～...",
  "difficulty_raw": "★☆☆",
  "detail_url": "https://shikoku-nature-trail.com/archives/119"
}

第一階段建議大量使用：

*_raw

不要急著把文字拆得過細。

可以額外保存容易且低風險的 normalized value，例如：

{
  "distance_km": 9.0,
  "difficulty": 1
}

但原始值必須保留。

8. Crawl Pipeline

整體流程：

Course List
    │
    ▼
Fetch list HTML
    │
    ▼
Parse Course Index
    │
    ▼
course-index.json
    │
    ▼
Fetch Detail Pages
    │
    ├── save page.html
    │
    ├── parse image URLs
    │
    └── parse Google My Maps mid
    │
    ▼
Download Assets
    │
    ├── images
    └── KML
    │
    ▼
Manifest + Report

9. Stage 1：下載 Course List

CLI：

nature-trail crawl-index

固定處理四個縣。

URL 建議集中放在 configuration：

struct PrefectureSource {
    id: &'static str,
    name_ja: &'static str,
    url: &'static str,
}

不要散落 hardcode。

輸出

indexes/tokushima.html
indexes/kagawa.html
indexes/ehime.html
indexes/kochi.html

以及：

course-index.json

10. Stage 2：解析 Course List

解析 table 中：

コース名
特徴
場所
距離
区間
難易度

對每一列取得：

course URL

post ID

course name

feature

location

distance

section

difficulty

Parser 原則

不要依賴：

nth-child(3)

作為唯一方法。

最好：

找 table

讀取 header

建立 header → column index mapping

再解析 row

這樣網站欄位順序改變時比較安全。

11. Stage 3：下載 Course Detail HTML

CLI：

nature-trail crawl-details

對：

course-index.json

逐一下載。

例如：

courses/119/page.html

重要原則

永遠先把原始 HTML 寫入 disk，再做 parser。

不要：

HTTP
→ parse
→ 丟掉 HTML

要：

HTTP
→ page.html
→ parser

這樣網站改版或 parser 出 bug，可以離線重跑。

12. Course Detail Metadata

詳細頁 parser 第一階段只需要萃取「下載資產所必要」以及容易辨認的資料。

例如：

{
  "source_post_id": 119,
  "source_url": "https://shikoku-nature-trail.com/archives/119",

  "title": "三間盆地2ヵ寺参りのみち",

  "google_my_maps": {
    "map_id": "...",
    "embed_url": "..."
  },

  "images": [
    {
      "url": "https://..."
    }
  ]
}

完整 description、撮影ポイント、觀光 Spot 的結構化解析可以：

第一階段先做基本擷取

或留到第二階段

但 HTML 已經完整保存，因此不會遺失。

13. Google My Maps ID 解析

詳細頁中搜尋：

google.com/maps/d/embed

解析 iframe src。

使用 URL parser 取得：

mid

不要用大型 regex 手動切 query string。

例如：

let url = Url::parse(src)?;
let map_id = url
    .query_pairs()
    .find(|(key, _)| key == "mid")
    .map(|(_, value)| value.into_owned());

14. KML Download

有 Map ID 後：

https://www.google.com/maps/d/kml?mid={MAP_ID}&forcekml=1

下載到：

courses/{post_id}/map/map.kml

同時保存：

courses/{post_id}/map/metadata.json

例如：

{
  "map_id": "1OadsM6Kmexbspfx-vHalObrDmRN50F8",
  "source_url": "https://www.google.com/maps/d/kml?...",
  "downloaded_at": "2026-08-19T12:00:00+08:00",
  "content_type": "application/vnd.google-earth.kml+xml",
  "size": 123456,
  "sha256": "..."
}

15. KML 驗證

Google 回傳 HTTP 200 不代表一定是 KML。

至少驗證：

HTTP

status == 200

Content size

> 0

XML sanity check

檔案開頭或內容應包含：

<kml

不要只相信：

Content-Type

因為 Google 有可能回 HTML error page / auth page。

如果不是 KML：

mark failed
保留 response body
不要覆蓋已存在的有效 KML

16. 圖片下載

詳細頁所有屬於內容區域的圖片先列入 asset manifest。

例如：

{
  "source_url": "...",
  "type": "image",
  "local_file": "images/001.jpg",
  "status": "downloaded",
  "sha256": "..."
}

不要抓

盡量排除：

WordPress theme 圖片

logo

favicon

social icon

header / footer decoration

tracking pixel

應優先限制 selector 在：

article
entry-content
post-content

實際 selector 必須由 implementation 時檢查 HTML 決定。

17. 圖片檔名

不要直接完全依賴 URL basename。

建議：

001.jpg
002.jpg
003.png

並在 assets.json 保存：

{
  "local_file": "images/001.jpg",
  "original_url": "...",
  "original_filename": "...",
  "content_type": "image/jpeg"
}

原因：

URL 可能帶 query

WordPress 可能有 resize suffix

Unicode filename

同名圖片

URL basename 不穩定

18. HTTP Client

全 crawler 共用一個：

reqwest::Client

設定：

User-Agent
timeout
redirect
connection pooling

例如 User-Agent：

ShikokuNatureTrailArchiver/0.1

可以附 project identifier，但不要冒充 browser。

19. Rate Limit

這個網站資料量不大，不需要高 concurrency。

建議：

max concurrent requests: 2～4

每個 request 可加入：

200～500 ms

間隔。

不要使用：

50 / 100 concurrency

沒有必要，也容易造成不友善負載。

20. Retry Policy

建議 retry：

429
500
502
503
504
network timeout
connection reset

不要 retry：

404
403

除非有明確理由。

Exponential backoff：

1s
2s
4s
8s

最大約：

4 attempts

21. Incremental / Resume

這非常重要。

Crawler 必須可以中途停掉再執行。

例如：

courses/119/page.html exists

且 metadata 表示下載成功：

skip

提供：

--force

才能重抓。

例如：

nature-trail crawl-details --force

22. Crawl State

建議：

crawl-state.json

例如：

{
  "schema_version": 1,
  "last_run": "2026-08-19T12:00:00+08:00",

  "courses": {
    "119": {
      "detail": "ok",
      "images": "ok",
      "kml": "ok"
    }
  }
}

但不要讓 state file 成為唯一真相。

真正判定還應檢查：

file exists
checksum
metadata

23. Manifest

建立整份 archive manifest：

{
  "schema_version": 1,
  "source": "shikoku-nature-trail.com",
  "generated_at": "...",

  "course_count": 100,

  "courses": [
    {
      "post_id": 119,
      "prefecture": "ehime",
      "detail_html": "courses/119/page.html",
      "metadata": "courses/119/metadata.json",
      "kml": "courses/119/map/map.kml",
      "image_count": 8
    }
  ]
}

Manifest 是後續第二階段 pipeline 的入口。

24. Checksum

以下檔案建議計算：

HTML
KML
images

使用：

SHA-256

用途：

偵測網站更新

確認下載完整

deduplicate

parser regression test

future archive comparison

25. HTTP Metadata

每個主要資源建議保存：

{
  "url": "...",
  "status": 200,
  "downloaded_at": "...",
  "etag": "...",
  "last_modified": "...",
  "content_type": "...",
  "content_length": 12345,
  "sha256": "..."
}

如果網站提供：

ETag
Last-Modified

未來可以支援 conditional GET：

If-None-Match
If-Modified-Since

26. CLI 設計

建議最少提供：

nature-trail crawl-index

nature-trail crawl-details

nature-trail download-assets

nature-trail download-kml

nature-trail crawl-all

nature-trail verify

nature-trail report

27. crawl-all

方便第一次 archive：

nature-trail crawl-all \
  --output ./data/raw/shikoku-nature-trail

相當於：

crawl-index
     ↓
crawl-details
     ↓
download-assets
     ↓
download-kml
     ↓
verify
     ↓
report

28. Verify

這個 command 很重要。

nature-trail verify

檢查：

四縣 index 是否存在
Course count
所有 course 是否有 detail HTML
所有有 My Maps 的 course 是否有 KML
KML 是否有效
所有 asset manifest 是否存在
圖片是否缺失
checksum 是否一致

29. Crawl Report

輸出：

reports/crawl-report.json
reports/crawl-report.md

Markdown 例如：

# Crawl Report

Courses discovered: 123

Tokushima: 24
Kagawa: ...
Ehime: ...
Kochi: ...

Detail HTML:
123 / 123

Google My Maps:
118

KML downloaded:
117 / 118

Images:
523

Failures:
- post 1234: KML HTTP 403

這會讓 AI agent 和人工都很容易確認結果。

30. Logging

使用：

tracing

建議 log：

INFO  fetching course list: ehime
INFO  discovered course post_id=119
INFO  fetching detail post_id=119
INFO  google map found map_id=...
INFO  downloading image 1/8
INFO  downloading KML
WARN  image retry
ERROR KML invalid

支援：

RUST_LOG=info

31. Error Handling

單一 Course 失敗不能終止整個 crawl。

例如：

course 119 OK
course 120 image failed
course 121 OK

最後：

exit code != 0

可以依需求設定，但完整 failure list 要寫進 report。

32. Parser Tests

第一次抓到 HTML 後，把數個 representative pages 放到：

tests/fixtures/

例如：

ehime-list.html
tokushima-list.html
course-119.html
course-with-many-images.html
course-without-map.html

注意：

測試 fixture 可以裁切到 parser 需要的 HTML 區塊，避免 repository 放大量內容。

Test 至少驗證：

Course count
post ID
Course name
distance
difficulty
detail URL
Google Map ID
image URL count

33. Selector 設計原則

避免寫死非常深的 selector：

body > div:nth-child(2) > div > ...

優先：

semantic class
article
table
iframe[src*="google.com/maps/d/"]

如果網站沒有良好的 semantic selector，可以在 parser 中：

primary selector
fallback selector

並在找不到時：

WARN

而不是 silent ignore。

34. 資料不要覆蓋

如果重新下載遇到失敗：

HTTP 500
invalid KML
empty body

不要覆蓋上一次有效檔案。

可以：

download temp file
      ↓
validate
      ↓
atomic rename

例如：

map.kml.tmp
→ validate
→ map.kml

HTML / image 也可採相同策略。

35. Atomic Write

所有重要 metadata：

course-index.json
manifest.json
crawl-state.json
metadata.json

應使用：

write temporary file
fsync / close
rename

避免 crawler 中斷造成 JSON 半寫入。

36. 建議實作順序

AI Agent 可以照以下順序實作。

Milestone 1

建立：

CLI
HTTP client
filesystem storage
logging

Milestone 2

完成四縣：

crawl-index

驗證 table parsing。

Output：

index HTML
course-index.json

Milestone 3

完成：

crawl-details

保存所有：

page.html

Milestone 4

Detail parser：

Google My Maps mid
image URL

產生：

metadata.json
assets.json

Milestone 5

圖片 downloader。

Milestone 6

KML downloader：

forcekml=1

並加入 KML validation。

Milestone 7

Resume / retry / checksum。

Milestone 8

實作：

verify
report

37. 第一階段 Definition of Done

第一階段完成條件：

四個縣 Course list HTML 全部保存

四個縣 Course 全部被發現

course-index.json 建立完成

每個 Course 的 detail HTML 已保存

每個 Course 的 Google My Maps ID 已解析（若存在）

可以透過 forcekml=1 下載所有可取得的 KML

KML 有 basic XML validation

Course 內容圖片已下載

每個下載檔案具有來源 URL metadata

KML / HTML / image 保存 SHA-256

支援 resume

支援 --force

單一 Course failure 不影響其他 Course

有完整 crawl report

可以執行 verify 確認 archive 完整性

38. 第二階段（已完成，2026-08-19）

已實作 deterministic offline normalization：

Raw Archive
    │
    ├── HTML Parser
    │     ├── Course metadata
    │     ├── description
    │     ├── 撮影ポイント
    │     └── 観光 SPOT
    │
    ├── KML Parser
    │     ├── LineString
    │     ├── Point
    │     └── Placemark
    │
    └── Image metadata
          │
          ▼
Normalized Dataset

執行：

```bash
python3 -m shikoku_nature_trail --data-dir source/shikoku-nature-trail normalize \
  --output output/shikoku-nature-trail.json
```

Schema v1 合併 course index、detail introduction、撮影ポイント、依來源順序的観光 SPOT、
assets local path 與 KML Placemark/Point/LineString/MultiGeometry。單 course 解析失敗記 warning
並繼續，不產生 timestamp。2026-08-19 全量：123 courses、123 photo points、686 tourism
spots、1,713 Placemarks、0 warnings；詳見 `shikoku_nature_trail/README.md`。

之後再考慮：

GeoJSON
SQLite
OSM merge
Henro route merge
DEM elevation
PMTiles
Android App

39. 核心設計原則總結

本 crawler 最重要的不是「一次成功把資料轉成 App 格式」，而是建立一份可靠、可重新處理的原始 archive。

應遵守：

Download first
Parse second
Normalize later

以及：

Source data should remain reproducible.

因此第一階段最重要的成果應該是：

HTML
+
Images
+
KML
+
Source Metadata
+
Checksums
+
Manifest

只要這一層保存完整，後續不論資料模型、GIS pipeline 或 Android App 架構怎麼調整，都不需要重新依賴網站進行開發。
