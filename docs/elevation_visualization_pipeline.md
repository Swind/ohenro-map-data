# 高程視覺化實作規格

本文件定義如何把 `gsi-dem` 已完成的高程 SQLite 轉成可在 MapLibre 地圖顯示的
等高線、高度色帶、hillshade 與選用的 3D terrain。本文是交付給實作 agent 的規格；
除非驗證結果證明既定方案不可行，第一版不得自行更換資料格式或擴大範圍。

## 1. 目標

第一版必須交付兩份新的地圖資料：

| 產物 | 格式 | 用途 |
|---|---|---|
| `output/shikoku-contours.pmtiles` | vector MVT PMTiles | 20m 等高線與 100m 主線標籤 |
| `output/shikoku-terrain.pmtiles` | PNG Terrain-RGB PMTiles | 高度色帶、hillshade、3D terrain |

現有 `output/shikoku-elevation.sqlite` 與
`output/shikoku-elevation-dem10.sqlite` 繼續作為精確點查詢資料，不改 schema、不改
runtime fallback 語意。視覺化 PMTiles 是可重建的衍生資料，不取代 SQLite。

Web preview 必須使用現有 `map-preview/`，加入：

- 高度色帶開關。
- hillshade 開關。
- 等高線與等高線標籤開關。
- 3D terrain 開關。
- 3D terrain 啟用時的點擊高程顯示。
- GSI attribution。

## 2. 第一版固定決策

| 項目 | 決策 |
|---|---|
| 視覺化來源 | DEM10-only SQLite，layer `10` |
| 輸入 | `output/shikoku-elevation-dem10.sqlite` |
| raster resolution | `1/9000°`，約 12m |
| raster sample | signed Int16，單位 1m |
| NODATA | `-32768` |
| 等高線間隔 | 20m |
| 主等高線 | 100m 的倍數 |
| contour zoom | z12-z15 |
| terrain zoom | z6-z14，z15 由 MapLibre overzoom |
| terrain encoding | Mapbox Terrain-RGB，base `-10000`、interval `0.1` |
| raster tile format | PNG；不可用有損 JPEG/WebP |
| Web renderer | 現有 MapLibre GL JS 5.x + PMTiles protocol |

第一版只用 DEM10，原因如下：

- DEM10 是一致的單一網格，不需要把 DEM10 resample 進 DEM5 fallback 缺口。
- DEM10 的 sea 與 NODATA 都是缺值，不會混淆 DEM5 sea `0m` 與陸地 `0m`。
- 約 12m source resolution 足以支援 20m contour 與 z14 terrain。
- 先完成端到端資料契約，再決定 DEM5 的額外體積是否值得。

## 3. 非目標

第一版不要實作：

- DEM5 + DEM10 composite raster。
- SQLite `mask_tiles` 或格式 v2。
- 10m contour。
- 預先烘焙的彩色 relief 或 hillshade raster。
- 自訂 marching-squares contour engine。
- 自訂 Terrain-RGB XYZ tiler。
- bilinear elevation query。
- route elevation profile。
- Android UI 或 Android PMTiles protocol。
- 新的 Web framework、後端 tile server 或 service worker。

MapLibre 已能從同一份 `raster-dem` source 動態產生 `color-relief` 與 `hillshade`，
因此不要額外輸出兩份彩色 raster PMTiles。

## 4. 完整資料流

```text
output/shikoku-elevation-dem10.sqlite
        |
        +-- gsi-dem export-vrt
        |       |
        |       +-- work/elevation/dem10.raw
        |       +-- work/elevation/dem10.vrt
        |
        +-- gdal_translate -of COG
                |
                +-- work/elevation/dem10.tif
                         |
                         +-- gdal_contour -i 20
                         |       |
                         |       +-- work/elevation/contours.geojsonseq
                         |               |
                         |               +-- tippecanoe
                         |                       |
                         |                       +-- contours.mbtiles
                         |                               |
                         |                               +-- pmtiles convert
                         |                                   output/shikoku-contours.pmtiles
                         |
                         +-- gdalwarp EPSG:3857
                                 |
                                 +-- work/elevation/dem10-3857.tif
                                         |
                                         +-- rio rgbify
                                                 |
                                                 +-- terrain.mbtiles
                                                         |
                                                         +-- pmtiles convert
                                                             output/shikoku-terrain.pmtiles
```

