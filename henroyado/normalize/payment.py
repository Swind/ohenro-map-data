"""Payment parsing (plan §18).

Examples:
  "現金"                                     -> methods ["cash"]
  "現金 、 カード"                            -> methods ["cash","card"]
  "現金 、 カード （VISA/JCB/Mastercard/UC/AE）"
    -> methods ["cash","card"], cards ["VISA","JCB","Mastercard","UC","AE"]
"""

import re

from henroyado.normalize.text import clean_punct, normalize_half_kana


def parse_payment(text):
    """Returns (methods, cards)."""
    if not text:
        return [], []
    t = normalize_half_kana(text)
    t_upper = t.upper().replace("VIZA", "VISA")
    t_flat = re.sub(r"\s+", "", t_upper)

    methods = []
    if "現金" in t:
        methods.append("cash")
    if "カード" in t:
        methods.append("card")

    cards = []

    def add(brand, present):
        if present and brand not in cards:
            cards.append(brand)

    add("VISA", "VISA" in t_flat)
    add("Mastercard", "MASTER" in t_flat)
    add("JCB", "JCB" in t_flat)
    add("AE", "AMEX" in t_flat or "AMERICANEXPRESS" in t_flat or "アメリカンエクスプレス" in t
        or bool(re.search(r"(?<![A-Z])AE(?![A-Z])", t_flat)))
    add("UC", bool(re.search(r"(?<![A-Z])UC(?![A-Z])", t_flat)))
    add("DC", bool(re.search(r"(?<![A-Z])DC(?![A-Z])", t_flat)))
    add("Diners", "DINERS" in t_flat)
    add("Discover", "DISCOVER" in t_flat)
    add("UnionPay", "UNIONPAY" in t_flat or "銀聯" in t)
    add("PayPay", "PAYPAY" in t_flat)
    add("d払い", "D払い" in t or "d払い" in text)
    return methods, cards


def clean_payment_text(text):
    """Raw payment text with punctuation spacing cleaned for display."""
    return clean_punct(text)
