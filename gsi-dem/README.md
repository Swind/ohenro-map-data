# gsi-dem

GSI 四國 DEM 資料轉換工具（Rust）。對應 `reference/gis-dem-converter.md` 規劃的
Phase 1-7 已完成（Inspector / Raster correctness / DEM5 merge / DEM10B fallback /
Final tiling / SQLite container + runtime query / Validation）。

## Phase 1 狀態（Inspector）

- ZIP reader：直接從 ZIP 讀 XML entry，**不將 XML 解壓到磁碟**（in-memory buffer，`gsi/archive.rs`）。
- 支援 nested ZIP（`open_inner_zip` + `MAX_INNER_ZIP_SIZE=64MiB` guard）。
- XML streaming parser（`gsi/xml.rs`，quick-xml event mode，不建 DOM）。
- tupleList streaming parse → SoA arrays（`elevation: Vec<f32>` + `mask: Vec<u8>`）。
- 正確解析 Terrain / Sea / InlandWater / NoData。
- 保留 `sequenceRule` / `startPoint`，供後續 pixel→coordinate 對映使用。
- CLI：`inspect` / `query` / `render`。

## 資料結構關鍵發現（重要，規劃假設需要修正）

### 1. DEM5 的 sample count 不固定

規劃文件假設每張 raster 都是 `225×150 = 33750` samples。**實際上沿海 mesh 只存部分 grid**：

```
mesh 51346200 (內陸): 33750 samples (full)
mesh 51346278 (沿海): 23850 samples (partial, start=(0,44))
mesh 51346258 (沿海):  2539 samples (partial, start=(161,138))
```

全部 69 個 DEM5A mesh 驗證一致：tuple 數 = `(W - start_x) + W * (H - 1 - start_y)`。
因此 **validate 不能要求 sample count == width×height**，partial mesh 是正常資料，
不是損壞。`is_partial()` 用於標記。

### 2. Grid 方向：row 0 = 北（max_lat）

`gml:Envelope` 的 `lowerCorner` 是 SW、`upperCorner` 是 NE，但 GSI 的實際 grid
排列是 **row 0 = 北方邊緣**，往南遞增。以 DEM10B 對照小豆島地標驗證：

| 座標 | 真實地物 | 本工具 |
|---|---|---|
| (34.508, 134.296) 寒霞渓 | 山（陸地） | 272.60m |
| (34.503, 134.256) | 小豆島內陸 | 200.90m |
| (34.575, 134.30) | 瀨戶內海 | N/A |

`raster/grid.rs` 的 `cell_center` / `nearest_cell` 已實作 north-up 對映
（`lat = max_lat - (row+0.5)*step`）。

### 3. DEM5 與 DEM10B 的 tuple schema 不同

- DEM5A（`5mメッシュ（標高）`）：`地表面,123.45` / `海水面,-9999.` / `データなし,-9999.` / `内水面,396.63`
  - `内水面`（內陸水）**帶有真實高程**（0~527m），不是 sentinel。
- DEM5B/5C（`5mメッシュ（数値地形）`）：**混合 schema** — 同一檔案可能混用
  `その他` / `地表面` / `海水面` / `データなし`。
  - `その他` + 非 `-9999` 值是**真實高程**（驗證：與 `地表面` 平滑連續，如 674.11→676.60）。
  - `海水面` 用 `-9999.` sentinel（與 DEM5A 相同語義）。
  - 部分 5B mesh 是 partial coverage（如 n=33600），且此類 mesh 常**真的有資料缺口**
    （DEM10B 有值、DEM5B 無值），這是 DEM10B 作為 fallback 的用途，不是損壞。
- DEM10B：全部標 `その他,<value>`，`-9999.00` 是 nodata/sea sentinel，
  **沒有 sea 語義區分**。`classify_tuple()` 處理所有差異。

### 4. Sea 正規化

