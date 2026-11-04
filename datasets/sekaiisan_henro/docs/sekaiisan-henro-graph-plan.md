# 協議會引導路線拓撲圖與區間推論計畫

> 上游文件：`datasets/sekaiisan_henro/docs/88sekaiisan-henro-route-pipeline-plan.md`（路線導入計畫，Phase 1–4）
>
> 本計畫是該文件的 **Phase 2/3 延伸實作**，不屬 Phase 1 immutable archive。
> Phase 1 已由 `python3 -m datasets.sekaiisan_henro` 完成：12 份 KML 的不可變快照已固定於
> `datasets/sekaiisan_henro/raw/snapshots/<sha256>/`，並由 `current.json` 指向目前快照。
> 本計畫在其之後，對四份 `routes/*.kml` 與四份 `temples/*.kml` 建立「可稽核的無向圖」與
> 「相鄰札所之間的候選路線」，**不建立任何 App / PMTiles 產物**。

## 1. 目的與資料語意

四國遍路世界遺產登錄推進協議會（`88sekaiisan.org`）公開的 `みち案内ルート` 是
「案內表示シートで案内するルート」的官方幾何參考。它不是可直接 routing 的圖：

- 單一線段通常只有 `FID` 與 `区分=みち案内ルート`，無名稱、札所編號、方向、連通順序或主線/支線語意。
- 多處線段互相斷開、端點未相接、存在橋樑/立體交叉/重疊/重複幾何（見 §2 量測事實）。
- 因此本計畫的目的**不是**製造一條「官方遍路道」或導航路徑，而是建立一份**可稽核、
  可人工審閱、有明確不確定性的無向圖**，並在 88 個札所之間推論「候選路線」供後續比較與視覺化。

**永不宣稱推論路徑為官方 / 導航路線。** 不做 OSM snapping、turn restriction、高程、
PMTiles、廁所、routing engine、自動歷史語意。

### 授權與發布界線

- 本機分析限定；所有 `output/sekaiisan-henro-*` 產物一律 gitignore，直到取得再散布許可。
- metadata、報告保留組織名稱、source URL、snapshot SHA、retrieved_at 與各檔 SHA-256。

## 2. 目前快照量測事實（`fec95f8d…`，2026-08-22）

作為設計基線，以下為目前 `current.json` 指向的快照的實際量測：

| 縣 | placemarks | LineStrings | 座標點 |
|---|---|---|---|
| Tokushima | 342 | 344 | 8,017 |
| Kochi | 474 | 479 | 12,779 |
| Ehime | 458 | 458 | 11,132 |
| Kagawa | 220 | 225 | 4,422 |
| **合計** | **1,494** | **1,506** | **36,350** |

- 札所：**恰好 88 個**獨一無二、有編號（1..88）的 Point。
- 寺廟到最近路線距離：min **7.05m**、median **55.46m**、p90 **133.08m**、max **288.76m**；
  `<=50m` 40 座、`<=100m` 71 座、`>100m` 17 座。
- 僅以端點做 1m/5m/10m clustering 得 82/72/67 個 component；**斷開拓撲是預期且必須被報告**，
  不得為了湊出 87 條區間而臆造連線。

這些量測直接決定 §4 的容差設計與 §6 的 confidence 門檻。

## 3. 範圍與非目標

**範圍（建置）**

- 可稽核的無向圖（nodes / edges / components）。
- 88 個札所的 anchor（最近路線投影 + 邊切分）。
- 相鄰札所（1→2 至 87→88）之間的候選路線（同一 component 內的加權最短路徑）。
- `88→1` 為**可選閉合**，單獨報告，不併入 87 條主區間。

**非目標（明確不做）**

- 不做 App / PMTiles / 向量 tile（屬上游文件 Phase 4，需發布許可後另案）。
- 不做 OSM snapping、turn restriction、高程、廁所、routing engine、歷史語意。
- 不把推論路徑標為「官方」或「可導航」。
- 不實作一般化 GIS framework；只做本資料集所需的最小功能。
- 不做自動歷史詮釋（哪些路段「是」歷史遍路道）。

## 4. 依賴決策

- **Python stdlib**：XML/JSON/hash/heapq/Dijkstra。
- **Shapely 2.x**（本機已有 2.1.2）：幾何型別、`STRtree`、線段切分（`line_interpolate_point` /
  split）、投影幾何運算。
- **不引入** `networkx`、`pyproj`。

### 4.1 本地度量投影

以固定於四國中心的 equirectangular（等距圓柱）投影做**本地度量**，僅用於拓撲與距離計算，
**輸出一律保留 WGS84（lon/lat）座標**，並提供逆變換回 WGS84。

- 投影（角度先轉 radians）：`x = R * radians(lon - lon0) * cos(radians(lat0))`、
  `y = R * radians(lat - lat0)`，`R = 6371008.8m`。