所有中間檔放在 `work/elevation/`。不要將 raw、VRT、GeoTIFF、GeoJSONSeq 或 MBTiles
放入 `output/`，也不要 commit 這些檔案。

## 5. 實作前驗證 gate

開始寫 exporter 前必須完成以下檢查並把結論記入本文件或 build report：

1. 確認 GSI source XML 宣告的水平 CRS，以及 `horizontal_datum=JGD2024` 對應的正式
   GDAL SRS/WKT。不得因經緯度看似相近就直接寫 `EPSG:4326`。
2. 使用 3x2 或 4x4 synthetic raster 驗證 VRT 的 row 0 在北側、Int16 byte order
   為 little-endian、cell center 與現有 `TileGrid::global_cell()` 一致。
3. 用小範圍 GeoTIFF 試跑 `rio rgbify`，確認 NODATA 產生透明/缺值像素，而不是被
   編成有效的極低高程。
4. 將測試 Terrain-RGB MBTiles 轉 PMTiles，確認目前 `pmtiles` CLI 與
   `pmtiles` JavaScript protocol 能讀 raster PMTiles。
5. 確認實際安裝版本的 Tippecanoe 可讀 GeoJSONSeq；若不行，改由 `ogr2ogr` 轉
   FlatGeobuf 或普通 GeoJSON，不得因此改寫 contour engine。

任一 gate 失敗時先記錄可重現命令與錯誤，再採最小替代方案。不要略過 CRS 或
NODATA gate。

## 6. `export-vrt` CLI

在 `gsi-dem` 增加：

```bash
cargo run --manifest-path gsi-dem/Cargo.toml --release -- export-vrt \
  output/shikoku-elevation-dem10.sqlite \
  --layer 10 \
  --output work/elevation/dem10.vrt
```

此命令同時寫：

- `work/elevation/dem10.vrt`
- `work/elevation/dem10.raw`

### 6.1 預計檔案

| 檔案 | 修改 |
|---|---|
| `gsi-dem/src/main.rs` | 註冊 `ExportVrt` subcommand |
| `gsi-dem/src/cli/mod.rs` | export module |
| `gsi-dem/src/cli/export_vrt.rs` | CLI args 與流程 |
| `gsi-dem/src/db.rs` | 可重用、persistent 的 tile reader |
| `gsi-dem/src/raster/vrt.rs` | raw raster 與 VRT writer；若很短可留在 CLI module |
| `gsi-dem/tests/export_vrt.rs` | synthetic DB export regression |

不要加入 Rust GDAL binding。Rust 只輸出標準 raw Int16 + VRT，GeoTIFF 交給既有
GDAL CLI。這可以避免 `libgdal` native linkage 進入 `gsi-dem` runtime。

### 6.2 CLI arguments

```text
gsi-dem export-vrt <DATABASE>
  --layer <5|10>          第一版 build script 固定傳 10
  --output <PATH.vrt>
  --srs <GDAL_SRS>        gate 確認後提供正確預設；仍允許覆寫
```

驗證規則：

- database 必須存在。
- `--layer` 只能是 `5` 或 `10`。
- output extension 必須是 `.vrt`。
- metadata 的 `compression` 必須是 `zstd`。
- metadata 的 `encoding` 必須是 `int16_meters`。
- metadata tile size 與資料列 width/height 必須一致。
- 解壓後 elevation blob 必須剛好是 `width * height * 2` bytes。
- output parent 不存在時建立。
- 已存在的 `.vrt` 或 `.raw` 不可默默覆蓋；提供明確 `--force` 才可覆蓋。

### 6.3 DB reader

目前 `query_db()` 每個 point 重新開 DB 並解壓完整 tile，只適合單點查詢。新增最小的
reader，生命週期內保留一個 `rusqlite::Connection`：

```rust
pub struct ElevationDb {
    conn: Connection,
    tile_size: usize,
    dem5: Option<GridInfo>,
    dem10: Option<GridInfo>,
}
```

至少提供：

