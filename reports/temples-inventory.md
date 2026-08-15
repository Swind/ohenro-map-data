# v1.1 盤點報告：OSM 中 88 所札所的實際 tagging

日期：2026-08-15
來源：`source/shikoku-latest.osm.pbf`（replication seq 3395）

## 摘要

- PBF 中 `amenity=place_of_worship` 物件共 **3,607** 個
  （node 1,936 / way 1,660 / relation 11）
- 其中 `religion=buddhist`：**1,123** 個
- **88 番全部都有對應的 place_of_worship 物件**，但 tagging 格式不一致

## 主要發現

### 1. 編號只在 `name`，沒有 `ref` / `temple` / `shikoku` 等專用 key

主流格式（86/88 可用）：

```text
name = 第XX番札所 <寺名> [(Romaji)]
```

例如 `第18番札所 恩山寺 (Onzan-ji)`、`第02番札所 極楽寺`、`第88番札所 大窪寺 (Okubo-ji)`。

共同標籤：`amenity=place_of_worship` + `religion=buddhist`
（denomination 多為 `shingon_shu`，少數 `rinzai` 或無，**不適合作為判定條件**）。

### 2. 幾何表示混用 node / way / relation

| geometry | 數量 |
|---|---|
| node | 69 |
| way | 16 |
| relation | 1（#75 善通寺）|

因此 `temples` layer 必須處理三種來源幾何，輸出時統一轉成點。

### 3. 必須排除的噪音（否則誤判）

| 噪音來源 | 範例 | 排除理由 |
|---|---|---|
| 爺神山ミニ四国八十八ヶ所 | `第2番札所(爺神山ミニ四国八十八ヶ所)`，88 個 | 迷你複製品，非真實札所 |
| henro route relations | `四国遍路 1番札所霊山寺~2番札所極楽寺` | 路線 relation，非寺院 |
| 別格 | `別格18番札所 屏風ヶ浦 海岸寺` | 別格靈場，非 1–88 |
| 文化財標記 | `高知県指定有形文化財土佐西国第２２番札所` | 非寺院物件 |
| 寺內副堂 | `45番札所 大師堂`、`46番札所 観音堂` | 主寺內的附屬堂，非札所本身 |

### 4. 格式不一致

- 全形數字：`第８４番札所 屋島寺`（node 11601613590）
- 缺空格的 full-width/半形混用：`第12番札所 焼山寺(Shosan-ji)`
- 無「第」前綴的副堂：`45番札所 大師堂`
- 極少數 `name` 不含編號（見下）

### 5. 資料缺口 / 錯誤（`第\d+番札所` 前綴解析只能命中 86/88）

| # | 狀況 | OSM 物件 |
|---|---|---|
| 66 | **重複**：`第66番札所 大興寺`（錯）vs `第66番札所 雲辺寺`（正確）| node 13457190181 / node 13457236116 |
| 67 | 大興寺被誤標為 66，way 659122412 無編號 | way 659122412 |
| 74 | 甲山寺：`place_of_worship` 但 name 無編號 | node 4435714991 |
| 76 | 金倉寺：`place_of_worship` 但 name 無編號 | node 6544524285 |

## 建議 v1.1 判定規則

```text
候選 = amenity=place_of_worship
     AND religion=buddhist
     AND name 符合 ^第(\d{1,2})番札所
     AND name 不含「爺神山ミニ」「別格」
```

temple_number 從 name 前綴解析。87/88 可完整取得（66 重複需額外處理），
67/74/76 需要以「88 寺正名對照表」補齊 → 也就是：

> **temple_number 需要一份可靠的 88 寺對照（name 前綴解析 + 正名表）才能進 schema。**