- 固定 `lon0 = 133.75`、`lat0 = 33.65`（四國範圍中央附近）。
- 逆變換：`lon = lon0 + degrees(x / (R * cos(radians(lat0))))`、
  `lat = lat0 + degrees(y / R)`。

**限制**：equirectangular 在跨經度較大的範圍有非等距誤差；四國全島跨度約 3.4° 經度、
2.4° 緯度，在 `lat0=33.65` 下的局部度量誤差為百分比級（距離失真隨與 `lat0` 的緯差增加），
對拓撲判定（相對長度比較、`<=5m` 容差）可接受，但不作為公制導航精度保證。任何進入
最終報告的「長度_m」都標示為「本地投影近似長度」，不宣稱高精度測量。`lat0`/`lon0`/`R`
寫死在程式常數並固定（deterministic）。

## 5. 產出（全部 gitignore）

```text
output/
  sekaiisan-henro-normalized.json          # Phase 1 標準化路線/札所
  sekaiisan-henro-topology-inventory.json  # Phase 2A 唯讀拓撲診斷
  sekaiisan-henro-graph.json               # Phase 2 無向圖（nodes/edges/components）
  sekaiisan-henro-temple-sections.json     # Phase 5 87+optional 區間候選路線
  sekaiisan-henro-graph-report.json        # Phase 6 QA 報告
```

可選、可進版控的覆寫檔：`datasets/sekaiisan_henro/graph_overrides.json` —— 僅在人工 QA 證明有需要
後才建立；schema 支援「寺廟 anchor 覆寫」「明確強制連接」「明確禁止連接」，各需 reason。
**不提供任何區間路徑覆寫**（不允許人為指定候選路線）。

## 6. 階段總覽

| 階段 | 名稱 | 產出 |
|---|---|---|
| 0 | 基線盤點與固定 live report | 目前快照量測事實（§2） |
| 1 | 標準化 | `normalized.json` |
| 2 | 保守拓撲 | `graph.json` |
| 3 | 圖 schema 定義 | （模型，與 2 同步） |
| 4 | 寺廟 anchors | `graph.json` 的 anchor 節點 + 報告 |
| 5 | 區間推論 | `temple-sections.json` |
| 6 | QA / 報告 | `graph-report.json` |
| 7 | 人工審閱 + 覆寫 | `graph_overrides.json`（僅有需要時） |

---

## Phase 0 — 基線盤點與固定 live report

- 只讀快照：解析 `current.json` 指向的 snapshot，固定列出 §2 的量測事實。
- 建立可重跑的 inventory 命令（見 §11），供開發與人工審閱對照。
- 不做任何改寫；這是後續所有階段的固定比較基準。

## Phase 1 — 標準化（`parser.py`）

**狀態：已實作。** 執行 `python3 -m datasets.sekaiisan_henro normalize`。目前 live snapshot 完整
accounted 1,494 Placemarks、1,506 LineStrings、36,350 個座標點與 88 札所；愛媛 16 個
無 FID Placemark 以 canonical geometry SHA-256 作穩定 fallback identity，並在 accounting
中明確記為 `missing_source_fid`，不以 source order 猜造 FID。

### 1.1 嚴格 KML parse

- 以 stdlib `xml.etree.ElementTree` 解析，支援 `MultiGeometry/LineString` 與直接 `LineString`
  （上游文件已要求）。每個 Placemark 可含多個 LineString 幾何 part。
- 札所 Point 由四份 `temples/*.kml` 解析；route parser 不得把 Point 當線遺失。
- 拒絕非法/缺失座標、少於兩個有效座標的線、不支援的 geometry，並於 report 明確列出，
  不靜默遺失。

### 1.2 穩定 source route ID

- 以 prefecture + source FID 為基礎；同 FID 含多個 LineString 時附加 geometry-part 序號。
  例如 `SHR_tokushima_42_2`（source FID 42 的第 2 條線）。
- **保留 source order**、`source_file`、`source_fid`、part、`prefecture`、
  raw description（原文字，不結構化）與 KML file reference 供診斷。

### 1.3 WGS84 驗證與 temple 編號

- 驗證所有座標 finite、經緯度在合理範圍（lon −180..180、lat −90..90）。
- temple number 從日文名稱（如 `1番 霊山寺`）解析出 1..88；**恰好 88 個且編號唯一**，
  重複或缺失即失敗（§12 acceptance）。

### 1.4 normalized.json 結構（示意）

```json
{
  "schema_version": 1,
  "snapshot_sha256": "fec95f8d…",
  "routes": [
    {
      "id": "SHR_tokushima_000001_1",
      "prefecture": "tokushima",
      "source_file": "tokushimaken_annairu-to36.kml",
      "source_fid": "0",
      "part": 1,
      "source_order": 0,
      "raw_description": "…",
      "geometry": {"type": "LineString", "coordinates": [[lon, lat], …]}
    }
  ],
  "temples": [
    {"id": "TEMPLE_1", "number": 1, "name_jp": "霊山寺",
     "geometry": {"type": "Point", "coordinates": [lon, lat]}, "source_file": "1-23.kml"}
  ],
  "accounting": {"routes": 1494, "linestrings": 1506, "points": 36350, "temples": 88}
}
```