```rust
impl ElevationDb {
    pub fn open(path: &Path) -> DemResult<Self>;
    pub fn grid(&self, layer: i64) -> DemResult<GridInfo>;
    pub fn tile_extent(&self, layer: i64) -> DemResult<Option<TileExtent>>;
    pub fn read_elevation_tile(
        &self,
        layer: i64,
        tile_x: i64,
        tile_y: i64,
    ) -> DemResult<Option<Vec<i16>>>;
}
```

`query_db()` 可改用 reader，但不要在本階段重寫 public query behavior。不要先加入 LRU
cache；bulk exporter 每個 tile 只讀一次，不需要 cache。

### 6.4 Export extent

用 SQL 查 layer 的 tile extent：

```sql
SELECT MIN(tile_x), MAX(tile_x), MIN(tile_y), MAX(tile_y)
FROM elevation_tiles
WHERE layer = ?1;
```

輸出 raster 以完整 tile rectangle 為範圍：

```text
width  = (max_tile_x - min_tile_x + 1) * tile_size
height = (max_tile_y - min_tile_y + 1) * tile_size
west   = origin_lon + min_tile_x * tile_size * step_lon
north  = origin_lat - min_tile_y * tile_size * step_lat
```

GeoTransform：

```text
[west, step_lon, 0, north, 0, -step_lat]
```

### 6.5 Raw writer

`dem10.raw` 格式固定為 row-major signed Int16 little-endian，沒有 header。

最小、可靠的寫法：

1. 建立寬度為 `width` 的 row buffer，全部填 `ELEV_NODATA`。
2. 先逐 row 寫滿整個 raw raster，確保不存在的 tile 是 NODATA，而不是 sparse-file 0。
3. 依 `(tile_y, tile_x)` 排序讀取 DB tiles。
4. 對每個 tile 的 256 rows，seek 到目標 byte offset 後寫該 row。
5. 所有乘法與 byte offset 使用 checked arithmetic。

不得把完整 raster 配置在 RAM。允許 raw 中間檔約 1-2GB，因為既有 pipeline 已使用
數 GB 的 `work/merged`。

### 6.6 VRT writer

VRT 使用 `VRTRawRasterBand`，必要內容如下：

```xml
<VRTDataset rasterXSize="..." rasterYSize="...">
  <SRS>...</SRS>
  <GeoTransform>west, step_lon, 0, north, 0, -step_lat</GeoTransform>
  <VRTRasterBand dataType="Int16" band="1" subClass="VRTRawRasterBand">
    <NoDataValue>-32768</NoDataValue>
    <SourceFilename relativeToVRT="1">dem10.raw</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>2</PixelOffset>
    <LineOffset>width_times_2</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
```

XML 內容必須 escape；不要用字串插值直接放入未驗證的 path 或 SRS。

## 7. GeoTIFF / COG

`scripts/build-elevation-visuals.sh` 執行：

```bash
gdal_translate \
  -of COG \
  -ot Int16 \
  -a_nodata -32768 \
  -co COMPRESS=ZSTD \
  -co BLOCKSIZE=256 \
  -co BIGTIFF=IF_SAFER \
  work/elevation/dem10.vrt \
  work/elevation/dem10.tif
```

接著用 `gdalinfo -json` 驗證：

- driver 是 `GTiff`/COG。
- band type 是 `Int16`。
- NODATA 是 `-32768`。
- CRS 等於 gate 確認的 source CRS。
- pixel Y size 是負值。
- bounds 覆蓋四國。

## 8. 等高線產生

執行：

```bash
gdal_contour \
  -f GeoJSONSeq \
  -i 20 \
  -a elevation_m \
  -snodata -32768 \
  work/elevation/dem10.tif \
  work/elevation/contours.geojsonseq
```

第一版只保留一個欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `elevation_m` | integer | contour 高程，必須是 20 的倍數 |

不要預先加入 `index` 欄位。Web style 用 `elevation_m % 100 == 0` 判斷主線。

Tippecanoe command：

```bash
tippecanoe \
  --force \
  --output work/elevation/contours.mbtiles \
  --layer contours \
  --minimum-zoom 12 \
  --maximum-zoom 15 \
  --drop-densest-as-needed \
  --extend-zooms-if-still-dropping \
  work/elevation/contours.geojsonseq

pmtiles convert \
  work/elevation/contours.mbtiles \
  output/shikoku-contours.pmtiles
```

