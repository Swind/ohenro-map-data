#!/usr/bin/env python3
"""Inn HTML extraction -> RawInn (plan §19, Step 3).

Extracts source values from each accommodation's front row + detail card
without semantic normalization. One field failing must not drop the record.
"""

import copy
import re

from bs4 import BeautifulSoup

from henroyado.model.raw import RawFacility, RawInn

TEMPLE_NUM_RE = re.compile(r"js_temple_(\d+)")
KNOWN_DETAIL_LABELS = {"部屋", "食事", "チェックイン", "チェックアウト"}


def _collapsed(el):
    """Text with all whitespace collapsed to single spaces."""
    return " ".join(el.get_text(" ", strip=True).split())


def _opt(value):
    """Coerce empty string to None (plan §3.4: missing -> null)."""
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _raw_text(el):
    """Text preserving <br> as newlines; other whitespace collapsed."""
    clone = copy.deepcopy(el)
    for br in clone.find_all("br"):
        br.append("\n")
    text = clone.get_text()
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _table_heading(table):
    cap = table.find("caption")
    if cap is not None:
        m = TEMPLE_NUM_RE.search(" ".join(cap.get("class") or []))
        if m:
            return "temple", {"number": int(m.group(1)), "text": _collapsed(cap)}
    h = table.select_one("tr.bl_heading")
    if h is not None:
        return "route", _collapsed(h)
    return None, None


def _section(info, heading):
    for sec in info.select("section.bl_sect"):
        h4 = sec.find("h4", class_="bl_sect_heading")
        if h4 is not None and _collapsed(h4) == heading:
            return sec
    return None


def _detail_items(section):
    items = []
    for li in section.select("ul.bl_sect_list li"):
        p = li.find("p", class_="bl_sect_headingSm")
        if p is None:
            continue
        label = _collapsed(p)
        clone = copy.deepcopy(li)
        clone.find("p", class_="bl_sect_headingSm").decompose()
        items.append((label, _raw_text(clone)))
    return items


def _source_context(front_row):
    table = front_row.find_parent("table")
    pref = None
    group = front_row.find_parent("div", class_="js_prefGroup")
    if group is not None:
        pref = group.get("data-pref")
    kind, heading = _table_heading(table) if table is not None else (None, None)
    temple = heading["number"] if kind == "temple" else None
    tbody = front_row.find_parent("tbody")
    data_types = []
    if tbody is not None and tbody.get("data-type"):
        data_types = [int(x) for x in re.split(r"[,\s]+", tbody["data-type"]) if x.strip()]
    tds = front_row.find_all("td")
    name = _collapsed(tds[0]) if tds else ""
    distance = _opt(_collapsed(tds[1])) if len(tds) > 1 else None
    status = _opt(_collapsed(tds[3])) if len(tds) > 3 else None
    if status == "詳細":
        status = None
    types = [_collapsed(t) for t in front_row.select("span.bl_icon_set_txt")]
    type_icons = []
    for img in front_row.select("img.bl_icon_set_img"):
        src = img.get("data-src") or img.get("src") or ""
        if src:
            type_icons.append(src.rsplit("/", 1)[-1])
    remark = _opt(_collapsed(tds[-1])) if tds else None
    return {
        "prefecture": pref,
        "table_kind": kind,
        "table_heading": heading["text"] if kind == "temple" else (heading if kind == "route" else None),
        "temple": temple,
        "row_data_types": data_types,
        "front_row_name": name,
        "row_distance": distance,
        "row_status": status,
        "row_types": types,
        "row_type_icons": type_icons,
        "row_remark": remark,
    }


def _facilities(section):
    facilities = []
    for w in section.select("div.bl_sect_iconList_iconWrapper"):
        imgs = w.find_all("img")
        icon = None
        disabled = False
        for img in imgs:
            src = img.get("src") or ""
            name = src.rsplit("/", 1)[-1]
            if name == "cross.png":
                disabled = True
            elif icon is None:
                icon = name
        remark = w.select_one("span.bl_iconList_icon_remark")
        facilities.append(RawFacility(icon=icon, remark=_opt(_collapsed(remark)) if remark else None, available=not disabled))
    return facilities


