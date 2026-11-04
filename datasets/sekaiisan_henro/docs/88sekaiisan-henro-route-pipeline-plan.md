# 四國遍路世界遺產登錄推進協議會 KML 導入計畫

## 目的

使用四國遍路世界遺產登錄推進協議會（`88sekaiisan.org`）公開的 KML，建立一份可獨立更新的「協議會引導路線參考」overlay；不取代 OSM 路網、不宣稱可用於導航，也不和既有 `shikoku-henro.pmtiles` 合併。

截至 2026-08-23，Phase 1 immutable archive 已實作；尚未對下列 KML 做 parsing、QA 或
衍生地圖產物。

## 已確認的來源與用途

| 資料組 | URL pattern | 幾何 | 用途 |
|---|---|---|---|
| 四縣遍路道 | `*_annairu-to{36,39,38,37}.kml` | 大量 LineString | 本計畫的主要資料；每筆 description 標為 `みち案内ルート` |
| 札所 | `{1ban23ban,24ban39ban,40ban65ban,66ban88ban}.kml` | 88 Point | 僅作札所端點和資料 QA 參考；不建立第二份寺廟 canonical data |
| 四縣廁所 | `{tokushimaken,koutiken,ehimeken,kagawaken}.kml` | Point | 有設施名、地址、開放時間、可用日、型式、ウォシュレット與備考；另案處理 |

四份路線 KML 的特性：

- 由 GIS 匯出，單一線段通常只有 `FID` 與 `区分=みち案内ルート`。
- 線段無名稱、札所編號、方向、連通順序或主線/支線語意。
- 使用 `MultiGeometry/LineString` 或直接 `LineString`，parser 必須支援兩者。
- 因此它是高價值的官方幾何參考，但不是可直接 routing 的圖。

### 協議會頁面的明確說明

`https://88sekaiisan.org/restroommap/` 對這批資料的語意有以下明確定義：

1. 掲載的遍路道是「みち案内表示シートで案内するルート」。
2. 該路線考量世界遺產登錄申請路線，並與相關機關協調後決定。
3. 路線可能包含沒有四國遍路文化背景的道路；不能將每一段都標為歷史遍路道或世界遺產申請路線。
4. 參考圖面比例造成 geometry 與地圖道路可能有偏移；不得對 KML 做自動 road snapping 後再稱為原始協議會路線。
5. 道路與交通管制可能改變，使用者必須依現場狀況與交通規制通行；這排除將資料當成 turn-by-turn navigation 指令的用途。

介面名稱與 App attribution 應使用「協議會みち案内表示ルート」或「協議會引導路線參考」，避免使用「官方遍路道」等過度概括的名稱。

## 來源與發布界線

1. 頁面要求使用者遵守國土地理院內容利用規約，該規約僅涵蓋地理院地圖系統與其內容，不能推定為協議會自有 KML 的再散布許可。
2. 網頁 footer 標示 `Copyright © World heritage Registration Council of Shikoku Eighty-eight Sacred temples and Pilgrim road ALL RIGHTS RESERVED.`；建置前必須向協議會取得 KML 轉換、離線封裝及再散布的明確許可。
3. 在許可確認前，僅供本機評估：raw archive、衍生 GeoJSON、PMTiles 一律 gitignore，不隨 App 或公開 repository 發布。
4. metadata、App attribution 和 QA report 都要保留組織名稱、完整 source URL、頁面 URL、下載時間與 SHA-256。
5. 不打包 KML description 內的外部圖片，也不把 KML 的寺廟照片當作已取得的授權。

## 建議產物與目錄

```text
datasets/sekaiisan_henro/raw/
  current.json
  snapshots/<sha256>/
    routes/tokushima.kml
    routes/kochi.kml
    routes/ehime.kml
    routes/kagawa.kml
    temples/1-23.kml
    temples/24-39.kml
    temples/40-65.kml
    temples/66-88.kml
    toilets/tokushima.kml
    toilets/kochi.kml
    toilets/ehime.kml
    toilets/kagawa.kml
    metadata.json

datasets/sekaiisan_henro/
  fetch.py
  parser.py
  normalize.py
  qa.py
  export_map.py
  tests/

output/
  sekaiisan-henro-routes.geojson
  sekaiisan-henro-route-report.json
  shikoku-sekaiisan-henro.pmtiles
```

所有 `datasets/sekaiisan_henro/raw/` 與 `output/sekaiisan-*` 產物均應 gitignore；程式、fixtures、測試和此文件進版控。

## Phase 1: Immutable archive

已實作：`python3 -m datasets.sekaiisan_henro`。它固定下載下列 12 個 KML 至
`datasets/sekaiisan_henro/raw/snapshots/<sha256>/`，完整資料組成功下載和驗證後才更新
`current.json`。該 archive 仍僅供本機評估，並由 `.gitignore` 排除。