若 Tippecanoe 回報 tile overflow，先記錄最大 tile 與 feature count，再調整 simplification
或 contour interval。不可直接使用 `--no-tile-size-limit` 產生不適合 mobile 的 tiles。

## 9. Terrain-RGB 產生

先 warp 到 Web Mercator。hillshade 與 web tile pyramid 不可直接把 degree 當公尺：

```bash
gdalwarp \
  -t_srs EPSG:3857 \
  -r bilinear \
  -srcnodata -32768 \
  -dstnodata -32768 \
  -multi \
  -wo NUM_THREADS=ALL_CPUS \
  -co TILED=YES \
  -co COMPRESS=ZSTD \
  -co BIGTIFF=IF_SAFER \
  work/elevation/dem10.tif \
  work/elevation/dem10-3857.tif
```

Terrain-RGB command：

```bash
rio rgbify \
  --base-val -10000 \
  --interval 0.1 \
  --min-z 6 \
  --max-z 14 \
  --format png \
  --workers 4 \
  work/elevation/dem10-3857.tif \
  work/elevation/terrain.mbtiles

pmtiles convert \
  work/elevation/terrain.mbtiles \
  output/shikoku-terrain.pmtiles
```

Mapbox Terrain-RGB decode contract：

```text
elevation_m = -10000 + (R * 256 * 256 + G * 256 + B) * 0.1
```

PNG 必須無損。任何會改動 RGB channel 的有損壓縮都會直接改變高程。

若 gate 發現 `rio-rgbify` 不保留 NODATA transparency，優先以最小 rasterio wrapper
修正 mask 後再呼叫既有 tiling，而不是自行實作整個 XYZ pyramid。替代方案必須附上
一個 ocean tile decode regression。

## 10. Build script

新增 `scripts/build-elevation-visuals.sh`，風格比照 `scripts/build-henro.sh`：

- `set -euo pipefail`。
- 路徑由 script directory 推導 repository root。
- preflight 檢查 `cargo`、`gdal_translate`、`gdalwarp`、`gdal_contour`、
  `gdalinfo`、`tippecanoe`、`rio`、`pmtiles`。
- 檢查 DEM10-only SQLite 存在且非空。
- 建立 `work/elevation`、`output`、`reports`。
- 預設不重建現有 SQLite。
- 任一步失敗即 non-zero exit。
- 完整 stdout/stderr 寫入 `reports/elevation-visuals-build.log`。
- PMTiles metadata 寫入 `reports/contours-metadata.txt` 與
  `reports/terrain-metadata.txt`。
- 最後執行資料驗證與 Web build。

腳本可接受環境變數：

| 變數 | 預設 |
|---|---|
| `ELEVATION_DB` | `output/shikoku-elevation-dem10.sqlite` |
| `WORK_DIR` | `work/elevation` |
| `CONTOUR_INTERVAL` | `20` |
| `TERRAIN_MIN_ZOOM` | `6` |
| `TERRAIN_MAX_ZOOM` | `14` |
| `RGBIFY_WORKERS` | `4` |

只有已知需要調整的 build resource 才設環境變數。不要為每個固定 schema 值增加設定。

## 11. Web preview 整合

### 11.1 Environment

在 `map-preview/.env.example` 新增：

```dotenv
VITE_CONTOURS_URL=/data/shikoku-contours.pmtiles
VITE_TERRAIN_URL=/data/shikoku-terrain.pmtiles
```

更新 `map-preview/README.md` 的本機 symlink 指令，加入兩份 PMTiles。

### 11.2 Sources

在 `map-preview/src/map.ts` 的 load flow 加入：

