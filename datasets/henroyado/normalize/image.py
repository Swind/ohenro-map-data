"""Image URL normalization (plan §17). No image binaries are downloaded.

"https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836"
  -> url "https://henroyado.com/storage/inns/HYT_02011.jpg"   (canonical)
     original_url "https://henroyado.com/storage/inns/HYT_02011.jpg?20260816022836"
"""


def split_image_url(url):
    """Returns (canonical_url, original_url)."""
    if not url:
        return None, None
    base = url.split("?", 1)[0]
    return base, url