## Phase 2 — 保守拓撲（`topology.py`、`projection.py`）

目標是把 source 線段切成**原子圖邊**，並建立節點，**只在證據充分時才連接**，其餘一律報告。

**Phase 2A 狀態：唯讀 inventory 已實作。** 執行
`python3 -m datasets.sekaiisan_henro topology-inventory`，輸出
`datasets/sekaiisan_henro/output/sekaiisan-henro-topology-inventory.json`。它只盤點 exact/proximity 端點、T 接點、
內部交叉、重疊及 endpoint-only components，不移動、切分或連接任何 source geometry。
目前 live 結果為 1m/5m/10m 各 82/72/67 components，另有 21 個 ambiguous crossings。
該命令本身不建立 graph；graph foundation 狀態如下。

**Phase 2B 狀態：exact-only graph 已實作。** 執行
`python3 -m datasets.sekaiisan_henro build-graph`，輸出 `datasets/sekaiisan_henro/output/sekaiisan-henro-graph.json`。
目前 live graph 為 1,953 nodes / 1,617 edges / 372 components；只連接 canonical shared
vertices 與 11 個明確 endpoint-on-line T 接點，21 個 ambiguous crossings 全數保持不連接，
`proximity_connections_applied=0`。

**Phase 2C 狀態：apply-proximity 已實作。** 執行
`python3 -m datasets.sekaiisan_henro apply-proximity`，在 exact-only graph 之上只加入保守、無歧義
的 proximity joins（見 §2.4 / §2.5 的 unambiguous 條件；clustering 與 T 接點規則保持
現狀，加入時不採 proximity snapping）。目前 live snapshot（`fec95f8d…`）結果：

- **Applied joins：379 = 324 endpoint cluster + 55 endpoint-to-line（T）**。
- **50 個 synthetic T nodes**（顯式 attached 到 target source edge；source edge 不在
  Phase 2C 改寫，Phase 3 traversal segmentation 才把 attachment 納入衍生拓撲）。
- **Rejected：37 cluster + 14 endpoint-to-line**（ambiguous / competing，一律只報告）。
- **5–20m gaps：76 = 50 endpoint pair + 26 endpoint-line**（只報告不連接）。
- **21 個 ambiguous crossings 維持不連接。**
- **components：372 → 53。**
- **source nodes / edges / provenance / lengths 保持 byte/value 不變**（synthetic joins 以
  顯式 `synthetic_joins` + `synthetic_nodes` 呈現，source edges/nodes 與 source length
  accounting 不被改動）。

輸出 `datasets/sekaiisan_henro/output/sekaiisan-henro-graph-proximity.json`。

### 2.1 度量變換

- 所有幾何先經 §4.1 equirectangular 變換為本地公尺座標；所有距離/長度計算都在此度量空間。
- 原始 WGS84 座標保留於 normalized 記錄；graph 節點同時存 WGS84 lon/lat 與投影座標（或標示來源）。

### 2.2 去除連續重複點但計數

- 同一線段內連續重複的座標點（`(lon,lat)` 完全相同）在**度量變換後**移除為單一點，
  但**計入**統計（重複點數、source 點數），於報告顯示。不得改變線的拓撲端點。
- 移除後仍須 `>=2` 個點，否則該線為 degenerate 並於報告列出。

### 2.3 完全共享端點/頂點 → 確定連接

- 若兩條 source 線「完全共享」一個端點或頂點（座標完全相同，經量化後），它們確定連接
  —— 這來自 source 幾何本身，非推論。

### 2.4 端點 clustering `<=5m`（candidate / 條件式自動）

- 對所有原子邊的端點做 clustering，容差 `<=5m`。
- **只有 unambiguous（一個 cluster 內端點可唯一對應）才自動連接**；ambiguous 只報告不連接。
- 每個 cluster 選 **deterministic representative** 節點（固定排序：依量化座標、再依 source
  排序的字典序最小的端點），所有端點指向它。
- **確定性 STRtree 候選排序與 cluster 直徑上限**（重要）：
  - 以 Shapely `STRtree` 的 `query_nearest`/`dwithin` 找端點候選，候選順序由
    STRtree 的 index 順序 + 固定 tie-break（量化座標 + source 排序）決定，確保 byte-deterministic。
  - cluster 的判定**不是 single-link**：按固定排序逐點建立 complete-link cluster，只有新端點與
    cluster 內**每一端點**距離都 `<=5m` 才能加入。這保證 cluster diameter `<=5m`，避免 A–B、
    B–C 各差 4m 但 A–C 差 8m 的「誤差鏈」間接跨越容差。

### 2.5 端點到線段內部 `<=5m`（T 節點，僅 unique）

