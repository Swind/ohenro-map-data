# Lodging PMTiles

Henroyado and min88 remain independent lodging sources and are built into separate PMTiles archives:

```bash
bash scripts/build-lodging-pmtiles.sh
# Or rebuild just one source:
bash scripts/build-lodging-pmtiles.sh henroyado
bash scripts/build-lodging-pmtiles.sh min88
```

Outputs:

- `output/shikoku-henroyado-lodging.pmtiles`
- `output/shikoku-min88-lodging.pmtiles`

Both archives contain one `lodging` point layer at zooms 6-14 with the same compact map contract:
`provider`, `source_id`, `name`, `business_status`, `address`, `phone`, `website`, `room_count`,
`check_in`, `check_out`, `price`, and `coordinate_source`.

Only records with resolved Google Place coordinates are emitted. min88 keeps its source post ID.
Henroyado uses its Google Place ID and emits one feature per place, collapsing duplicate source listings
only in the map export; its source JSONL remains unchanged.
