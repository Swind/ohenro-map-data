# Android 端離線高程查詢 — 實作指南

本文說明如何用 `output/shikoku-elevation.sqlite` 在 Android App 內做
`lat/lon -> elevation` 查詢。這是 gsi-dem（Rust 資料工廠）的**消費者端**指南：
App 不碰 GSI GML / ZIP / merge / tile 產生等邏輯，只讀最終 SQLite
（參考 `reference/gis-dem-converter.md` §8/§19/§20/§23/§25/§46）。

資料檔案：`output/shikoku-elevation.sqlite`（540 MB，2026-08-18 build，shikoku-elevation.sqlite）

另有 **DEM10-only 精簡版**：`output/shikoku-elevation-dem10.sqlite`（126 MB，
只有 10m DEM layer，解析度較粗、體積小 76%）。適用於只需粗略海拔/地勢概覽、
不要求 5m 精度的用途。兩者共用同一套 schema 與查詢演算法（見下文），差異只在
layer 數與 grid 解析度。

---

## 1. 資料庫 Schema

三個 table（規劃 §23）：

```sql
CREATE TABLE metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE elevation_tiles (
    layer  INTEGER NOT NULL,   -- 5 = DEM5, 10 = DEM10
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    width  INTEGER NOT NULL,   -- 恆為 256
    height INTEGER NOT NULL,   -- 恆為 256
    data   BLOB NOT NULL,      -- zstd(int16[65536] LE)
    PRIMARY KEY (layer, tile_x, tile_y)
);

CREATE TABLE source_tiles (
    layer  INTEGER NOT NULL,
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    data   BLOB NOT NULL,      -- zstd(uint8[65536])
    PRIMARY KEY (layer, tile_x, tile_y)
);
```

### metadata 內容（key -> value）

| key | 值（目前 build） | 說明 |
|---|---|---|
| `format_version` | `1` | 格式版本 |
| `dataset` | `shikoku` | 資料集 |
| `horizontal_datum` | `JGD2024` | 水平基準 |
| `tile_size` | `256` | tile 邊長 |
| `compression` | `zstd` | 壓縮 |
| `encoding` | `int16_meters` | 編碼 |
| `created_at` | unix epoch 秒 | build 時間 |
| `dem5.origin_lat` | `34.583333333` | DEM5 網格北邊界 |
| `dem5.origin_lon` | `132.0` | DEM5 網格西邊界 |
| `dem5.step_lat` | `0.0000555556` (=1/18000) | 每格緯度 |
| `dem5.step_lon` | `0.0000555556` | 每格經度 |
| `dem10.origin_lat` | `34.583333333` | DEM10 網格北邊界 |
| `dem10.origin_lon` | `132.0` | DEM10 網格西邊界 |
| `dem10.step_lat` | `0.0001111111` (=1/9000) | 每格緯度 |
| `dem10.step_lon` | `0.0001111111` | 每格經度 |

---

## 2. 查詢演算法（O(1)，無需索引掃描）

### 2.1 讀 grid metadata（啟動時讀一次）

```kotlin
data class Grid(val originLat: Double, val originLon: Double,
                val stepLat: Double, val stepLon: Double, val tileSize: Int)
```

從 `metadata` 表讀 `dem5.*` 與 `dem10.*`，建兩個 Grid。

### 2.2 lat/lon -> tile + pixel（純數學）

```kotlin
// 回傳 (tileX, tileY, pixelX, pixelY)
fun locate(grid: Grid, lat: Double, lon: Double): LongArray {
    // 全域 cell 座標（north-up：row 0 = 北）
    val gx = Math.floor((lon - grid.originLon) / grid.stepLon).toLong()
    val gy = Math.floor((grid.originLat - lat) / grid.stepLat).toLong()
    // tile 座標（負數向負無限取整，用 floorDiv / floorMod 處理）
    val tx = Math.floorDiv(gx, grid.tileSize.toLong())
    val ty = Math.floorDiv(gy, grid.tileSize.toLong())
    val px = Math.floorMod(gx, grid.tileSize.toLong()).toInt()
    val py = Math.floorMod(gy, grid.tileSize.toLong()).toInt()
    return longArrayOf(tx, ty, px.toLong(), py.toLong())
}
```

> 注意：**必須用 `floorDiv`/`floorMod`**（向負無限取整），不是 `/` 和 `%`
> （向零取整）。東半球的 `gx` 一般為正，但南/西邊界可能出現負數。