def _contact(section):
    phone = website = email = None
    for li in section.select("ul.bl_sect_list li"):
        a = li.find("a")
        if a is None or not a.get("href"):
            continue
        href = a["href"]
        if href.startswith("tel:") and phone is None:
            phone = href[len("tel:"):]
        elif href.startswith("mailto:") and email is None:
            email = href[len("mailto:"):]
        elif href.startswith("http") and website is None:
            website = href
    return phone, website, email


def _map_info(section):
    embed = None
    search = None
    iframe = section.select_one("div.bl_embedMapWrapper iframe")
    if iframe is not None and iframe.get("src"):
        embed = iframe["src"]
    for a in section.select("a"):
        href = a.get("href") or ""
        if "maps.google.com/maps?q=" in href:
            search = href
    return search, embed


def _images(detail_tr):
    seen = []
    for img in detail_tr.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if "storage/inns" in src and src not in seen:
            seen.append(src)
    return seen


def extract_inn(front_row, detail_tr):
    """Extract a RawInn from a front row and its following detail row."""
    context = _source_context(front_row)
    info = detail_tr.select_one("div.bl_card_info") if detail_tr is not None else None
    has_content = info is not None and info.select_one("h3") is not None

    name = ""
    description = route = notice = None
    room = meal = check_in = check_out = None
    facilities = []
    extra_details = []
    pricing_items = []
    payment = None
    phone = website = email = None
    search = embed = None

    if has_content:
        name = _collapsed(info.select_one("h3"))
        lead = info.select_one("span.bl_sect_txt.bl_card_info_leadTxt")
        description = _opt(_raw_text(lead)) if lead is not None else None

        rt = info.select_one("span.hp_roundFrame_txt")
        route = _opt(_collapsed(rt)) if rt is not None else None

        sec = _section(info, "お知らせ")
        if sec is not None:
            p = sec.select_one("p.bl_sect_txt")
            notice = _opt(_raw_text(p)) if p is not None else None

        sec = _section(info, "宿詳細")
        if sec is not None:
            for label, value in _detail_items(sec):
                value = _opt(value)
                if value is None:
                    continue
                if label == "部屋":
                    room = value
                elif label == "食事":
                    meal = value
                elif label == "チェックイン":
                    check_in = value
                elif label == "チェックアウト":
                    check_out = value
                else:
                    extra_details.append({"label": label, "value": value})
            facilities = _facilities(sec)

        sec = _section(info, "料金")
        if sec is not None:
            for li in sec.select("ul.bl_sect_list li"):
                text = _opt(_collapsed(li))
                if not text:
                    continue
                pricing_items.append(text)
                m = re.match(r"支払い方法\s*[:：]\s*(.*)", text)
                if m:
                    payment = _opt(m.group(1))

        sec = _section(info, "お問い合わせ")
        if sec is not None:
            phone, website, email = _contact(sec)

        sec = _section(info, "マップ")
        if sec is not None:
            search, embed = _map_info(sec)

    if not name:
        name = context["front_row_name"]

    return RawInn(
        source_context=context,
        name=name,
        description=description,
        route=route,
        notice=notice,
        room=room,
        meal=meal,
        check_in=check_in,
        check_out=check_out,
        facilities=facilities,
        pricing_items=pricing_items,
        payment=payment,
        phone=phone,
        website=website,
        email=email,
        google_maps_search_url=search,
        google_maps_embed_url=embed,
        images=_images(detail_tr) if detail_tr is not None else [],
        extra_details=extra_details,
    )


def extract_all(html):
    """Extract RawInn for every accommodation in the page. Returns (inns, skipped)."""
    soup = BeautifulSoup(html, "html.parser")
    inns = []
    for row in soup.select("tr.bl_table_row_frontInfo"):
        detail = row.find_next_sibling("tr")
        inns.append(extract_inn(row, detail))
    return inns
