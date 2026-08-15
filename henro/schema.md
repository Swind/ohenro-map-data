# Shikoku Henro PMTiles v1 Schema

`henro/output/shikoku-henro.pmtiles` — Shikoku Henro overlay tileset。

- Planetiler：0.10.2
- 來源：`source/shikoku-latest.osm.pbf`（OSM Geofabrik shikoku extract，replication seq 3395）
- 格式：PMTiles v3 / MVT / overlay（`type=overlay`）
- zoom：0–14

## Layer：`henro_routes`

| | |
|---|---|
| Geometry | LineString（每個 relation member way 各自輸出一條，v1 不 merge） |
| Min / Max zoom | 0 / 14 |
| 來源 OSM 物件 | `type=route` + `route=hiking` relations 的 member ways |

### Filter rules

```text
preprocessOsmRelation(relation):
  relation.type == "route"
  && relation.route == "hiking"
  → 儲存 HenroRelationInfo 並附加到每個 member way

processFeature(way):
  for each membership in way.relationInfo(HenroRelationInfo):
    → features.line("henro_routes")
```

### Attributes

| field | 型別 | 說明 | 來源 OSM tag |
|---|---|---|---|
| `relation_id` | integer | relation ID，debug OSM 資料用的關鍵欄位 | `relation.id` |
| `name` | string | relation name（不做 parsing） | `name`（存在才寫入） |
| `ref` | string | relation ref | `ref`（存在才寫入） |
| `network` | string | `nwn` / `rwn` / `lwn` 等原始值，v1 不改寫 | `network` |
| `route` | string | `hiking` | `route` |
| `route_kind` | string | `henro_candidate`（v1 固定值） | — |

### 語意說明

- `route_kind=henro_candidate` 表示「這條 hiking route 是候選路線」，**不代表**正式判定為四國遍路。
- Extraction（`route=hiking`）與 classification（是否 Shikoku Henro）刻意分開。
- 正式分類（`henro_main` / `henro_alternate` / `henro_connector` / `other_hiking`）屬於 v1.3，需要先盤點實際 OSM 資料。
- 目前 smoke test 使用 relation `13653654`，這是 **temporary smoke-test rule**，不是正式分類邏輯。

### 後續擴充（未在本版）

- `temples`、`henro_pois`、`guideposts`、`danger_sections` layers。
- Geometry merge（v1.4 Geometry QA 之後，另有 route-processing pipeline）。

## 建置

```bash
./scripts/build-henro.sh
```

## 驗證

```bash
python3 scripts/smoke-test-henro.py henro/output/shikoku-henro.pmtiles
./scripts/validate.sh
```
