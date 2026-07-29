#!/usr/bin/env python3
"""Сторож приёмной кампании: юрфак МГУ, платные места.

Снимает состояние шести источников, сравнивает со снимком прошлого прохода
и печатает только то, что изменилось. Если меняться нечему — молчит.

Коды возврата:
    0  — тихо, изменений нет
    10 — есть изменения, их стоит прочитать
    20 — источник не отвечает подряд столько раз, что молчание само стало
         новостью (см. FAILURES_BEFORE_ALARM)

Запуск:
    python3 watch.py              обычный проход
    python3 watch.py --report     напечатать состояние целиком, даже без изменений
    python3 watch.py --baseline   перезаписать снимок, ничего не сравнивая
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as cfg  # noqa: E402

STATE_PATH = Path(__file__).resolve().parent / "state" / "snapshot.json"
JOURNAL_PATH = Path(__file__).resolve().parent / "journal.md"
MSK = timezone(timedelta(hours=3))


def now_msk() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")


# --------------------------------------------------------------------------
# Сеть
# --------------------------------------------------------------------------


def fetch(url: str, binary: bool = False):
    """Тянет URL с повторами. Возвращает (payload, error).

    payload — str для HTML, bytes для PDF. При неудаче payload = None,
    error — короткая причина, годная для показа человеку.
    """
    headers = {
        "User-Agent": cfg.USER_AGENT,
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    last = "неизвестная ошибка"
    for attempt in range(cfg.HTTP_RETRIES):
        try:
            r = requests.get(url, headers=headers, timeout=cfg.HTTP_TIMEOUT)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
                # Ошибки клиента повторять бессмысленно, кроме 429.
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return None, last
            else:
                if binary:
                    return r.content, None
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding or "utf-8"
                return r.text, None
        except requests.exceptions.SSLError as e:
            return None, f"TLS: {type(e).__name__}"
        except requests.RequestException as e:
            last = f"{type(e).__name__}"
        if attempt < cfg.HTTP_RETRIES - 1:
            time.sleep(2 ** attempt)
    return None, last


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    return hashlib.sha256(data).hexdigest()[:16]


# --------------------------------------------------------------------------
# Разбор таблиц
# --------------------------------------------------------------------------


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).replace("\xa0", " ").strip()


def section_of(tag) -> str:
    """Ближайший предшествующий заголовок — подпись к таблице.

    Абитуриент проходит по нескольким конкурсам сразу, поэтому строку без
    указания раздела читать бесполезно.
    """
    for prev in tag.find_all_previous(
        ["h1", "h2", "h3", "h4", "h5", "caption", "legend", "summary", "th"]
    ):
        text = clean(prev.get_text())
        if 3 < len(text) < 200:
            return text
    return "(раздел не определён)"


def rows_containing(html: str, needle: str) -> list[dict]:
    """Все строки таблиц, где встречается needle, вместе с шапкой и разделом.

    Разбор намеренно не опирается на классы и вёрстку cpk.msu.ru: ищем
    строку по содержимому, шапку берём из первой строки той же таблицы.
    Так парсер переживает косметические правки сайта.
    """
    soup = BeautifulSoup(html, "lxml")
    found = []
    for tr in soup.find_all("tr"):
        if needle not in tr.get_text():
            continue
        cells = [clean(td.get_text()) for td in tr.find_all(["td", "th"])]
        if not cells:
            continue
        table = tr.find_parent("table")
        headers: list[str] = []
        if table:
            head = table.find("thead")
            head_row = head.find("tr") if head else table.find("tr")
            if head_row is not None and head_row is not tr:
                headers = [clean(c.get_text()) for c in head_row.find_all(["th", "td"])]
        found.append(
            {
                "section": section_of(table or tr),
                "headers": headers,
                "cells": cells,
            }
        )
    if not found:
        # Запасной путь: таблицы может не быть вовсе (список, div-вёрстка).
        text = BeautifulSoup(html, "lxml").get_text("\n")
        for line in text.splitlines():
            if needle in line:
                found.append(
                    {"section": "(вне таблицы)", "headers": [], "cells": [clean(line)]}
                )
    return found


def labelled(row: dict) -> dict:
    """Пара столбец→значение, если шапка нашлась."""
    h, c = row.get("headers") or [], row.get("cells") or []
    if not h or len(h) != len(c):
        return {}
    return {k: v for k, v in zip(h, c) if k}


def find_awaited_value(row: dict) -> str | None:
    """Значение столбца, заполнения которого ждём."""
    pairs = labelled(row)
    for k, v in pairs.items():
        if cfg.COLUMN_AWAITED.lower() in k.lower():
            return v
    # Шапка не совпала по длине — ищем столбец по позиции в шапке.
    h = row.get("headers") or []
    c = row.get("cells") or []
    for i, k in enumerate(h):
        if cfg.COLUMN_AWAITED.lower() in k.lower() and i < len(c):
            return c[i]
    return None


def filled(value: str | None) -> bool:
    return bool(value and value not in {"-", "—", "–", "", "нет", "не сдавал"})


def sublinks(html: str, base: str, must_contain: str) -> list[dict]:
    """Ссылки на отдельные конкурсы со страницы-оглавления.

    cpk.msu.ru отдаёт по адресу раздела не таблицу, а перечень конкурсов
    («Юриспруденция (обучение на договорной основе)» и прочие), и номера
    заявлений лежат уже внутри них.
    """
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"]).split("#")[0]
        title = clean(a.get_text())
        if len(title) < 5 or must_contain not in href:
            continue
        if href.rstrip("/") == base.split("#")[0].rstrip("/") or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "title": title})
    return out


def search_deep(
    base_url: str, needle: str, must_contain: str, max_pages: int = 40
) -> tuple[list[dict] | None, str | None, dict]:
    """Ищет строку по номеру на странице, а если та — оглавление, то внутри.

    Возвращает (строки, ошибка, сведения о самой странице). Раздел в
    найденной строке подменяется названием конкурса из ссылки: оно точнее
    того, что удаётся вытащить из вёрстки вложенной страницы.
    """
    html, err = fetch(base_url)
    if html is None:
        return None, err, {}

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ")
    info = {
        "title": clean(soup.title.get_text()) if soup.title else "",
        "years_on_page": sorted(set(re.findall(r"\b(20[2-3]\d)\b", text))),
        "page_hash": sha(re.sub(r"\s+", " ", text)),
    }

    rows = rows_containing(html, needle)
    if rows:
        info["depth"] = "страница раздела"
        return rows, None, info

    links = sublinks(html, base_url, must_contain)
    info["competitions"] = len(links)
    info["depth"] = "вложенные конкурсы"
    found, checked, failed = [], 0, 0
    for link in links[:max_pages]:
        sub, sub_err = fetch(link["url"])
        if sub is None:
            failed += 1
            continue
        checked += 1
        for row in rows_containing(sub, needle):
            row["section"] = link["title"]
            row["url"] = link["url"]
            found.append(row)
    info["checked"] = checked
    info["unreachable"] = failed
    return found, None, info


# --------------------------------------------------------------------------
# Пробы источников
# --------------------------------------------------------------------------


def probe_submitted() -> dict:
    rows, err, info = search_deep(cfg.URL_SUBMITTED, cfg.NUM_SUBMITTED, "/submitted/")
    if rows is None:
        return {"ok": False, "error": err}
    out = []
    for r in rows:
        awaited = find_awaited_value(r)
        out.append(
            {
                "section": r["section"],
                "url": r.get("url"),
                "cells": r["cells"],
                "labelled": labelled(r),
                "dvi": awaited,
                "dvi_filled": filled(awaited),
            }
        )
    return {"ok": True, "found": len(out), "rows": out, **info}


def probe_rating() -> dict:
    rows, err, info = search_deep(cfg.URL_RATING, cfg.NUM_AIS, "/rating/")
    if rows is None:
        return {"ok": False, "error": err}
    return {
        "ok": True,
        "year_expected_present": cfg.YEAR_EXPECTED in info.get("years_on_page", []),
        "found": len(rows),
        "rows": [
            {
                "section": r["section"],
                "url": r.get("url"),
                "cells": r["cells"],
                "labelled": labelled(r),
            }
            for r in rows
        ],
        **info,
    }


def probe_news() -> dict:
    html, err = fetch(cfg.URL_NEWS)
    if html is None:
        return {"ok": False, "error": err}
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(cfg.URL_NEWS, a["href"])
        if "/news/" not in href:
            continue
        title = clean(a.get_text())
        if len(title) < 12 or href in seen:
            continue
        seen.add(href)
        items.append({"url": href, "title": title})
    items = items[:60]
    hits = [
        i for i in items
        if any(k in i["title"].lower() for k in cfg.NEWS_KEYWORDS)
    ]
    return {"ok": True, "count": len(items), "items": items, "keyword_hits": hits}


def pdf_text(data: bytes) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # PDF может быть сканом или битым — это не повод падать
        return f"__PDF_TEXT_ERROR__ {type(e).__name__}: {e}"


def probe_dvi_pdf() -> dict:
    data, err = fetch(cfg.URL_DVI_PDF, binary=True)
    if data is None:
        return {"ok": False, "error": err}
    text = pdf_text(data)
    score = None
    context = None
    if not text.startswith("__PDF_TEXT_ERROR__"):
        for line in text.splitlines():
            if cfg.CODE_DVI in line:
                context = clean(line)
                nums = re.findall(r"\b(\d{1,3})\b", line.replace(cfg.CODE_DVI, " "))
                plausible = [int(n) for n in nums if 0 <= int(n) <= 100]
                if plausible:
                    score = plausible[-1]
                break
    return {
        "ok": True,
        "sha": sha(data),
        "bytes": len(data),
        "code_line": context,
        "score": score,
        "score_matches_expected": (score == cfg.SCORE_DVI_EXPECTED)
        if score is not None
        else None,
    }


def probe_contract() -> dict:
    """Страница юрфака про заключение договора.

    Порог баллов («приглашаем заключать договор от 230 баллов») может
    появиться здесь раньше, чем в ленте новостей, поэтому кроме хеша
    вытаскиваем все упоминания баллов.
    """
    html, err = fetch(cfg.URL_CONTRACT)
    if html is None:
        return {"ok": False, "error": err}
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" "))
    scores = sorted(set(re.findall(r"(?:от\s*)?(\d{2,3})\s*балл", text, re.I)))
    return {"ok": True, "sha": sha(text), "chars": len(text), "scores": scores}


def probe_binary(url: str) -> dict:
    data, err = fetch(url, binary=True)
    if data is None:
        return {"ok": False, "error": err}
    return {"ok": True, "sha": sha(data), "bytes": len(data)}


def probe_page_hash(url: str) -> dict:
    html, err = fetch(url)
    if html is None:
        return {"ok": False, "error": err}
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" "))
    return {"ok": True, "sha": sha(text), "chars": len(text)}


PROBES = {
    "submitted": ("Список подавших документы", probe_submitted),
    "rating": ("Конкурсные списки", probe_rating),
    "news": ("Новости юрфака", probe_news),
    "contract": ("Страница «Заключение договора»", probe_contract),
    "dvi_pdf": ("Ведомость ДВИ по обществознанию", probe_dvi_pdf),
    "schedule": ("График приёмной кампании", lambda: probe_binary(cfg.URL_SCHEDULE_PDF)),
    "kcp": ("План приёма (число мест)", lambda: probe_binary(cfg.URL_KCP_PDF)),
    "passing": ("Проходные баллы прошлых лет", lambda: probe_page_hash(cfg.URL_PASSING_SCORES)),
}


# --------------------------------------------------------------------------
# Сравнение снимков
# --------------------------------------------------------------------------


def describe(key: str, old: dict | None, new: dict) -> list[str]:
    """Человеческое описание того, что изменилось. Пусто — значит тихо."""
    label = PROBES[key][0]
    msgs: list[str] = []

    if not new.get("ok"):
        return msgs  # недоступность разбирается отдельно, счётчиком неудач

    if old is None or not old.get("ok"):
        if old is not None:
            msgs.append(f"[{label}] источник снова отвечает")
        return msgs

    if key == "submitted":
        o = {r["section"]: r for r in old.get("rows", [])}
        for r in new.get("rows", []):
            prev = o.get(r["section"])
            if prev is None:
                msgs.append(
                    f"[{label}] НОВАЯ строка в разделе «{r['section']}»: "
                    + " | ".join(r["cells"])
                )
                continue
            if r["dvi_filled"] and not prev.get("dvi_filled"):
                msgs.append(
                    f"[{label}] ★ ЗАПОЛНЕН столбец «{cfg.COLUMN_AWAITED}» "
                    f"в разделе «{r['section']}»: {r['dvi']}"
                )
            elif r["dvi"] != prev.get("dvi"):
                msgs.append(
                    f"[{label}] столбец «{cfg.COLUMN_AWAITED}» в разделе "
                    f"«{r['section']}»: {prev.get('dvi')} → {r['dvi']}"
                )
            if r["cells"] != prev.get("cells"):
                msgs.append(
                    f"[{label}] строка в разделе «{r['section']}» изменилась:\n"
                    f"    было:  {' | '.join(prev.get('cells', []))}\n"
                    f"    стало: {' | '.join(r['cells'])}"
                )
        if new.get("found", 0) == 0 and old.get("found", 0) > 0:
            msgs.append(
                f"[{label}] ⚠ абитуриент {cfg.NUM_SUBMITTED} ПРОПАЛ из списка "
                f"(было строк: {old.get('found')})"
            )

    elif key == "rating":
        if new.get("year_expected_present") and not old.get("year_expected_present"):
            msgs.append(
                f"[{label}] ★★ на странице появился {cfg.YEAR_EXPECTED} год — "
                f"конкурсные списки переключились"
            )
        if new.get("years_on_page") != old.get("years_on_page"):
            msgs.append(
                f"[{label}] годы на странице: {old.get('years_on_page')} → "
                f"{new.get('years_on_page')}"
            )
        if new.get("title") != old.get("title"):
            msgs.append(
                f"[{label}] заголовок: «{old.get('title')}» → «{new.get('title')}»"
            )
        if new.get("found", 0) > 0 and old.get("found", 0) == 0:
            msgs.append(
                f"[{label}] ★★ заявление {cfg.NUM_AIS} НАЙДЕНО в конкурсных "
                f"списках, строк: {new['found']}"
            )
            for r in new.get("rows", []):
                msgs.append(f"    «{r['section']}»: {' | '.join(r['cells'])}")
        else:
            o = {r["section"]: r for r in old.get("rows", [])}
            for r in new.get("rows", []):
                prev = o.get(r["section"])
                if prev is None:
                    msgs.append(
                        f"[{label}] новый конкурс «{r['section']}»: "
                        + " | ".join(r["cells"])
                    )
                elif r["cells"] != prev.get("cells"):
                    msgs.append(
                        f"[{label}] «{r['section']}» изменился:\n"
                        f"    было:  {' | '.join(prev.get('cells', []))}\n"
                        f"    стало: {' | '.join(r['cells'])}"
                    )
            if new.get("found", 0) == 0 and old.get("found", 0) > 0:
                msgs.append(
                    f"[{label}] ⚠ заявление {cfg.NUM_AIS} пропало из списков"
                )
        if not msgs and new.get("page_hash") != old.get("page_hash"):
            msgs.append(
                f"[{label}] страница изменилась, но наша строка прежняя "
                f"(двигались другие абитуриенты)"
            )

    elif key == "news":
        known = {i["url"] for i in old.get("items", [])}
        fresh = [i for i in new.get("items", []) if i["url"] not in known]
        for i in fresh:
            mark = (
                " ★"
                if any(k in i["title"].lower() for k in cfg.NEWS_KEYWORDS)
                else ""
            )
            msgs.append(f"[{label}] новость{mark}: {i['title']}\n    {i['url']}")

    elif key == "dvi_pdf":
        if new.get("sha") != old.get("sha"):
            msgs.append(
                f"[{label}] ⚠ ведомость ПЕРЕОПУБЛИКОВАНА "
                f"({old.get('bytes')} → {new.get('bytes')} байт)"
            )
        if new.get("score") != old.get("score"):
            msgs.append(
                f"[{label}] ★ балл по коду {cfg.CODE_DVI}: "
                f"{old.get('score')} → {new.get('score')}"
            )
        if new.get("score") is not None and not new.get("score_matches_expected"):
            msgs.append(
                f"[{label}] ⚠ балл {new.get('score')} расходится с ожидаемым "
                f"{cfg.SCORE_DVI_EXPECTED}"
            )

    elif key == "contract":
        if new.get("scores") != old.get("scores"):
            msgs.append(
                f"[{label}] ★★ изменились упоминания баллов: "
                f"{old.get('scores')} → {new.get('scores')} — "
                f"возможно, объявлен порог для договора"
            )
        elif new.get("sha") != old.get("sha"):
            msgs.append(f"[{label}] страница изменилась, порог баллов прежний")

    else:  # schedule, kcp, passing — следим за фактом обновления файла
        if new.get("sha") != old.get("sha"):
            msgs.append(f"[{label}] документ обновлён — стоит перечитать")

    return msgs


# --------------------------------------------------------------------------
# Состояние
# --------------------------------------------------------------------------


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text("utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def journal(lines: list[str]) -> None:
    """Дописывает событие в журнал.

    Снимок состояния перезаписывается каждый проход, поэтому история
    изменений живёт здесь: если контейнер со сторожем пересоздадут, по
    журналу видно, что уже случилось и о чём уже сообщали.
    """
    if not lines:
        return
    head = "" if JOURNAL_PATH.exists() else "# Журнал сторожа\n"
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{head}\n## {now_msk()}\n\n")
        for line in lines:
            f.write(f"- {line}\n")


# --------------------------------------------------------------------------


def summary(key: str, snap: dict) -> str:
    label = PROBES[key][0]
    if not snap.get("ok"):
        return f"  {label}: НЕДОСТУПЕН ({snap.get('error')})"
    if key == "submitted":
        rows = snap.get("rows", [])
        if not rows:
            return f"  {label}: строка {cfg.NUM_SUBMITTED} не найдена"
        bits = [
            f"«{r['section']}» → {cfg.COLUMN_AWAITED}: "
            f"{r['dvi'] if filled(r['dvi']) else 'пусто'}"
            for r in rows
        ]
        return f"  {label}: строк {len(rows)}; " + "; ".join(bits)
    if key == "rating":
        depth = snap.get("depth", "?")
        extra = ""
        if snap.get("competitions") is not None:
            extra = (
                f", конкурсов {snap.get('competitions')}, "
                f"проверено {snap.get('checked')}"
            )
            if snap.get("unreachable"):
                extra += f", НЕ ОТКРЫЛОСЬ {snap.get('unreachable')}"
        return (
            f"  {label}: годы {snap.get('years_on_page')}, "
            f"{cfg.YEAR_EXPECTED} "
            f"{'ЕСТЬ' if snap.get('year_expected_present') else 'нет'} "
            f"({depth}{extra}), строк по заявлению: {snap.get('found')}"
        )
    if key == "news":
        return f"  {label}: новостей на странице {snap.get('count')}"
    if key == "dvi_pdf":
        return (
            f"  {label}: код {cfg.CODE_DVI} → балл {snap.get('score')}, "
            f"файл {snap.get('sha')}"
        )
    return f"  {label}: {snap.get('sha')}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Сторож приёмной кампании юрфака МГУ")
    ap.add_argument("--report", action="store_true", help="печатать состояние целиком")
    ap.add_argument(
        "--baseline", action="store_true", help="записать снимок без сравнения"
    )
    args = ap.parse_args()

    state = load_state()
    prev = state.get("probes", {})
    fails = state.get("failures", {})

    fresh, changes, alarms, down = {}, [], [], []

    for key, (label, fn) in PROBES.items():
        try:
            snap = fn()
        except Exception as e:
            snap = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        fresh[key] = snap

        if snap.get("ok"):
            if fails.get(key, 0) >= cfg.FAILURES_BEFORE_ALARM:
                alarms.append(f"[{label}] снова доступен после {fails[key]} неудач")
            fails[key] = 0
        else:
            fails[key] = fails.get(key, 0) + 1
            down.append(f"  {label}: {snap.get('error')} (подряд: {fails[key]})")
            if fails[key] == cfg.FAILURES_BEFORE_ALARM:
                alarms.append(
                    f"[{label}] ⚠ не отвечает {fails[key]} проверки подряд — "
                    f"сторож этот источник больше не покрывает"
                )

        if not args.baseline:
            changes += describe(key, prev.get(key), snap)

    first_run = not prev
    save_state(
        {
            "updated": now_msk(),
            "updated_iso": datetime.now(MSK).isoformat(timespec="seconds"),
            "probes": fresh,
            "failures": fails,
        }
    )

    if args.baseline or first_run:
        print(f"Снимок записан {now_msk()} — сравнивать пока не с чем.")
        for key in PROBES:
            print(summary(key, fresh[key]))
        return 0

    if changes or alarms:
        print(f"═══ ИЗМЕНЕНИЯ {now_msk()} ═══")
        for m in alarms:
            print(m)
        for m in changes:
            print(m)
        journal(alarms + changes)
    elif args.report:
        print(f"Без изменений на {now_msk()}. Текущее состояние:")
        for key in PROBES:
            print(summary(key, fresh[key]))

    if down and (changes or alarms or args.report):
        print("\nНедоступные источники:")
        print("\n".join(down))

    if alarms:
        return 20
    return 10 if changes else 0


if __name__ == "__main__":
    sys.exit(main())
