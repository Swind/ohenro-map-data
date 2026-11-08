# 一日一斉おもてなし遍路道ウォーク資料來源

```bash
python3 -m datasets.omotenashi_henro_inspection
python3 -m datasets.omotenashi_henro_inspection fetch
python3 -m datasets.omotenashi_henro_inspection build
python3 -m datasets.omotenashi_henro_inspection validate
python3 -m datasets.omotenashi_henro_inspection run --local
```

預設 `run` 每次重新讀取官方頁、其點檢地圖及地圖程式宣告的路線 KML，下載並驗證來源，再離線建置及驗證完整輸出。沒有使用舊檔名作為靜默 fallback；官方頁改版造成無法唯一辨識路線時會失敗並保留原有選擇。`fetch` 保留只下載 archive 的用途；`build`、`validate` 不連網，使用 `current.json` 指定的本機快照。`run --local` 不下載，`run/build --force` 強制重建。可用 `--raw-dir`（舊名 `--data-dir`）、`--output-dir`、`--reports-dir` 及 `--timeout` 調整路徑與下載逾時。

來源頁為 <https://www.omotenashi88.net/issei/issei-map>；其連結的地圖程式目前仍宣告
<https://komelabo.sakura.ne.jp/omotenashi-henro-walk/kml/route1102.kml>。
來源存為 `raw/snapshots/<sha256>/<來源檔名>.kml` 及 `metadata.json`，保留舊 `route1102.kml` archive 格式相容性；中繼資料包含來源 URL、發現鏈文件雜湊、下載時間及 KML 雜湊。驗證完整來源後才原子更新 `raw/current.json`，歷史快照不覆寫。

輸出：

- `output/omotenashi-henro-inspection-routes.geojson`：非空 `FeatureCollection`；每個原始 Placemark 對應一筆，保留 `name`、`folders`、`documents`、`description`、`style_url`、原始 ID 與來源次序。單段使用 `LineString`，同一 Placemark 多段使用 `MultiLineString`，保留經緯度及選填高度，不簡化、不拼接路段、不建立導航圖。
- `output/source-metadata.json`：確定性的來源、雜湊、座標順序、用途、限制及權利說明，不加入建置時間。
- `reports/pipeline.json`：來源／建置設定雜湊、每個輸出的大小及雜湊、Placemark／獨立線段／座標數與邊界。來源、程式及輸出雜湊全數相同時略過重建，但仍比對原始幾何及 provenance。

建置先暫存及驗證所有輸出，再逐檔原子發布，report 最後寫入；使用來源目錄的非阻塞 `.pipeline.lock` 防止同時執行。空來源、無效座標、退化線段、未處理幾何或 network link 均會中止，不以空資料取代既有輸出。

資料語義是「一日一斉おもてなし遍路道ウォーク」遍路道點檢活動的覆蓋路線，可作為較可能受該活動關注的路段參考。這不代表道路目前已維護、可通行或適合導航。發布者也說明路線會隨時代變遷、幾何可能與實際道路偏移，且必須以現場狀況與交通管制為準。

原網站標示 All Rights Reserved；本管線只供本機 archive 與本機衍生資料使用，不授予再散布權。公開散布、轉換或打包前應先取得權利人的明確許可。
