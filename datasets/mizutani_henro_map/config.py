"""Constants and archive paths for the Mizutani Henro Guide Map."""

from __future__ import annotations

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DATA_DIR = os.path.join(ROOT, 'datasets/mizutani_henro_map/raw')

DATASET_ID = "mizutani-henro-map"
MAP_ID = "1FYOrTzLZCmGi4wGFf5bNhIe3K18"
TITLE = "お遍路のルート・おすすめ宿・お店・道しるべ・経験談"
AUTHOR = "水谷卓也"
SOURCE_MAP_URL = "https://www.google.com/maps/d/u/0/viewer?mid=" + MAP_ID
SOURCE_ARTICLE_URL = "https://min88.jp/photo/558/"
KML_URL = "https://www.google.com/maps/d/kml?mid=" + MAP_ID + "&forcekml=1"

USER_AGENT = "MizutaniHenroMapArchiver/0.1 (ohenro-map-data; personal-use)"
DEFAULT_TIMEOUT = 30
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2)


def data_layout(data_dir: str) -> dict[str, str]:
    return {
        "current": os.path.join(data_dir, "current.json"),
        "snapshots": os.path.join(data_dir, "snapshots"),
        "failed": os.path.join(data_dir, "failed"),
    }
