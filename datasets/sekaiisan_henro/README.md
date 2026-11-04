# 世界遺產協議會：四國路線一鍵管線

```bash
python3 -m pip install -r datasets/sekaiisan_henro/requirements.txt
python3 -m datasets.sekaiisan_henro run
```

需要 Python 3.11+、Shapely；不需 Docker／Java。
一鍵命令是 **`run`**；既有無子命令與 `fetch` 仍只下載 raw archive。

## 來源與更新

來源：<https://88sekaiisan.org/restroommap/>，KML 位於
<https://88sekaiisan.org/map/data/>。每次 `run` 取得固定的 12 檔（四縣路線、
四組札所、四縣廁所），逐檔 SHA-256 再組合為 snapshot hash。新內容存入
`raw/snapshots/<sha256>/`，舊版保留，相同內容重用。無需登入。
HTTP 失敗會重試；整組下載、XML、normalization（含 88 札所）驗證成功後，
才更新 `raw/current.json`。

建置前重新校驗 12 檔 hash、metadata 與整組 snapshot hash。輸入、bridge_m、
可選參考資料 hash、程式碼、Shapely 版本及所有產出 size/hash 都未變則跳過。
`--force` 強制重建；舊版沒有 pipeline.json 的產出首次會重建。

## 流程與產出

```text
normalize → topology-inventory → build-graph → apply-proximity
→ build-anchors → build-sections → build-section-corridors
→ export-plan-graph → build-review-pack
→ 可選 arukihenro-attribution（source 與 traversal 兩層）
→ 跨檔驗證 → 發布
```

預設 `datasets/sekaiisan_henro/output/`，下列省略 `sekaiisan-henro-` 前綴：
- `normalized.json`：路線、88 札所、廁所及 toilet_defects。
- `topology-inventory.json`：接點／缺口診斷。
- `graph.json`、`graph-proximity.json`、`graph-anchors.json`：三階段拓撲。
- `temple-sections.json`：87 相鄰區間候選。
- `section-corridors.json`、`section-corridor-edges.geojson`：87 corridors 與 edge 歸屬。
- `plan-graph.json`：schema v2 topology/geometry 分離的瀏覽器 graph。
- `review/`：source-edges/topology/anchors/sections GeoJSON、review-items/report JSON。
- 可選 `arukihenro-attribution.json`、`arukihenro-attribution-traversal.json`。

核心共 15 檔，可選比對加入後為 17 檔。`--bridge-m` 預設 5m，只影響瀏覽器
plan graph。disconnected、ambiguous、anchor_review_required 與 toilet_defects
是合法診斷，不為了通過建置而補線或猜座標；區間是候選，不是導航保證。

驗證包含 snapshot/dataset identity、source preservation、既有 graph validators、
accounting、87 corridor IDs、corridor GeoJSON 重建比對、review pack 重建比對
（含路徑幾何與長度），以及 plan graph ID 唯一性、端點、geometry lookup、非負權重。
`validate` 另比對全部已發布檔案 size/hash 與驗證摘要。

全程使用新暫存目錄，失敗保留舊產出。成功後逐檔 atomic replace，最後寫入
`reports/pipeline.json`（inputs/build_config/validation/outputs size+hash）。
不是多檔單一交易；發布中斷需重跑。完整 log 可用 shell 重導保存。
一鍵命令有來源鎖；勿同時用分步命令修改相同輸入／產出。資料皆不提交 Git。

## 分步與選項

```bash
python3 -m datasets.sekaiisan_henro run --local  # 使用 current snapshot，略過下載
python3 -m datasets.sekaiisan_henro build        # 同上
python3 -m datasets.sekaiisan_henro run --force
python3 -m datasets.sekaiisan_henro validate
python3 -m datasets.sekaiisan_henro run \
  --arukihenro datasets/arukihenro_routes/output/arukihenro-routes.json

# 隔離實跑
python3 -m datasets.sekaiisan_henro run \
  --data-dir /tmp/opencode/sekaiisan-check/raw \
  --output-dir /tmp/opencode/sekaiisan-check/output \
  --reports-dir /tmp/opencode/sekaiisan-check/reports
```

`--arukihenro` 需要另一來源已完成 normalize；不指定時只管理核心 15 檔，
既有舊 attribution 不刪除，其 snapshot 可能已過時，以 pipeline.json outputs
清單為當次產出。review-items 是產生式清單，人工 decisions 請另檔保存。

下載不可用時，複製完整 raw/（current.json 及其指向的 snapshots/<sha256>/
metadata.json、routes/temples/toilets KML）後用 `--local`。僅散放 KML 不足以
建置，manifest/hash 也是來源證據的一部分。現有分步 CLI 仍可獨立執行。

```bash
python3 -m unittest discover datasets/sekaiisan_henro/tests
```

## 實跑紀錄

2026-11-05：完整下載／建置（含兩層 attribution）成功，17 檔發布到
`/tmp/opencode/sekaiisan-check/output/`；再跑 `run` 確認來源未變並跳過重建。
1506 lines、88 札所、594 廁所、1 個來源座標 defect；plan graph
2080 nodes / 1744 traversal edges / 443 joins。新驗證抓出並修正舊 exporter
在共用接點重複產生 bridge ID 的問題，僅合併重複 bridge，exact graph 不變。
220 項測試與獨立 `validate` 通過；正式資料未替換。