`海水面` → elevation `0.0` + `mask=SEA`。`データなし` → `NaN` + `mask=NODATA`。
`内水面` → 保留真實高程 + `mask=INLAND_WATER`。

### 5. DEM10B 是單一 XML / ZIP

DEM10B 每 zip 只有一個 XML，grid 是 `1125×750 = 843750` samples（full coverage），
而 DEM5 每 zip 有 69~74 個 XML（每個 mesh 一個）。檔案命名也不同
（`FG-GML-5134-62-dem10b-20161001.xml`，全小寫 `dem10b`）。

## 使用方法

```bash
# Inspect（不落 XML 到磁碟）
cargo run --release -- inspect source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip
cargo run --release -- inspect --verbose source/GSI/DEM10B/FG-GML-513462-DEM10B-20161001.zip

# 只顯示 partial mesh
cargo run --release -- inspect --partial-only source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip

# lat/lon -> elevation（nearest-cell，bilinear 屬後續 phase）
cargo run --release -- query source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip --lat 34.503 --lon 134.256

# Debug render PNG（north-up；黑=未儲存格, 紫=NODATA, 藍=SEA, 青=內水, 深藍=海底/內水底, 灰階=地形）
cargo run --release -- render source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip --mesh 51346200 --output /tmp/mesh.png

# Phase 3：DEM5 per-mesh merge（A > B > C pixel-level）+ Phase 4：DEM10B fallback
cargo run --release -- merge --input source/GSI/DEM5 --dem10b-input source/GSI/DEM10B \
  --report /tmp/merge-report.json
# 只處理特定 primary region（6 位 prefix，可重複）
cargo run --release -- merge --input source/GSI/DEM5 --region 513440 --region 513462
# 印出某點的 DEM5 + DEM10B fallback 高程（fallback 查詢路徑）
cargo run --release -- merge --input source/GSI/DEM5 --dem10b-input source/GSI/DEM10B \
  --region 503354 --query-lat 33.754 --query-lon 133.544
# 渲染某個 merged mesh 目視檢查 + 寫 merged .bin（每 mesh ~200KB，全量約 3.8GB）
cargo run --release -- merge --input source/GSI/DEM5 \
  --render-mesh 51344063 --render-output /tmp/merged.png --out-dir work/merged

# Phase 5：把 merged .bin + DEM10B 切成 256x256 zstd tile
cargo run --release -- tile --merged work/merged \
  --dem10b source/GSI/DEM10B --out work/tiles \
  --report /tmp/tile-report.json --check-lat 33.754 --check-lon 133.544

# Phase 6：tiles -> SQLite（metadata + elevation_tiles + source_tiles）
cargo run --release -- build --tiles work/tiles \
  --grid /tmp/tile-report.json --output output/shikoku-elevation.sqlite

# 只用 DEM10 layer 的精簡版（126MB，10m 解析度）
cargo run --release -- build --tiles work/tiles --grid /tmp/tile-report.json \
  --layer 10 --output output/shikoku-elevation-dem10.sqlite

# runtime 查詢：DEM5 優先、無值 fallback DEM10
cargo run --release -- query-db output/shikoku-elevation.sqlite --lat 33.754 --lon 133.544
# => Elevation: 335.0 m  (layer=DEM10, source=DEM10B)

# Phase 7：golden coordinates regression + coverage/source report
cargo run --release -- validate-db output/shikoku-elevation.sqlite \
  --golden gsi-dem/tests/golden/elevation.json --report /tmp/validate-report.json
# => golden: 7/7 passed; coverage DEM5/DEM10 breakdown

# 高程視覺化：把 DEM10 layer 匯出成 raw Int16 + GDAL VRT（不 link libgdal）
# 輸入可以是精簡的 output/shikoku-elevation-dem10.sqlite（--layer 10）
cargo run --release -- export-vrt \
  output/shikoku-elevation-dem10.sqlite --layer 10 --output work/elevation/dem10.vrt
# 同時寫 work/elevation/dem10.raw（row-major Int16 LE）+ dem10.vrt。
# 之後用 scripts/build-elevation-visuals.sh 產生兩份 PMTiles：
#   output/shikoku-contours.pmtiles（20m 等高線, MVT, z12-15）
#   output/shikoku-terrain.pmtiles（Terrain-RGB, PNG, z6-14）
# 該 build script 用 Docker 跑 GDAL / tippecanoe / rgbify（見 docker/Dockerfile.elevation）。

# 交叉驗證 raster 正確性（Phase 2 acceptance）
# DEM5A vs DEM10B：
cargo run --release -- validate \
  source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip \
  source/GSI/DEM10B/FG-GML-513462-DEM10B-20161001.zip --samples 500
# DEM5B（混合 schema）vs DEM10B：
cargo run --release -- validate \
  source/GSI/DEM5/5B/FG-GML-493254-DEM5B-20210115.zip \
  source/GSI/DEM10B/FG-GML-493254-DEM10B-20161001.zip --samples 500
```

