"""Text helpers: full-width digit normalization, half-width katakana, punctuation spacing."""

import re

FULLWIDTH_DIGITS = str.maketrans(
    "０１２３４５６７８９",
    "0123456789",
)

HALFWIDTH_KA = str.maketrans(
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝｯｬｭｮ",
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンッャュョ",
)


def normalize_digits(text):
    return text.translate(FULLWIDTH_DIGITS).replace("：", ":")


def normalize_half_kana(text):
    text = text.translate(HALFWIDTH_KA)
    dakuten = {
        "カ": "ガ", "キ": "ギ", "ク": "グ", "ケ": "ゲ", "コ": "ゴ",
        "サ": "ザ", "シ": "ジ", "ス": "ズ", "セ": "ゼ", "ソ": "ゾ",
        "タ": "ダ", "チ": "ヂ", "ツ": "ヅ", "テ": "デ", "ト": "ド",
        "ハ": "バ", "ヒ": "ビ", "フ": "ブ", "ヘ": "ベ", "ホ": "ボ",
    }
    handakuten = {
        "ハ": "パ", "ヒ": "ピ", "フ": "プ", "ヘ": "ペ", "ホ": "ポ",
    }
    out = []
    for ch in text:
        if ch in ("ﾞ", "゛") and out and out[-1] in dakuten:
            out[-1] = dakuten[out[-1]]
        elif ch in ("ﾟ", "゜") and out and out[-1] in handakuten:
            out[-1] = handakuten[out[-1]]
        else:
            out.append(ch)
    return "".join(out)


def clean_punct(text):
    """Remove spaces around Japanese punctuation 、 。 and full-width （ ）.

    "朝食 (7:00) 、 夕食" -> "朝食 (7:00)、夕食"   (half-width parens kept)
    "現金 、 カード （VISA）" -> "現金、カード（VISA）"  (full-width parens closed)
    """
    if not text:
        return text
    text = re.sub(r"[ \t]+([、。，])", r"\1", text)
    text = re.sub(r"([、。，])[ \t]+", r"\1", text)
    text = re.sub(r"[ \t]+([（）])", r"\1", text)
    text = re.sub(r"([（])[ \t]+", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