- 端點投影到另一條線的**內部**（非端點）距離 `<=5m` 時，可建立 T 節點（把被投影線在此點切開）。
- **僅當 unambiguous / unique**：即該端點到該線內部有且僅有一個最近點、且該線只有一個候選
  （不被多個端點爭搶）時才自動建立；ambiguous 只報告。
- T 節點切分必須保留兩側 provenance（見 2.7）。

### 2.6 內部–內部交叉 → 偵測但**不**自動連接

- 兩條線的內部在空間上交會（crossing / intersect）時，**偵測並報告為 ambiguous**
  （可能是橋樑、立體交叉、資料誤差），**除非 source 幾何本身有共享頂點**（2.3），否則一律不自動連接。
- 這是因為無法從純平面幾何判斷上下穿越。

### 2.7 5–20m 近距缺口 → 僅報告

- 端點之間、或端點到線內部距離在 `(5m, 20m]` 的「近距但未達容差」組合**只寫入報告**
  （gap endpoints），**不發明連接器**，不做任何自動補線。

### 2.8 將 source 線切成原子圖邊、保留全部 provenance

- 依上述切分（T 節點、端點合併、共享頂點）把每條 source 線切成原子圖邊。
- 每條原子邊保留**來源 provenance 清單**：可含多個 refs（當多條 source 線重疊時），
  每個 ref 為 `(source_route_id, 原始片段範圍)`。
- **重疊**不消除：多個 provenance refs 可指到同一段原子邊的座標（或各自帶原始點集合），
  保留供 QA 與比較。
- 圖邊不 rewrite geometry 的實際點列，只以切分後座標呈現；每個原子邊有正長度。

### 2.9 確定性

- 所有候選排序、representative 選擇、切分順序都必須是確定性（固定 iterate source order +
  字典序 tie-break），使相同 snapshot + config 產出 byte-identical 結果。

## Phase 3 — 圖 schema（`graph.py`）

### 3.1 確定性 ID

- 節點 ID：由 **canonical 量化 WGS84 座標**（例如 lon/lat 各捨入到固定小數位）做 hash 前綴 +
  順序化。
- 邊 ID：由「兩個端點節點 ID 的有序對」+ 「排序後的 provenance 清單」做 hash，確保
  ID 是座標與來源的純函式（不依賴執行順序）。

### 3.2 節點 / 邊欄位

```json
{
  "schema_version": 1,
  "snapshot_sha256": "…",
  "projection": {"kind": "equirectangular", "lon0": 133.75, "lat0": 33.65, "R": 6371008.8},
  "nodes": [
    {"id": "N_…", "lon": 133.xxx, "lat": 33.xxx,
     "kind": "endpoint|t_junction|interior|temple_anchor|snap_cluster_rep",
     "source_refs": ["SHR_tokushima_…", …]}
  ],
  "edges": [
    {"id": "E_…", "from": "N_…", "to": "N_…",
     "coordinates": [[lon, lat], …],
     "length_m": 123.45,
     "provenance": [{"route_id": "SHR_…", "segment": [0.0, 0.42]}],
     "flags": {"has_overlap": true, "t_junction": false}}
  ],
  "components": [{"id": "C_0", "node_count": 12, "edge_count": 11}],
  "synthetic_joins": []
}
```

- **無向圖**；路徑遍歷記錄 forward/reverse 方向（邊本身的 from/to 只是存檔順序，
  遍歷時依行走方向記 `direction: "forward"|"reverse"`）。
- **Synthetic joins 獨立表示**：任何非 source 幾何的「人為連接」（例如 §7 覆寫的強制連接）
  一律放 `synthetic_joins`，**永不靜默混入 source 幾何**；預設空。
- `length_m` 為本地投影近似長度（見 §4.1 限制說明）。

## Phase 4 — 寺廟 anchors（`anchors.py`）

**狀態：已實作。** 執行 `python3 -m datasets.sekaiisan_henro build-anchors`，把 88 個札所投影到
最近 source edge 並切分 derived traversal edges；confidence 分 `near`(<=50m) /
`offset`(>50–150m) / `review_required`(>150m 或最近邊 tied)。目前 live snapshot
（`fec95f8d…`）結果：

- **88 total anchors，81 usable（near/offset），7 review_required。**
- **Safe shared-node tie resolution：temples 2 / 21 / 51 的 `shared_node_tie` 解析為既有
  確切節點；temple 71 維持 true tie（不猜選投影或 anchor node，標 unusable 供審）。**
- **Traversal topology：1,733 edges / 2,069 nodes；components 53 → 53（不增不減，僅
  subdivide）。**
- **最大重建誤差約 4.55e-13m**（derived traversal edge 重建長度 vs source edge weights）。
- source nodes/edges/synthetic joins/route_sources/source length accounting 保持
  byte/value 不變；temple 點原樣保留、temple→邊的偏移線絕不作為 edge。
- review-required anchors 一律排除於自動 pathing（§4.1）。

輸出 `datasets/sekaiisan_henro/output/sekaiisan-henro-graph-anchors.json`。

對每個札所 Point：