## 測試

```bash
cargo test
```

- `tests/parser.rs`：synthetic GML fixture（3×2 grid），metadata / kinds / 正負高程 /
  grid placement（full + partial）/ north-up 對映 / 錯誤處理 / Shift_JIS 舊檔解碼 /
  海底（海水底面）/ 內水底（内水底面）帶真實高程。
- `tests/merge.rs`：merge 單元測試（A>B>C 優先序、Sea/Seabed 覆蓋低優先序、
  A nodata → B 填補、partial A 由 B 補洞、partial 尾列 bounds、source array、
  幾何衝突錯誤、round-trip）。
- `raster/dem10.rs` tests：DEM10B fallback（nearest-cell 取樣、nodata 不算、
  fill_count 填補/殘留計算）。
- `tile/` 內建 tests：global grid 對齊與 cell 對映、quantize/zstd round-trip、
  mesh/DEM10 放置到 tile（含 nodata skip）。
- `db.rs` 內建 test：合成 tiles → SQLite build → query 的完整 round-trip
  （DEM5 命中 + DEM10 fallback）。
- `tests/golden.rs`：golden-coordinate regression（讀 `tests/golden/elevation.json`，
  DB 不存在時自動 skip）。
- `tests/integration.rs`：真實 `FG-GML-513462-DEM5A-20251208.zip`、
  `FG-GML-513462-DEM10B-20161001.zip`、`FG-GML-493254-DEM5B-20210115.zip`。
  驗證 sample counts、地標高程、round-trip、混合 schema、DEM5 vs DEM10B 交叉驗證。
  archive 不存在時自動 skip。

## 結構

```text
src/
├── main.rs            CLI entry（clap）
├── lib.rs
├── cli/
│   ├── build.rs        tiles -> SQLite（metadata + elevation/source tiles）
│   ├── inspect.rs      inspect 命令
│   ├── merge.rs        per-mesh merge（A > B > C，report / render / out-dir）
│   ├── query.rs        lat/lon -> elevation（ZIP archive）
│   ├── query_db.rs     lat/lon -> elevation（SQLite，DEM5→DEM10 fallback）
│   ├── render.rs       debug PNG
│   ├── tile.rs         256x256 tiling（zstd int16 tile）
│   ├── validate.rs     DEM5 vs DEM10B 交叉驗證（Phase 2 acceptance）
│   └── validate_db.rs  golden coordinates + coverage/source report（Phase 7）
├── db.rs               SQLite schema + build + runtime query（規劃 §23-§25）
├── gsi/
│   ├── archive.rs      ZIP / nested ZIP / entry reader
│   ├── xml.rs          streaming XML parser（quick-xml，含 Shift_JIS 解碼）
│   ├── model.rs        GsiDemRaster / SampleKind / DemSource
│   └── error.rs        DemError
├── raster/
│   ├── dem10.rs        DEM10B fallback 查詢 + nodata 填補計算
│   ├── grid.rs         grid placement / coordinate mapping / lookup
│   └── merged.rs       MergedMesh + per-pixel merge 邏輯 + GM5M bin I/O
└── tile/
    ├── grid.rs         TileGrid（固定 geographic grid，256x256）
    ├── codec.rs        int16 quantize + zstd
    ├── rasterize.rs    merged mesh / DEM10 raster -> tile accumulator
    └── tilefile.rs     G5T1 tile 檔案格式（Phase 6 讀回用）
```

