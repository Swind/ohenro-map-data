# 步行遍路 Arukihenro：更新到正規化資料

```bash
python3 -m datasets.arukihenro_routes run
```

需要 Python 3.11+，只用標準函式庫。一鍵入口是 **`run`**；無子命令與
`fetch` 沿用原本快取模式（更新 legacy archive 請用 `fetch --force`）。

## 更新與來源保存

來源為 <https://ohenro.jp/blog/arukihenro/> 四縣列表頁、路線 HTML、內嵌 Google
My Maps KML 與既有明確列出的別格路線。不需登入，不下載照片本體。
每次 `run` 重新取得 HTML 與 KML：單 worker、預設延遲 0.3 秒、timeout 30 秒、
網路失敗最多 3 次。HTML 不變不能代表 My Maps 未更新，因此也會重新下載 KML。

先下載至暫存目錄，檢查四縣列表非空、manifest／列表一致、至少 88 路線、
title／map metadata、KML XML／SHA-256，再正常化驗證。KML 下載失敗、缺檔、
normalization warnings 或 accounting 不符都停止，保留先前 current 與產出。

成功後保存 `raw/snapshots/<sha256>/`（indexes/、routes/、manifest.json），更新
`raw/current.json`；舊快照保留。hash 涵蓋全部檔案內容及相對路徑。
已有 legacy `raw/manifest.json` 平面 archive 也可用 `build`。有 current.json 時，
一鍵管線及 `normalize` 都優先使用其 snapshot。

## 產出與未變更處理

- `output/arukihenro-routes.json`：既有 schema v1，欄位與分類規則沿用。
- `reports/pipeline.json`：archive_sha256、source_sha256（程式碼 hash）、
  output/output_sha256/size、summary（各類數量及 degenerate_line_count）。

每次在暫存檔重算輕量 normalization 並驗證。若 JSON、程式碼與現有 output hash
皆未變，**不替換 output**，只更新來源報告；WordPress 頁尾變更不會重發產出。
`--force` 強制重新發布。產出／報告各自 atomic replace，不是兩檔單一交易；
中斷時重跑可修復。

來源限制：40→41、68→69 頁沒有 KML，保留空 maps；其他頁突然缺 map 會停止。
65→66 的 My Maps 有一條單頂點導航線，保留座標、報告 degenerate_line_count，
不臆造線段或悄悄刪除。

## 分步、離線與隔離實跑

```bash
python3 -m datasets.arukihenro_routes run --local
python3 -m datasets.arukihenro_routes build
python3 -m datasets.arukihenro_routes run --force
python3 -m datasets.arukihenro_routes validate

python3 -m datasets.arukihenro_routes run \
  --data-dir /tmp/opencode/arukihenro-check/raw \
  --output-dir /tmp/opencode/arukihenro-check/output \
  --reports-dir /tmp/opencode/arukihenro-check/reports
```

下載不可用時，把完整 legacy archive（indexes/、routes/、manifest.json），或
完整 snapshot archive（current.json、snapshots/）放入 `datasets/arukihenro_routes/raw/`，
再用 `--local`。不要把 legacy `fetch` 寫出的平面資料與 current snapshot 混用。
一鍵流程有來源鎖；勿同時用分步命令修改相同資料。資料與報告皆不提交 Git。

下游協議會比對及統合 POI 仍由各自管線重建：

```bash
python3 -m datasets.sekaiisan_henro run \
  --arukihenro datasets/arukihenro_routes/output/arukihenro-routes.json
python3 -m unittest discover datasets/arukihenro_routes/tests
```

## 實跑紀錄

2026-11-05 全量線上下載及隔離建置成功（`/tmp/opencode/arukihenro-check/`），
snapshot `141a6a2d…`：90 routes / 91 maps / 324 lines / 933 points，
385 點帶照片、0 warnings、1 條單頂點來源線。獨立 `validate` 通過；再次
`build` 確認跳過發布且 output 修改時間不變。36 項測試通過。