1. 在度量空間以 STRtree 找最近原子邊；把 temple 點投影到該邊，並在投影點**切分邊**以建立
   anchor 節點（`kind="temple_anchor"`）。
2. **不移動 temple 點**；temple 座標原樣保留。
3. **不把「temple→最近邊的直線連接器」視為 source route**；它只是一個量測與 anchor 節點的
   連帶關係，不放進圖邊的 source geometry（僅在報告標示距離與方向）。
4. anchor 節點保留 `temple_number`、`distance_m`、該邊的**候選邊清單**（多個等近邊時列全部）。

### 4.1 confidence 分類

| 類別 | 條件 |
|---|---|
| `near` | 投影距離 `<= 50m` |
| `offset` | 投影距離 `50m < d <= 150m` |
| `review_required` | `> 150m`，或最近候選有歧義（多個等近邊無法唯一決定） |

- **自動候選 pathing 只限 `near` / `offset`**；`review_required` 一律排除，直到有明確
  覆寫（§7）才納入。不靜默強制連線。
- 多條 nearest edge tied 時，只有在**每條候選的最近投影都落在同一個既有 exact graph
  node** 才以 `shared_node_tie` 安全解析；只共享某個端點但實際投影不同、或投影位於不同
  interior，仍維持 `review_required`，不任意挑選 edge。
- 保留距離與 source edge 候選清單供人工審閱。
- 基線量測（§2）：40 座 `near`、31 座 `offset`（50–100 之間）、17 座 `>100m` 進 `review_required`
  （其中 >150 需特別審）。

## Phase 4b — 區間 corridor（`build-section-corridors`）

**狀態：已實作並為現行 line-classification 主模型。** 執行
`python3 -m datasets.sekaiisan_henro build-section-corridors`，在 effective undirected graph
（只有 `traversal_edges` + `synthetic_joins`；**不**在 source `edges` 上 routing、
**不**用 temple 偏移當 edge/cost）上，對 88 個札所兩兩相鄰（1→2 至 87→88）計算
**section corridor**：

- `SEC_i_(i+1)` = 所有「落在某一條從 temple i anchor 到 temple i+1 anchor 的 SIMPLE
  path 上」的 effective edge 的 **union**。
- **其他所有 usable temple anchor node 禁止作為內部 transit node**（forbidden）：任何
  allowed simple s-t path 都不得通過其他 temple anchor。
- 保留所有 reconnecting 建議分支（**無 1.15x / 長度門檻**）；排除 dead ends、透過單一
  articulation 附著的 lollipop cycle、以及會經過其他 temple anchor 的相反環島路線。
- **不列舉 simple paths**：先移除 forbidden 其他 anchor nodes，用確定性 undirected
  vertex-biconnected edge blocks（Tarjan edge stack，正確支援 parallel edges）+
  block-cut forest，找 s/t 之間唯一的 block-cut-tree path 並 union 其上所有 edge blocks
  —— 即落在某條 allowed simple s-t path 上的精確 edge set。
- status：`corridor`（cyclomatic E−V+1 == 0）/ `branched_corridor`（>0）/
  `disconnected`（無 allowed path）/ `anchor_review_required`（任一側 anchor 不可用）。
  `s==t` 是 zero-edge corridor（shortest length 0）；positive/zero weights 不影響 corridor
  membership；synthetic joins 保持 explicit。

目前 live snapshot（`fec95f8d…`）結果：

- **28 corridor、23 branched、23 disconnected、13 anchor_review_required**。
- **2,112 effective edges；718 assigned_once、66 assigned_multiple、1,328 unassigned；
  850 assignments；無 shared-anchor conflicts。**

輸出 `datasets/sekaiisan_henro/output/sekaiisan-henro-section-corridors.json` 與
`datasets/sekaiisan_henro/output/sekaiisan-henro-section-corridor-edges.geojson`（byte-deterministic、無
timestamp、atomic write）。另含 global effective-edge classification（每條 effective edge
的 sorted section_ids、assignment_count、assigned_once/multiple/unassigned、
`source_edge_id`）與 by-status / by-classification accounting（不宣稱 assignment 是
exclusive）。

## Phase 5 — 區間推論（`sections.py`）

**狀態：加權最短路徑已實作並保留為 QA / reference 模型（非 line-classification 主模型；
主模型為 §Phase 4b corridors）。** 執行 `python3 -m datasets.sekaiisan_henro build-sections`
（在 effective undirected graph 上做加權最短路徑；權重 = `length_m`/`distance_m`，
**不**在原始 source `edges` 上 routing、**不**用 temple 偏移距離當成本）。目前 live
snapshot（`fec95f8d…`）結果：

- **34 candidate、17 ambiguous、23 disconnected、13 anchor_review_required**。
- **38 條 primary path 使用 synthetic joins**。
- 替代路徑 = 逐一排除 primary 每條邊重跑；`closure_88_1` = `{"status":"not_requested"}`。
- 永不宣稱 resolved/official/navigable。