## Phase 2 狀態（Raster correctness）

已完成並驗證：

- **sequenceRule / startPoint**：`+x-y` Linear + startPoint 的 tuple→grid 對映
  已整理進 `raster/grid.rs`（含 row flip 語意說明），sample-count 公式對全部
  69 個 DEM5A mesh + DEM5B/5C + DEM10B 成立。
- **pixel ordering**：row 0 = north（max_lat）已確認。
- **coordinate mapping**：`gsi-dem validate` 交叉驗證通過：
  - DEM5A vs DEM10B（Shodoshima 513462）：median |diff| 3.87m，sea 一致性 100%。
  - DEM5B vs DEM10B（Uwajima 493254）：median 4.07m，0 個 land-over-sea 錯誤。
  - 剩餘的 "land-over-sea" 點都是 0~3m 的沿海邊界格（10m vs 5m 解析度差異），
    非方向錯誤。
- **PNG debug render**：`render` 命令輸出 north-up 灰階圖，方向已驗證。

**Phase 2 完成前不要開始 bulk build** 的條件已滿足，已進入 Phase 3（DEM5 merge）。

## Phase 3 狀態（DEM5 per-mesh merge）

新增 `merge` 命令：掃描 `source/GSI/DEM5`（5A/5B/5C），依 6 位 primary region
群組（每 archive 只解析一次），對每個 mesh 做 **A > B > C pixel-level merge**。

- **per-pixel 語意**：A/B/C 中較高優先序者「只要有非 NODATA 樣本就贏」，
  包括 Sea / InlandWater / Seabed / InlandBottom（它們都是有效樣本）。
  只有 NoData 才會落到較低優先序的 source。
- **MergedMesh**（`raster/merged.rs`）：full grid（W×H），每格記錄
  elevation + mask + **source code**（規劃 §16：0=NODATA, 2=DEM5C, 3=DEM5B, 4=DEM5A，
  1=DEM10B 保留給 Phase 4）。
- **幾何校驗**：同 mesh 的 A/B/C bounds 與 W×H 必須一致，否則 error。
- **partial 尾列**：部分 mesh 不只第一列 partial，最後一列也可能 partial
  （如 mesh stored 5039/33750、start=(13,0)）。`grid_to_tuple_index` 對未儲存
  格回傳 ≥ sample_count 的 index，merge 以 bounds-check 視為「該 source 無值」。
- **結果**（2026-08-17，全四國 417 archives、20,362 meshes、38 秒）：
  - combos：A-only=17918、AB=1439、ABC=13、AC=855、B-only=136、C-only=1。
  - 像素：A=626.7M、B=6.4M、C=17.5k、nodata=54.1M（總和 = 20362×33750，無誤差）。
  - 不變式驗證：merged A-wins == A 有效樣本數、merged B-wins == B 有效 − A 有效
    （在 513440 區域逐 mesh 抽查通過）。
- `--out-dir` 可寫每 mesh 二進位檔（magic `GM5M`，f32 elevation + u8 mask + u8 source）；
  `--render-mesh` 可輸出 merged PNG 目視檢查。

### Phase 3 過程新增的資料結構發現

1. **舊 5B 是 Shift_JIS 編碼**：8 個 2008–2010 的 5B archive 宣告
   `encoding="Shift_JIS"`（其餘 5A/5B/5C 全 UTF-8）。parser 現讀 XML declaration，
   用 `encoding_rs` 解碼 label/欄位（`gsi/xml.rs`）。
