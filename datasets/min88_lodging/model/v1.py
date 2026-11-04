"""Constants for the provider-specific Min88LodgingV1 model."""

SCHEMA_VERSION = 1
PROVIDER = "min88"
LIST_URL = "https://min88.jp/inn/list_ja/"

PREFECTURE_JP = {
    "tokushima": "徳島県",
    "kochi": "高知県",
    "ehime": "愛媛県",
    "kagawa": "香川県",
}

SHIKOKU_PREFECTURES = tuple(PREFECTURE_JP.values())
JAPANESE_PREFECTURE_RE = (
    r"(?:北海道|東京都|京都府|大阪府|(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|"
    r"神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|兵庫|奈良|和歌山|"
    r"鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|"
    r"鹿児島|沖縄)県)"
)

# Conservative main-island fallback for marker-only Google results.
SHIKOKU_POLYGON = (
    (132.00, 33.05), (132.30, 32.75), (133.10, 32.70), (134.20, 33.10),
    (134.85, 33.65), (134.70, 34.25), (134.20, 34.48), (133.35, 34.42),
    (132.65, 34.18), (132.15, 33.65),
)

BUSINESS_STATUS = {"《休業･閉業》": "closed_or_suspended", "休業･閉業": "closed_or_suspended"}

LODGING_TYPE_MAP = {
    "民宿･ゲストハウス": "guesthouse",
    "民宿・ゲストハウス": "guesthouse",
    "宿坊": "temple_lodging",
    "旅館": "ryokan",
    "ホテル": "hotel",
    "ビジネスホテル": "hotel",
    "旅館･ホテル": ["ryokan", "hotel"],
    "旅館・ホテル": ["ryokan", "hotel"],
    "通夜堂･善根宿": "pilgrim_shelter",
    "通夜堂・善根宿": "pilgrim_shelter",
    "キャンプ場": "campground",
}