輸出 `datasets/sekaiisan_henro/output/sekaiisan-henro-temple-sections.json`（byte-deterministic，無 timestamp）。

### 5.0 目前無 corridor 的區間

corridor（§Phase 4b）與加權最短路徑是兩套獨立分類模型；下列區間在 corridor 模型下
**沒有 corridor**（含斷開與 anchor review），屬合法、可交付結果 —— **缺少 corridor
不代表缺少官方路線**，不得臆造連線：

- **disconnected（23）**：`5→6`、`6→7`、`7→8`、`11→12`、`17→18`、`23→24`、
  `27→28`、`28→29`、`37→38`、`38→39`、`40→41`、`43→44`、`47→48`、`51→52`、
  `53→54`、`54→55`、`58→59`、`59→60`、`63→64`、`64→65`、`77→78`、`83→84`、
  `87→88`。兩端 anchor 可用，但 effective graph 無 allowed path，不推斷跨 component 連線。
- **anchor_review_required（13）**：`9→10`、`10→11`、`44→45`、`45→46`、`67→68`、
  `68→69`、`69→70`、`70→71`、`71→72`、`79→80`、`80→81`、`81→82`、`82→83`。
  由 temples 10 / 45 / 68 / 69 / 71 / 80 / 82 的不可用 anchor 引起，不予自動 pathing。

### 5.1 最短路徑

- 對**同一 component** 內的相鄰札所（`temple i` 與 `temple i+1`，經其 anchor 節點）做
  加權最短路徑，權重 = 邊 `length_m`，使用 **stdlib Dijkstra**（heapq）。
- 若兩 anchor 不在同一 component，狀態為 `disconnected`，**不臆造跨 component 路徑**。

### 5.2 替代路徑（replacement path）

- 對主最短路徑的**每一條邊逐一排除**（replacement path），再算一次最短路徑，取其中最短者為第二候選。
- 若第二候選長度 `<= 1.15 × 主路徑`，判定為 `ambiguous` 並**同時保留兩條**（`primary` + `alternative`）；
  否則主路徑視為唯一候選（仍標 `candidate`）。
- **永不自動把候選標為 resolved**。所有區間都是候選/ambiguous，人工審閱才是最終決定。

### 5.3 輸出狀態

每個區間（1→2 … 87→88）狀態為其一：

- `candidate`：有唯一候選路徑。
- `ambiguous`：有接近等長的第二路徑（`<=1.15x`），兩條皆保留。
- `disconnected`：兩 anchor 不在同一 component。
- `anchor_review_required`：任一側 anchor 為 `review_required`，不予自動推論。

### 5.4 表示

- 記錄**有序邊 ID 清單** + 每條邊的**遍歷方向**（forward/reverse）；**不 rewrite 幾何**。
- 同一條邊可屬多個區間 ID（`edges` 可能同時在 section 1→2 與 2→3）。
- `88→1` 為可選閉合，**單獨報告**，不併入主區間。
- 恰有 **87 條主區間**記錄（`section 1→2` … `section 87→88`），無論成功與否都有 traceable 狀態。

### 5.5 temple-sections.json（示意）

```json
{
  "schema_version": 1,
  "snapshot_sha256": "…",
  "sections": [
    {"id": "SEC_1_2", "from_temple": 1, "to_temple": 2,
     "status": "candidate|ambiguous|disconnected|anchor_review_required",
     "primary": {"edge_ids": ["E_…"], "directions": ["forward", "reverse"], "length_m": 3421.5},
     "alternative": {"edge_ids": […], "directions": […], "length_m": 3800.2},
     "anchors": {"from": {"temple_number": 1, "node_id": "N_…", "distance_m": 22.1, "confidence": "near"},
                 "to":   {"temple_number": 2, "node_id": "N_…", "distance_m": 300.2, "confidence": "review_required"}}}
  ],
  "closure_88_1": {"status": "not_requested"}
}
```

## Phase 6 — QA / 報告（`report.py`）

所有結果必須能從 stable ID 回查 **snapshot SHA / source file / FID / part**。報告包含：

1. **raw accounting**：Placemark / LineString / 座標點 / 重複點 / degenerate / 拒收，逐縣。
2. **source 長度覆蓋**：每條 source 線的原始長度 vs 切分後原子邊長度總和，比對。
3. **圖統計**：node / edge / degree / component 數、每 component 大小、代表節點。
4. **snap actions**：每次端點 clustering / T 節點連接的記錄（candidate vs 自動）。
5. **candidate / rejected joins**：`<=5m` 自動、`<=5m` ambiguous、5–20m gap。
6. **ambiguous crossings**：內部–內部交會清單（含兩條 source 線 ID）。
7. **duplicate / overlap**：重複幾何、重疊 provenance 的邊。
8. **temple distance / confidence**：88 座全數，含距離、confidence、候選邊清單。
9. **87 區間狀態**：每條 status + 主/替代路徑長度；gap 端點（5–20m 未接）。
10. **確定性**：相同 snapshot + config 產出 byte-identical。