2. **`海水底面`（seabed）與 `内水底面`（inland water bed）帶真實高程**：
   沿海 5m 資料量到淺海底（如 -5.16m），不是 sentinel。新增
   `SampleKind::Seabed = 4` / `SampleKind::InlandBottom = 5`，保留負高程。
   全資料集 tuple label 只有 7 種（地表面/その他/データなし/海水面/内水面/
   海水底面/内水底面），已全部支援。
3. **5C 幾乎全被覆蓋**：C 只贏 17.5k 像素（20,362 meshes 中僅 13 個 ABC、1 個
   C-only），5C 資料在 merge 後基本只是驗證用。

## Phase 4 狀態（DEM10B fallback layer）

DEM10B 是獨立的 10m 解析度層（275 archives、每 region 一張 1125×750 raster），
**不做 resample、不 merge 進 DEM5**（規劃 §17/§42）。`merge` 命令現會：

- 掃描 `--dem10b-input`（預設 `source/GSI/DEM10B`），依 region 載入對應的
  DEM10B raster（每 region 一張）。
- 對每個 merged mesh，把 DEM5 的 nodata 格轉成 lat/lon，對 DEM10B 取 nearest-cell：
  有值 → `dem10_fills`，無值 → `remains`。
- `--query-lat/--query-lon`：印出該點的「DEM5 合併結果 + DEM10B fallback 結果」，
  直接示範 runtime fallback 查詢路徑。

**結果**（2026-08-17，全量 57 秒）：
- DEM10B 填補 **999,851 格**（佔 DEM5 nodata 54.1M 的 1.8%）。
- 其餘 5,300 萬格是公海 — DEM10B 的 `その他,-9999` sentinel 也沒有 sea 語義，
  在公海同樣 nodata，所以不填。
- 填補集中在特定區域：如 503354（高知南岸）nodata 100% 被填補
  （108,620 格、0 殘留），示範點 (33.754, 133.544)：DEM5=no data →
  **DEM10B fallback=335.00 m**（與直接 `query` DEM10B archive 一致）。
- runtime 語義：`e = dem5.query(); if valid return; else return dem10.query()` —
  DEM5 有值時（如小豆島 204.33m）DEM10 僅作後備，不覆蓋。

## Phase 5 狀態（Final tiling）

`tile` 命令把 merged .bin（`merge --out-dir`）與 DEM10B layer 切成統一的
256×256 tile（規劃 §18-§22）：

- **固定 geographic grid**（規劃 §19）：DEM5 step = `1/18000°`（~6.2m）、
  DEM10 step = `1/9000°`（~12.4m）。已驗證所有 GSI 3次 mesh 角落都落在
  1/18000° 網格上（bounds × 18000 為整數），因此**不需 resample**。
  每個 layer 各有一組 `origin/step/tile_size`（規劃 §24）。
- **row-sweep**：依 tile 列由北往南，一次只保留一列的 tile accumulator
  （~22MB），讀取與該列重疊的 merged .bin / DEM10 raster 放置 — 記憶體有界，
  不會隨 mesh 數量線性成長（規劃 §29/§30）。
- **編碼**（規劃 §20/§21）：float32 → int16（1m），`i16::MIN` = NODATA；
  每 tile `elevation int16[65536]` + `source u8[65536]`。
- **壓縮**（規劃 §22）：zstd（level 10）→ `G5T1` tile 檔案
  （`<out>/dem5/y_tx.tile`、`<out>/dem10/...`），Phase 6 直接讀入 SQLite。
- `--check-lat/--check-lon`：從寫出的 tile 讀回該點 DEM5 + DEM10 值，
  驗證 round-trip。