### 2.3 讀 + 解壓 tile

```kotlin
val blob: ByteArray = db.query(
    "SELECT data FROM elevation_tiles WHERE layer = ? AND tile_x = ? AND tile_y = ?",
    layer, tx, ty
) ?: return null   // 該 tile 不存在 -> nodata

val raw = Zstd.decompress(blob)   // 131072 bytes
val idx = py * 256 + px
val elevation = (raw[idx*2].toInt() and 0xFF) or ((raw[idx*2+1].toInt() and 0xFF) shl 8)
// elevation 是 i16 little-endian
```

**int16 編碼（規劃 §20）**：
- 單位 = 1 公尺（`elevation = round(meters)`）
- `i16::MIN = -32768` = **NODATA**（無資料）
- 其他值 = 高程公尺數（含負值，如海底）

**source tile**（選擇性，用於顯示資料品質）：
```kotlin
val srcBlob = db.query(
    "SELECT data FROM source_tiles WHERE layer = ? AND tile_x = ? AND tile_y = ?", ...)
val srcRaw = Zstd.decompress(srcBlob)   // 65536 bytes
val sourceCode = srcRaw[idx]
```

source code（規劃 §16）：
| 值 | 來源 |
|---|---|
| 0 | NODATA |
| 1 | DEM10B |
| 2 | DEM5C |
| 3 | DEM5B |
| 4 | DEM5A |

### 2.4 Fallback（規劃 §17/§25）

```
查 DEM5 -> 有值(非 NODATA) -> 回傳 DEM5
       -> NODATA 或缺 tile  -> 查 DEM10 -> 有值 -> 回傳 DEM10
                                       -> NODATA -> 回傳 "no data"
```

```kotlin
fun elevation(db: Db, lat: Double, lon: Double): Result? {
    val g5 = locate(gridDem5, lat, lon)
    val dem5 = readTile(db, LAYER_DEM5, g5)
    if (dem5 != null && dem5.elevation != NODATA) return Result(dem5.elevation, "DEM5")
    val g10 = locate(gridDem10, lat, lon)
    val dem10 = readTile(db, LAYER_DEM10, g10)
    if (dem10 != null && dem10.elevation != NODATA) return Result(dem10.elevation, "DEM10")
    return null
}
```

> DEM10 的網格 step 是 DEM5 的兩倍，所以同一個 lat/lon 在 DEM10 是**另一組** tile
> 座標 — 用 `locate(gridDem10, ...)` 重新算，**不能**沿用 DEM5 的 tx/ty/pixel。

---

## 3. 效能注意事項

- **tile cache**：`HashMap<Pair<Int,Long>, i16Array>`，key = (layer, tx, ty)。
  同一 tile 只解壓一次（每次查詢解壓 256KB 去取 1 個 sample 太浪費）。
- **只查一次 DB**：`elevation_tiles` 是 `(layer, tile_x, tile_y)` 主鍵，
  SQLite B-tree 直接命中單一列，不需掃描。
- **路線剖面**（§27）：對每個 route vertex 查詢會解壓大量 tile → 建議先對整條
  路線收集所有需要的 tile，一次讀完。

---

## 4. 驗證（regression）

用 `gsi-dem/tests/golden/elevation.json` 的點對照 App 查詢結果：
- tolerance：DEM5 = 10m、DEM10 = 20m
- 已知值：
  - `(34.50513, 134.25787)` 小豆島內陸 → 285 m (DEM5)
  - `(34.508, 134.296)` 寒霞渓 → 272 m (DEM5)
  - `(33.839, 132.766)` 松山 → 24 m (DEM5)
  - `(33.559, 133.531)` 高知 → 3 m (DEM5)
  - `(34.07, 134.55)` 徳島 → 1 m (DEM5)
  - `(34.289, 133.797)` 丸亀 → 5 m (DEM5)
  - `(33.754, 133.544)` 高知南岸 → 335 m (**DEM10 fallback**)

---

## 5. 參考實作（Rust，可直接對照翻譯）

查詢邏輯在 `gsi-dem/src/db.rs`（`query_db` / `sample_layer`），
tile 座標數學在 `gsi-dem/src/tile/grid.rs`（`global_cell` / `tile_of`）。
App 端就是把它們翻成 Kotlin。

注意：`tile_size` 固定 256；若未來 build 改 `tile_size` 或 `encoding`，一律以
`metadata` 表的值為準，不要 hardcode。