1. 建立 manifest，固定列出 12 個 URL、資料組、都道府縣和札所範圍。
2. 以 stdlib `urllib` 下載，設定 User-Agent、30 秒 timeout、有限 retry。
3. 驗證 HTTP 200、非空 body、可 XML parse 且根節點為 KML，避免以 HTML error page 覆蓋有效 archive。
4. 對整組來源與各檔計算 SHA-256；內容不變時不重複建立 snapshot。
5. 以 atomic write 建立 snapshot；任何一檔失敗時不更新 `current.json`。

## Phase 2: Route parsing and normalization

Graph reconstruction、札所 anchor 與相鄰札所候選區間的詳細實作規劃見
`datasets/sekaiisan_henro/docs/sekaiisan-henro-graph-plan.md`。該計畫延伸本文件 Phase 2/3，不改變 Phase 1 archive。

每個 route feature 保留最少必要資訊：

```json
{
  "id": "SHR_tokushima_000001",
  "source_dataset": "88sekaiisan-henro",
  "source_file": "tokushimaken_annairu-to36.kml",
  "prefecture": "tokushima",
  "source_fid": "0",
  "source_classification": "みち案内ルート",
  "geometry": {"type": "LineString", "coordinates": []}
}
```

- `id` 用 prefecture + source FID，若同 FID 有多個 LineString，附加 geometry-part 序號。
- 不從幾何順序推斷 direction、寺廟區間、主線或替代線。
- 保留 source order、raw description 與 raw KML file reference 供診斷；不要寫入 vector tile。
- 拒絕非法座標、少於兩個有效座標的線與未支援 geometry，並於 report 明確列出，不能靜默遺失。

## Phase 3: Geometry QA before any display

1. 計算每縣線段數、點數、總長度、bounds、孤立端點和重複 geometry。
2. 以 88 寺 KML Point 作為端點鄰近性檢查，但寺廟 canonical identity 與座標仍沿用既有寺廟管線。
3. 將官方線段與 OSM `henro_routes` 及 Mizutani 88 route 做 spatial comparison：
   - 每條官方線段計算到候選路線的採樣距離分布。
   - 分成一致、局部偏離、無對應三類；只產生 QA 結果，不自動 snap 或改寫任一來源。
   - 優先人工審閱無 OSM 對應、長度顯著不一致、端點未接近其他線段的區段。
4. 報告必須能從 stable ID 回查 raw KML 的 source URL、檔名與 FID。

這一階段的成功條件是所有原始 LineString 都被 accounted，且能找出官方資料相對 OSM 最具價值的缺口；不是把片段自動串成一條路。

## Phase 4: Independent PMTiles overlay

QA 通過且發布權利確認後才建立 `shikoku-sekaiisan-henro.pmtiles`：

- layer：`sekaiisan_henro_routes`
- geometry：LineString，原始片段粒度，不合併、不簡化
- property：`id`、`prefecture`、`source_fid`、`source`
- zoom：z0-14；必要時測試後設較高 minzoom，避免全島低 zoom 過度密集
- metadata：資料集名稱、協議會 attribution、12 個來源 URL、snapshot SHA、retrieved_at、usage/license status

App 將它標示為「協議會引導路線參考」，以獨立開關與 OSM/Mizutani 路線並列，並在資訊面板顯示協議會的位移與現場交通注意事項。使用者可比較來源，不應有任何一份資料被視為導航指令。

## 廁所資料後續案

四縣廁所資料的欄位足以成為 `henro_toilets` 或獨立 `shikoku-sekaiisan-facilities.pmtiles`。但它是會過時的營運資料，不能與路線 phase 綁定。

後續導入時：

1. raw description HTML table 解析成 name、address、availability、hours、toilet_type、washlet、notes。
2. 保留原文字與 snapshot SHA；時間、假日和例外條件先不做錯誤的結構化推論。
3. 依座標和名稱比對 OSM `amenity=toilets`，只標示可能重複，不自動合併。
4. 以較高 zoom 顯示，並在 UI 顯示資料日期與「開放狀態請現場確認」。

## 最小測試

1. KML namespace、`MultiGeometry` 與直接 `LineString`。
2. 一個 Placemark 含多個 geometry 的 stable ID 與 accounting。
3. 札所 Point 與廁所 Point 的 parser 不會被 route parser 當成線遺失。
4. XML 錯誤、無 geometry、非法經緯度與 HTML error page 失敗。
5. snapshot 相同不重建；單檔下載失敗不更新 current snapshot。
6. fixed fixture -> deterministic normalized output 和 QA report。

## 實作順序

1. 先確認授權與再散布條件。
2. 實作 12 檔 immutable archive 和 parser fixtures。
3. 只針對四份 `annairu` 建 normalized routes 和 QA report。
4. 人工審閱與 OSM/Mizutani 的差異，確認 overlay 對使用者確有新增價值。
5. 建獨立 PMTiles，最後才評估廁所資料。