**derived 產出內不含 timestamp**（snapshot metadata 已攜帶 `retrieved_at`）；輸出
byte-deterministic。

## Phase 7 — 人工審閱與覆寫（僅有需要時）

1. 先看 Phase 6 報告；只有當人工審閱證明需要（例如某 `review_required` anchor 確定應連、
   某候選連接確屬錯誤）才建立 `graph_overrides.json`。
2. Schema 支援三種覆寫，各需 `reason`：
   - `temple_anchor_override`：指定某 temple 改用指定邊/節點作 anchor。
   - `forced_join`：明確強制連接兩個節點（加入 `synthetic_joins`，不混入 source geometry）。
   - `forbidden_join`：明確禁止某候選連接。
   - **無**區間路徑覆寫（不允許人為指定候選路線）。
3. 驗證覆寫引用的 ID 存在、snapshot 行為（覆寫綁定 snapshot SHA，snapshot 不同則標 stale）。
4. 覆寫**永不編輯 raw geometry**；報告列出所有 applied / stale overrides。
5. `graph_overrides.json` 是唯一可能進版控的圖相關檔案；只有在本階段證明需要後才建立並進版控。

## Phase 8 — QGIS review-pack / report exporter（`build-review-pack`）

**狀態：已實作。** 執行 `python3 -m datasets.sekaiisan_henro build-review-pack`，產生給 QGIS 人工
審閱用的唯讀、確定性 review pack（輸出 `datasets/sekaiisan_henro/output/sekaiisan-henro-review/`）。先驗證所有
kind / dataset / snapshot 一致與跨輸入 accounting 基本 identity，全部 payload 在記憶體
建好後用既有 atomic writer 逐檔寫出（byte-deterministic、無 timestamp）：

- `source-edges.geojson`（anchored source edges，QGIS 底圖用）
- `topology.geojson`（每個 applied/rejected <=5m candidate、5–20m gap、ambiguous
  crossing 各一 feature，含 `review_kind` / applied / distance / reason / route IDs /
  priority / used-by-primary|alternative section IDs）
- `anchors.geojson`（每座寺廟一個 temple Point；每個已有確定投影的位置另有 offset
  LineString，`review_visualization_only=true`，**永不是** graph edge；unresolved tied anchor
  只有 temple Point，resolved `shared_node_tie` 仍有 offset；含 anchor review ID /
  confidence / usable / candidate+chosen/resolved edge IDs）
- `sections.geojson`（由 ordered `traversal_edges` + `synthetic_joins` 依方向重建的
  primary / alternative path LineStrings；宣稱長度 vs effective edge weights 須在 1e-6 m
  內符合，不符即 fail；disconnected / review-required 無 geometry）
- `review-items.json`（**產生式的 immutable review queue，不是 decisions 檔**：每 topology
  record + 每 temple anchor + 每 section 各一筆；含 stable review_id / category / priority /
  current automated status / references / `allowed_decisions` / `evidence_required` /
  空的 `decision: null`；rerun 會覆寫產生式 queue，decisions 屬未來獨立的
  `graph_overrides` / `review-decisions` 檔）
- `report.json`（snapshot、input accounting、output feature/item 數、review priority 計數、
  unresolved focal 計數、preservation notes、檔案清單）

Priority policy：**P0** = review_required anchors、ambiguous/disconnected/
anchor_review_required sections、被 primary path 使用的 applied joins；**P1** = 只被
alternative 使用的 applied joins、所有 rejected <=5m candidates、5–20m gaps、ambiguous
crossings；**P2** = 其他 accepted anchors / candidate sections / 未使用的 applied joins。

目前 live snapshot（`fec95f8d…`）結果：

- **Output features：source edges 1,617、topology 527、anchors 175、sections 68、
  review items 702。**
- **Priorities：P0 = 168、P1 = 158、P2 = 376。**
- 產生式輸出確定性；synthetic joins 的 section crossref（primary 與 alternative 分開）
  由 exporter 交叉比對；本 exporter **不寫 decisions**（人工決定記到未來獨立的
  `graph_overrides` / `review-decisions` 檔）。

---

## 7. 程式模組與 CLI

### 7.1 模組（新增於 `datasets/sekaiisan_henro/`）

| 模組 | 職責 |
|---|---|
| `parser.py` | routes/temples 解析、stable source ID、WGS84/temple 驗證 |
| `projection.py` | equirectangular 本地投影 + 逆變換 + 限制說明 |
| `topology.py` | 端點/T 節點/交叉/近距、原子邊切分、provenance、STRtree 候選 |
| `graph.py` | 圖模型（nodes/edges/components）、adjacency、stdlib Dijkstra、確定性 ID |
| `anchors.py` | 札所最近邊投影、邊切分、confidence 分類、候選邊清單 |
| `sections.py` | 相鄰札所最短路徑 + replacement path、狀態 |
| `report.py` | QA 統計、traceability、確定性輸出 |
| `tests/` | fixture + 單元測試（§8） |