```ts
map.addSource("elevation-dem", {
  type: "raster-dem",
  url: `pmtiles://${terrainUrl}`,
  encoding: "mapbox",
  tileSize: 256,
  attribution: "...GSI attribution...",
});
```

MapLibre 對同一 source 同時作 terrain 與 color-relief 會提出品質警告。用兩個 source ID
指向同一個 PMTiles URL，不複製資料：

- `elevation-dem-style`：供 hillshade 與 color-relief。
- `elevation-dem-terrain`：供 `map.setTerrain()`。

Contour source：

```ts
map.addSource("elevation-contours", {
  type: "vector",
  url: `pmtiles://${contoursUrl}`,
});
```

環境變數空白時略過該 source/layers，Web preview 仍須正常載入既有 basemap。

### 11.3 Layers

固定 layer IDs：

| ID | type | 預設 |
|---|---|---|
| `elevation-color-relief` | `color-relief` | hidden |
| `elevation-hillshade` | `hillshade` | visible |
| `elevation-contour` | `line` | visible |
| `elevation-contour-index` | `line` | visible |
| `elevation-contour-label` | `symbol` | visible |

建議 color ramp：

```ts
"color-relief-color": [
  "interpolate", ["linear"], ["elevation"],
  0, "#d9e8bd",
  100, "#b9d39a",
  300, "#d8c589",
  600, "#b8956e",
  1000, "#8c766b",
  1800, "#e2dfda",
]
```

主 contour filter：

```ts
["==", ["%", ["get", "elevation_m"], 100], 0]
```

一般 contour 排除同一批主線，避免重疊繪製。Label 使用 `symbol-placement: line`，只標
100m 主線，文字內容為 `{elevation_m} m`，使用 halo 保持可讀性。

Layer insertion order：

```text
basemap background/earth
elevation-color-relief
elevation-hillshade
basemap landcover/water
elevation contours
basemap roads/buildings
basemap labels
henro route
temples/lodging
```

不可只用 `map.addLayer()` 全部加在 style 最上層。找一個穩定的 basemap layer ID 作
`beforeId`；若該 ID 不存在，fallback 到第一個 label layer 前。

### 11.4 Controls

擴充 `HenroLayers` 或改名為較通用的 preview layer registry，加入 elevation layer IDs。
不要建立抽象 plugin system。

`map-preview/index.html` 新增：

- `toggle-elevation-color`
- `toggle-hillshade`
- `toggle-contours`
- `toggle-contour-labels`
- `toggle-terrain`

`map-preview/src/main.ts` 沿用現有 `toggleLayer()`。Terrain toggle：

```ts
map.setTerrain(visible ? {source: "elevation-dem-terrain", exaggeration: 1} : null);
```

只有 terrain 啟用且 tile 已載入時，點擊 popup 才附加：

```ts
const elevation = map.queryTerrainElevation(e.lngLat);
```

回傳 `null` 時顯示 `elevation: unavailable`，不可顯示 0。不要為了 terrain 關閉時的
點查詢，把 126MB SQLite 載入 browser 或增加 backend API。

### 11.5 Layer errors

監聽 MapLibre `error` event。Elevation URL 缺失或 archive 讀取失敗時：

- console 顯示 source ID 與錯誤。
- 不阻止 basemap 與 Henro layers 顯示。
- 對應 toggle disabled 或標記 unavailable。

## 12. 自動驗證

### 12.1 Rust tests

新增最少三個 exporter tests：

1. synthetic 2x2 tiles 跨越四個 tile coordinate，驗證 raw placement、tile 邊界與
   north-up orientation。
2. 缺一個 tile，驗證整個缺區都是 `-32768`，不是 `0`。
3. malformed decompressed blob length，驗證回傳 error 而不是 panic/out-of-bounds。

可再用小 VRT 執行 GDAL integration test，但 GDAL 不存在時必須明確 skip，不可讓
一般 `cargo test` 依賴 system GDAL。

### 12.2 Golden coordinates

對 `gsi-dem/tests/golden/elevation.json` 中 `layer=dem10` 的點驗證：

- GeoTIFF sample 與 SQLite sample 差異應為 0m。
- Terrain-RGB decode 與 GeoTIFF 差異不超過 1m。
- 最終 PMTiles tile decode 與 MBTiles tile decode 一致。

既有 golden 中 DEM5 點不要求 DEM10 visualization 與 DEM5 高程相同；可另以同座標
直接查 DEM10 layer 建立 visualization baseline。

### 12.3 Contour validation

驗證：

- 所有 `elevation_m` 是有限 integer。
- 所有 `elevation_m % 20 == 0`。
- 不存在 `-32768` contour。
- PMTiles metadata 的 vector layer 包含 `contours` 與 `elevation_m`。
- bounds 與四國重疊。
- z12-z15 至少各有 tile。
- 選定內陸 hill sample 的 contour 高程能包圍 golden elevation，誤差不超過一個
  contour interval。

### 12.4 Raster validation

驗證：

- PMTiles tile type 是 PNG。
- z6-z14 有 tile。
- 任一陸地 sample decode 為合理高程。
- 任一公海 sample 不得 decode 為有效陸地高程。
- tile seam 兩側高程連續；允許 source terrain 本身的變化，不允許固定 256px 接縫。

### 12.5 Web validation

執行：

```bash
npm --prefix map-preview run build
```

手動檢查桌面與手機寬度：

1. 無 elevation URL 時既有 preview 正常。
2. hillshade 預設可見且不蓋掉道路、地名和遍路路線。
3. color relief 可獨立開關。
4. contour 在 z12 以下不出現，z12 以上可讀。
5. 100m 主線較粗且有標籤。
6. 3D terrain 開關可恢復平面地圖。
7. terrain 啟用後點擊可取得合理高程。
8. 海面沒有低高程彩色方塊或尖峰。

## 13. Top-level scripts 與文件更新

實作完成時更新：

- `gsi-dem/README.md`：加入 `export-vrt` 與 visualization build commands。
- `map-preview/README.md`：加入 elevation sources、controls、data links。
- `scripts/inspect-pmtiles.sh`：顯示 contours 與 terrain metadata；檔案不存在時可標記
  skipped，不影響只建舊產品的 workflow。
- `scripts/validate.sh`：若 elevation visualization artifacts 存在就驗證；另提供
  `scripts/build-elevation-visuals.sh` 的嚴格 validation，不可讓缺檔默默成功。
- `AGENTS.md`：目錄與常用命令補上兩份新 PMTiles。

Attribution 文字依 GSI 使用條款確認後，同時寫入 PMTiles metadata 與 MapLibre source。
不要只放在 README。

## 14. 建議 commit 切分

實作 agent 應保持每個 commit 可驗證：

1. `Add DEM SQLite VRT exporter`
2. `Add elevation visualization build pipeline`
3. `Add elevation layers to map preview`
4. `Document elevation visualization workflow`

不要把 generated GeoTIFF、MBTiles、PMTiles、`work/` 或 `map-preview/dist/` commit 進 git。

## 15. 完成定義

第一版只有在以下全部成立時才算完成：

- `cargo test --manifest-path gsi-dem/Cargo.toml` 通過。
- `gsi-dem export-vrt` 可由 DEM10-only SQLite 產生可被 GDAL 讀取的 VRT。
- COG GeoTIFF 的 CRS、north-up、NODATA 與 golden samples 正確。
- `output/shikoku-contours.pmtiles` 可被 PMTiles CLI 與 Web preview 讀取。
- `output/shikoku-terrain.pmtiles` 可被 MapLibre 當作 `raster-dem` 讀取。
- Web preview 可切換 color relief、hillshade、contours、labels 與 3D terrain。
- ocean NODATA、tile seam、contour interval 與 Terrain-RGB decode 驗證通過。
- `npm --prefix map-preview run build` 通過。
- build script 可從已存在的 DEM10 SQLite 一次重建兩份 PMTiles。
- build log、metadata 與 attribution 已保存。

## 16. 第二階段：DEM5 視覺化

DEM10 第一版穩定且實測確認需要更高細節後，才進行 DEM5：

1. 從 `MergedMesh` 保留 mask 到 tile accumulator。
2. 新增 versioned tile format `G5T2`。
3. SQLite 新增 `mask_tiles`，`format_version` 升為 2。
4. 明確區分 Terrain 0m、Sea 0m、InlandWater、Seabed、InlandBottom。
5. 建立 DEM5 grid 的 visualization composite；只在 DEM5 NODATA 時 nearest-resample
   DEM10，並清楚標記這是 cartographic derivative，不改 canonical query semantics。
6. terrain max zoom 可提高至 z15，contour interval 可評估降至 10m。

目前 SQLite 已遺失 sample kind mask，無法可靠由 `source_tiles` 還原 sea/terrain。
第二階段必須從 `work/merged` 或 GSI sources 重建，不得把所有 `0m` 當 sea 猜測。