**結果**（2026-08-17，全量 merge + tile 約 2 分鐘）：
- DEM5：**10,836 tiles**，633,143,706 valid / 77,004,390 nodata cells，
  zstd 1.11 GB（raw 1.42 GB）。
- DEM10：2,889 tiles，151,126,794 valid / 38,206,710 nodata cells，
  zstd 313 MB（raw 379 MB）。
- **一致性**：DEM5 有效格 633,143,706 == merge 的 A+B+C 總和
  （626,723,640 + 6,402,612 + 17,454）— 每格都保留，無遺失。
- **round-trip**：Phase 4 的 fallback 示範點在 tile 上重現
  `(33.754, 133.544): DEM5=no data, DEM10=335.0m`。
- 內點抽查（非格線上的點）：tile 值 == merged 值 quantize 後，完全一致。

## Phase 6 狀態（SQLite container + runtime query）

`build` 命令把 `tile` 產出的 `G5T1` 檔案讀進 SQLite（規劃 §23）：

- `metadata(key PK, value)`：`format_version` / `created_at` / `dataset` /
  `horizontal_datum=JGD2024` / `tile_size` / `compression=zstd` /
  `encoding=int16_meters` / `dem5.*` / `dem10.*`（origin + step，規劃 §24）。
- `elevation_tiles(layer, tile_x, tile_y, width, height, data)`：
  `data` = zstd(int16[65536] LE)；`layer` 5 = DEM5、10 = DEM10。
- `source_tiles(layer, tile_x, tile_y, data)`：zstd(u8[65536] source codes)。

`query-db` 實作 runtime 查詢（規劃 §25）：

```
lat/lon → global cell → tile 座標 → SELECT blob → zstd 解壓 → 取樣
DEM5 有值 → 回傳（含 layer + source）
DEM5 nodata/缺 tile → DEM10 tile → 回傳或 no data
```

**結果**（2026-08-17，全量 build 1.3 秒）：
- `elevation_tiles`：DEM5 10,836 + DEM10 2,889 = 13,725 筆（與 tile 數完全一致）。
- DB 大小 **540 MB**（tiles 1.4GB → source 壓縮後縮小）。
- 驗證：
  - `(34.50513, 134.25787)` → `285.0 m (layer=DEM5, source=DEM5A)` ✓
  - `(33.754, 133.544)` → `335.0 m (layer=DEM10, source=DEM10B)` ✓ fallback
  - `(34.7, 134.0)`（四國外）→ `no data` ✓

## Phase 7 狀態（Validation）

`validate-db` 命令提供回歸與覆蓋率驗證（規劃 §34-§37）：

- **golden coordinates**（§36）：讀 `tests/golden/elevation.json`，對每點查詢
  SQLite 並與期望值比對（DEM5 tolerance 10m、DEM10 20m）。點選在**地勢穩定的
  平地/緩坡**（城市、已交叉驗證的小豆島內陸）與一個 DEM10 fallback 區；
  尖峰山頂刻意排除（其高程對座標極敏感，5m 網格常抓不到最高格）。
  任一點失敗 → exit code 非零。`tests/golden.rs` 將其做成自動 regression
  （DB 不存在時自動 skip）。
- **coverage / source report**：掃描所有 elevation/source tiles，統計每 layer
  的 valid/nodata 格與 source 分佈（A/B/C/DEM10，§16）。

**結果**（2026-08-17，全量）：
- golden **7/7 passed**。
- coverage DEM5：10,836 tiles，633,143,706 valid / 77,004,390 nodata；
  source 分佈 A=626.7M B=6.4M C=17.5k —— 與 merge report 完全一致。
- coverage DEM10：2,889 tiles，151,126,794 valid，全為 DEM10 來源。

Phase 8 預告：Android 整合（SQLite + tile cache + zstd + lookup，§42）。
`query` 仍用 nearest-cell；bilinear interpolation（§26）與 route elevation
profile（§27）尚未實作。
- Phase 2 完成前**不要開始 bulk build**（規劃 §42）。