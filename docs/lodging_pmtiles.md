# Lodging PMTiles

Henroyado and min88 remain independent sources. Update each complete source and its map in one command:

```bash
python3 -m datasets.henroyado
python3 -m datasets.min88_lodging
# Rebuild from selected local source snapshots (reuse/fill Google response cache):
bash scripts/build-lodging-pmtiles.sh [all|henroyado|min88] [--force]
```

Outputs:

- `datasets/henroyado/output/shikoku-henroyado-lodging.pmtiles`
- `datasets/min88_lodging/output/shikoku-min88-lodging.pmtiles`

Both archives contain one `lodging` point layer at zooms 6-14 with the same compact map contract:
`provider`, `source_id`, `name`, `business_status`, `address`, `phone`, `website`, `room_count`,
`check_in`, `check_out`, `price`, and `coordinate_source`.

Only records with resolved Google Place coordinates are emitted. min88 keeps its source post ID.
Henroyado uses its Google Place ID and emits one feature per place, collapsing duplicate source listings
only in the map export; its source JSONL remains unchanged.

The shell entry delegates to each source's `build`; it no longer publishes tiles independently
of its source JSONL/GeoJSON. Each source stages and validates all managed outputs before
per-file atomic publication, then writes `datasets/<source>/reports/pipeline.json`.
`run --local` uses the selected source snapshot and cached Google responses without network;
missing cache fails safely. `validate` independently checks source/cache/output hashes and tiles.
