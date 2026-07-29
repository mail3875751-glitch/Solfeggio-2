#!/usr/bin/env python3
"""Проверка разбора и сравнения на образцах — без сети.

Живые страницы cpk.msu.ru из этого окружения недоступны, поэтому логика
проверяется на HTML, воспроизводящем их структуру: таблица с шапкой,
несколько разделов-конкурсов, пустой столбец ДВИ, который потом заполняют.
Тесты стерегут ровно те переходы, ради которых сторож и написан.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import watch as w  # noqa: E402

FAILED = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}\n       ожидалось: {want!r}\n       получено:  {got!r}")
        FAILED.append(name)


def check_that(name, cond, hint=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {hint}")
        FAILED.append(name)


# --------------------------------------------------------------------------
# Образцы
# --------------------------------------------------------------------------


def submitted_html(dvi_value: str) -> str:
    """Список подавших: два конкурса, наш абитуриент в обоих."""
    def table(section, anchor, dvi):
        return f"""
        <h3 id="{anchor}">{section}</h3>
        <table>
          <thead><tr>
            <th>№</th><th>Номер</th><th>Сумма</th>
            <th>Русский язык</th><th>Обществознание ДВИ</th><th>Согласие</th>
          </tr></thead>
          <tbody>
            <tr><td>1</td><td>2055111</td><td>310</td><td>98</td><td>92</td><td>Да</td></tr>
            <tr><td>2</td><td>{cfg.NUM_SUBMITTED}</td><td>295</td><td>96</td>
                <td>{dvi}</td><td>Нет</td></tr>
          </tbody>
        </table>"""

    return (
        "<html><body><h1>Юридический факультет</h1>"
        + table("Бюджетные места", "submitted_137930", dvi_value)
        + table("Платные места", "submitted_137931", dvi_value)
        + "</body></html>"
    )


def rating_html(year: str, with_us: bool) -> str:
    row = (
        f"<tr><td>7</td><td>{cfg.NUM_AIS}</td><td>295</td><td>85</td>"
        f"<td>Платные места</td></tr>"
        if with_us
        else ""
    )
    return f"""<html><head><title>Конкурсный список {year}</title></head><body>
      <h1>Конкурсные списки {year} года</h1>
      <h3>Платные места</h3>
      <table>
        <tr><th>Место</th><th>Заявление</th><th>Сумма</th><th>ДВИ</th><th>Конкурс</th></tr>
        <tr><td>1</td><td>152102080001</td><td>320</td><td>95</td><td>Платные места</td></tr>
        {row}
      </table></body></html>"""


def news_html(extra=()) -> str:
    items = [
        ("11415", "Результаты ДВИ по обществознанию (основные потоки)"),
        ("11371", "Приём 2026: почему Юрфак МГУ?"),
    ] + list(extra)
    links = "".join(
        f'<div><a href="/news/item_{i}">{t}</a></div>' for i, t in items
    )
    return f"<html><body><h1>Новости</h1>{links}</body></html>"


# --------------------------------------------------------------------------
# Тесты
# --------------------------------------------------------------------------


def test_row_lookup():
    print("\nПоиск строки абитуриента в списке подавших")
    rows = w.rows_containing(submitted_html("-"), cfg.NUM_SUBMITTED)
    check("найден в обоих конкурсах", len(rows), 2)
    check_that(
        "раздел «Платные места» распознан",
        any("Платные места" in r["section"] for r in rows),
        [r["section"] for r in rows],
    )
    paid = next(r for r in rows if "Платные" in r["section"])
    check("шапка сопоставлена со строкой", labelled_ok(paid), True)
    check("столбец ДВИ пуст", w.find_awaited_value(paid), "-")
    check("пустой прочерк не считается заполненным", w.filled("-"), False)

    rows2 = w.rows_containing(submitted_html("85"), cfg.NUM_SUBMITTED)
    paid2 = next(r for r in rows2 if "Платные" in r["section"])
    check("столбец ДВИ прочитан", w.find_awaited_value(paid2), "85")
    check("85 считается заполненным", w.filled("85"), True)
    check_that(
        "чужая строка не подхвачена",
        all(cfg.NUM_SUBMITTED in " ".join(r["cells"]) for r in rows2),
    )


def labelled_ok(row):
    pairs = w.labelled(row)
    return pairs.get("Номер") == cfg.NUM_SUBMITTED and "Обществознание ДВИ" in pairs


def test_dvi_fill_event():
    print("\nГлавное событие №1: заполнение столбца ДВИ")
    old = fake_probe_submitted("-")
    new = fake_probe_submitted("85")
    msgs = w.describe("submitted", old, new)
    check_that(
        "поймано заполнение столбца",
        any("ЗАПОЛНЕН" in m and "85" in m for m in msgs),
        msgs,
    )
    check_that("тишина, когда ничего не менялось", w.describe("submitted", old, old) == [])
    disappeared = {"ok": True, "found": 0, "rows": []}
    check_that(
        "исчезновение из списка замечено",
        any("ПРОПАЛ" in m for m in w.describe("submitted", new, disappeared)),
    )


def fake_probe_submitted(dvi):
    rows = w.rows_containing(submitted_html(dvi), cfg.NUM_SUBMITTED)
    out = []
    for r in rows:
        a = w.find_awaited_value(r)
        out.append(
            {
                "section": r["section"],
                "cells": r["cells"],
                "labelled": w.labelled(r),
                "dvi": a,
                "dvi_filled": w.filled(a),
            }
        )
    return {"ok": True, "found": len(out), "rows": out}


def fake_probe_rating(year, with_us):
    import re
    from bs4 import BeautifulSoup

    html = rating_html(year, with_us)
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ")
    years = sorted(set(re.findall(r"\b(20[2-3]\d)\b", text)))
    rows = w.rows_containing(html, cfg.NUM_AIS)
    return {
        "ok": True,
        "title": w.clean(soup.title.get_text()),
        "headings": [],
        "years_on_page": years,
        "year_expected_present": cfg.YEAR_EXPECTED in years,
        "found": len(rows),
        "rows": [
            {"section": r["section"], "cells": r["cells"], "labelled": w.labelled(r)}
            for r in rows
        ],
        "page_hash": w.sha(re.sub(r"\s+", " ", text)),
    }


def test_rating_year_switch():
    print("\nГлавное событие №2: конкурсные списки переключились на 2026")
    old = fake_probe_rating("2025", with_us=False)
    new = fake_probe_rating("2026", with_us=True)
    msgs = w.describe("rating", old, new)
    check_that(
        "поймано появление 2026 года",
        any(cfg.YEAR_EXPECTED in m and "переключились" in m for m in msgs),
        msgs,
    )
    check_that(
        "поймано появление нашего заявления",
        any("НАЙДЕНО" in m for m in msgs),
        msgs,
    )
    check_that("тишина без изменений", w.describe("rating", old, old) == [])

    moved_old = fake_probe_rating("2026", with_us=True)
    moved_new = fake_probe_rating("2026", with_us=True)
    moved_new["rows"][0]["cells"][0] = "9"
    check_that(
        "сдвиг места в конкурсе замечен",
        any("изменился" in m for m in w.describe("rating", moved_old, moved_new)),
    )


def rating_index_html() -> str:
    """Страница раздела на cpk — оглавление, а не таблица.

    Воспроизводит то, что реально отдаёт cpk.msu.ru/rating/dep_15: заголовок
    с годом и перечень конкурсов ссылками. Номера заявлений лежат внутри них,
    поэтому поиск только по этой странице не находит ничего.
    """
    return """<html><head><title>Центральная приемная комиссия МГУ</title></head>
      <body>
      <h1>Конкурсные списки лиц, прошедших вступительные испытания в МГУ
          имени М.В.Ломоносова в 2026 году по каждому конкурсу</h1>
      <p>Юридический факультет</p>
      <a href="/rating/dep_15/101">Международно-правовая</a>
      <a href="/rating/dep_15/102">Международно-правовая (обучение на договорной основе)</a>
      <a href="/rating/dep_15/103">Юриспруденция</a>
      <a href="/rating/dep_15/104">Юриспруденция (обучение на договорной основе)</a>
      <a href="/rating/dep_15/105">Юриспруденция (особая квота)</a>
      <a href="/about">О приёмной комиссии</a>
      </body></html>"""


def competition_html(with_us: bool) -> str:
    row = (
        f"<tr><td>7</td><td>{cfg.NUM_AIS}</td><td>295</td><td>85</td><td>Нет</td></tr>"
        if with_us
        else ""
    )
    return f"""<html><body><h2>Конкурсный список</h2><table>
      <tr><th>Место</th><th>Заявление</th><th>Сумма</th><th>ДВИ</th><th>Согласие</th></tr>
      <tr><td>1</td><td>152102080001</td><td>320</td><td>95</td><td>Да</td></tr>
      {row}</table></body></html>"""


def test_index_traversal():
    print("\nСтраница раздела — оглавление, а не таблица")
    index = rating_index_html()

    check("на оглавлении номера нет", len(w.rows_containing(index, cfg.NUM_AIS)), 0)

    links = w.sublinks(index, cfg.URL_RATING, "/rating/")
    check("собраны все конкурсы, посторонние ссылки отброшены", len(links), 5)
    check_that(
        "договорная «Юриспруденция» найдена",
        any("Юриспруденция (обучение на договорной основе)" == l["title"] for l in links),
        [l["title"] for l in links],
    )
    check_that(
        "ссылка «О приёмной комиссии» не подхвачена",
        all("О приёмной" not in l["title"] for l in links),
    )

    # Подменяем сеть: оглавление и пять конкурсов, наш номер — в договорной.
    pages = {cfg.URL_RATING: index}
    for n, title in [
        (101, "Международно-правовая"),
        (102, "Международно-правовая (обучение на договорной основе)"),
        (103, "Юриспруденция"),
        (104, "Юриспруденция (обучение на договорной основе)"),
        (105, "Юриспруденция (особая квота)"),
    ]:
        pages[f"https://cpk.msu.ru/rating/dep_15/{n}"] = competition_html(n == 104)

    real_fetch = w.fetch
    w.fetch = lambda url, binary=False: (pages.get(url), None if url in pages else "404")
    try:
        snap = w.probe_rating()
    finally:
        w.fetch = real_fetch

    check("2026 год распознан", snap["year_expected_present"], True)
    check("обход дошёл до вложенных конкурсов", snap["depth"], "вложенные конкурсы")
    check("проверены все пять конкурсов", snap["checked"], 5)
    check("заявление найдено ровно один раз", snap["found"], 1)
    check(
        "конкурс назван по ссылке, а не по вёрстке",
        snap["rows"][0]["section"],
        "Юриспруденция (обучение на договорной основе)",
    )
    check_that(
        "строка содержит балл ДВИ",
        "85" in snap["rows"][0]["cells"],
        snap["rows"][0]["cells"],
    )
    check_that(
        "сохранена ссылка на конкурс",
        snap["rows"][0]["url"].endswith("/104"),
        snap["rows"][0].get("url"),
    )


def test_news_diff():
    print("\nГлавное событие №3: новость о договорах")
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    def probe(html):
        soup = BeautifulSoup(html, "lxml")
        items, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = urljoin(cfg.URL_NEWS, a["href"])
            if "/news/" not in href:
                continue
            t = w.clean(a.get_text())
            if len(t) < 12 or href in seen:
                continue
            seen.add(href)
            items.append({"url": href, "title": t})
        return {"ok": True, "count": len(items), "items": items, "keyword_hits": []}

    old = probe(news_html())
    new = probe(
        news_html([("11500", "Приглашаем к заключению договоров от 230 баллов")])
    )
    msgs = w.describe("news", old, new)
    check("ровно одна новая новость", len(msgs), 1)
    check_that("новость помечена звёздочкой как ключевая", "★" in msgs[0], msgs)
    check_that("тишина без новых новостей", w.describe("news", old, old) == [])


def test_dvi_pdf_guard():
    print("\nСтраховка: пересмотр ведомости ДВИ")
    old = {"ok": True, "sha": "aaa", "bytes": 100, "score": 85,
           "score_matches_expected": True}
    same = dict(old)
    check_that("тишина, пока ведомость та же", w.describe("dvi_pdf", old, same) == [])
    changed = {"ok": True, "sha": "bbb", "bytes": 120, "score": 78,
               "score_matches_expected": False}
    msgs = w.describe("dvi_pdf", old, changed)
    check_that("переопубликация замечена", any("ПЕРЕОПУБЛИКОВАНА" in m for m in msgs))
    check_that("смена балла замечена", any("85 → 78" in m for m in msgs), msgs)
    check_that("расхождение с ожидаемым названо", any("расходится" in m for m in msgs))


def test_availability():
    print("\nМолчание источника не должно успокаивать")
    down = {"ok": False, "error": "HTTP 403"}
    up = {"ok": True, "found": 0, "rows": []}
    check_that("недоступность не выдаётся за изменение", w.describe("submitted", up, down) == [])
    check_that(
        "возврат источника отмечен",
        any("снова отвечает" in m for m in w.describe("submitted", down, up)),
    )
    check_that("первый снимок молчит", w.describe("submitted", None, up) == [])


def test_static_docs():
    print("\nСправочные документы")
    old = {"ok": True, "sha": "x1", "bytes": 10}
    check_that("тишина, пока файл прежний", w.describe("schedule", old, dict(old)) == [])
    msgs = w.describe("schedule", old, {"ok": True, "sha": "x2", "bytes": 11})
    check_that("обновление графика замечено", any("обновлён" in m for m in msgs), msgs)


for t in (
    test_row_lookup,
    test_dvi_fill_event,
    test_rating_year_switch,
    test_index_traversal,
    test_news_diff,
    test_dvi_pdf_guard,
    test_availability,
    test_static_docs,
):
    t()

print("\n" + "─" * 60)
if FAILED:
    print(f"ПРОВАЛЕНО {len(FAILED)}: {', '.join(FAILED)}")
    sys.exit(1)
print("Все проверки пройдены.")
