# gsi-dem

GSI 四國 DEM 資料轉換工具（Rust）。對應 `reference/gis-dem-converter.md` 規劃的
Phase 1（Inspector）與 Phase 2（Raster correctness）已完成。

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

# Debug render PNG（north-up；黑=未儲存格, 紫=NODATA, 藍=SEA, 青=內水, 灰階=地形）
cargo run --release -- render source/GSI/DEM5/5A/FG-GML-513462-DEM5A-20251208.zip --mesh 51346200 --output /tmp/mesh.png

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
  grid placement（full + partial）/ north-up 對映 / 錯誤處理。
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
│   ├── inspect.rs      inspect 命令
│   ├── query.rs        lat/lon -> elevation
│   ├── render.rs       debug PNG
│   └── validate.rs     DEM5 vs DEM10B 交叉驗證（Phase 2 acceptance）
├── gsi/
│   ├── archive.rs      ZIP / nested ZIP / entry reader
│   ├── xml.rs          streaming XML parser（quick-xml）
│   ├── model.rs        GsiDemRaster / SampleKind / DemSource
│   └── error.rs        DemError
└── raster/
    └── grid.rs         grid placement / coordinate mapping / lookup
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

**Phase 2 完成前不要開始 bulk build** 的條件已滿足，可進入 Phase 3（DEM5 merge）。

Phase 3 預告：`query` 目前用 nearest-cell；bilinear interpolation 需處理
NODATA neighbors。merge（A > B > C per-pixel）尚未實作。
- Phase 2 完成前**不要開始 bulk build**（規劃 §42）。