**不預先實作一般化 GIS framework**；每個模組只做本資料集需要的最小功能。

### 7.2 CLI（保留現有行為）

- `python3 -m datasets.sekaiisan_henro` 維持 fetch（不可變 archive），**不變**。
- 新增子命令（`--snapshot` 預設 `current`，輸出路徑確定性）：

```bash
python3 -m datasets.sekaiisan_henro normalize     --snapshot current
python3 -m datasets.sekaiisan_henro build-graph   --snapshot current
python3 -m datasets.sekaiisan_henro build-sections --snapshot current
python3 -m datasets.sekaiisan_henro report        --snapshot current
python3 -m datasets.sekaiisan_henro analyze       --snapshot current   # 便利：全部依序
```

- **staged 命令供診斷**：`analyze` 只是依序呼叫 normalize→build-graph→build-sections→report；
  各階段可獨立執行、獨立查診斷輸出，不必每次跑全管線。
- 若任一階段失敗，**不覆寫先前有效輸出**（atomic write：temp → fsync → rename）。

## 8. 測試（`datasets/sekaiisan_henro/tests/`）

以固定 fixture（從真實 KML 抽片段）測試，不依賴 gitignore 的完整 source：

- MultiGeometry 與直接 LineString；一個 Placemark 多 part 的 stable ID 與 accounting。
- 重複座標點去除與計數；`<2` 點 degenerate 拒收。
- 端點 clustering `<=5m` 自動、ambiguous 不自動；cluster 直徑上限（避免誤差鏈）。
- T 節點（端點到線內部 `<=5m`、unique vs ambiguous）。
- 內部–內部交叉：偵測、不自動連接（除非 source 共享頂點）。
- 重疊 provenance（多 source refs）與重複幾何報告。
- 斷開圖：不同 component 的札所 → `disconnected`，不臆造路徑。
- 札所投影與邊切分；temple 點不被移動；直線連接器不入 source geometry。
- temple 編號重複 / 缺失 → 失敗。
- 確定性 ID 與輸出：相同 fixture 跑兩次 byte-identical。
- 最短路徑正確性；`<=1.15x` 替代路徑判 `ambiguous`；失敗/需審 anchor。
- 可選 live integration report（非單元測試必要，因完整 source 已 gitignore）。

**驗證狀態（live snapshot `fec95f8d…`）：**

- **202 tests pass**（`python3 -m unittest discover datasets/sekaiisan_henro/tests`）。
- **corridor 實作額外以 200 個確定性隨機 multigraph brute-force simple-path oracle cases
  對照驗證**（Tarjan edge-block / block-cut corridor 與窮舉 simple-path union 一致）。
- **所有產出 byte-deterministic**（相同 snapshot + config 重跑 byte-identical）。

## 9. 階段驗收門檻

| 階段 | 驗收 |
|---|---|
| **1 標準化** | 依 snapshot metadata/accounting 完整 accounted 全部 source 幾何與 88 寺，否則失敗；目前基線另應得到 1,494 placemarks / 1,506 LineStrings / 36,350 點。 |
| **2/3 圖** | 每條邊有兩個有效節點與正長度；per-source 重建長度在明確小容差內；所有 snaps/report 確定性；無 ambiguous 交叉被自動連接。 |
| **4 anchors** | 88 座全數 accounted 且有明確 status；無靜默強制連線。 |
| **5 sections** | 恰有 87 條主區間記錄（無論成功與否），各 traceable / statused；無跨 component 臆造路徑。 |
| **6 輸出** | 相同 snapshot/config 產出 byte-deterministic；失敗不覆寫先前有效輸出（atomic write）。 |
| **7 覆寫** | 僅在證據充分後才引入；驗證 ID / snapshot 行為 / reason；不編輯 raw geometry。 |

## 10. 建議初始實作順序

1. **parser + fixtures**：先建立嚴格解析與 88 寺唯一編號驗證，凍結 normalized fixture。
2. **topology inventory（不含 snapping）**：先只盤點端點/交叉/近距，輸出 inventory 供審，
   確認量測與 §2 一致。
3. **保守 snaps / report**：實作端點 clustering、T 節點、交叉、近距，但先全部只報告，
   再逐步放行 unambiguous 自動連接。
4. **anchors**：88 座 confidence 分類與 anchor 節點。
5. **sections**：Dijkstra + replacement path 判 ambiguous。
6. **overrides**：僅當人工 QA 證明需要才引入 `graph_overrides.json`。

## 11. 風險與注意事項

- **斷開拓撲是資料特性**：不得為了湊 87 條區間而臆造連線；`disconnected` / `ambiguous` /
  `anchor_review_required` 是合法、可交付的結果。
- 本地投影僅為相對比較用，不作為公制導航精度保證（§4.1）。
- 任何推論路徑都不是官方/導航路線；命名與 attribution 依上游文件使用
  「協議會みち案內表示ルート / 協議會引導路線參考」。
