#!/usr/bin/env python3
"""Сводка по журналу питания: дни, текущая неделя, тренд веса.

Запуск из корня папки: python3 scripts/report.py [--days N]
Нормы берутся из profile.md (строки «Дневная норма» и «Пол дневной нормы»).
"""
import argparse
import csv
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIVITY_DISCOUNT = 0.5  # в бюджет возвращается половина расчётного расхода

def read_norm(name):
    text = (ROOT / "profile.md").read_text(encoding="utf-8")
    m = re.search(rf"{name}:\s*([\d\s]+)\s*ккал", text)
    return int(m.group(1).replace(" ", "")) if m else None

def load_rows(path):
    p = ROOT / path
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("date")]

def num(row, key):
    try:
        return float(row.get(key) or 0)
    except ValueError:
        return 0.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="сколько последних дней показать")
    args = ap.parse_args()

    norm = read_norm("Дневная норма")
    floor = read_norm(r"Пол дневной нормы \(85% BMR\)")
    if norm is None:
        print("В profile.md не заполнена дневная норма — сначала первый сеанс с помощником.")

    days = {}
    for r in load_rows("data/journal.csv"):
        d = days.setdefault(r["date"], {"in": 0.0, "out": 0.0, "p": 0.0, "f": 0.0, "c": 0.0, "alco": 0.0})
        kcal = num(r, "kcal")
        if r["type"] in ("еда", "алкоголь"):
            d["in"] += kcal
            d["p"] += num(r, "protein"); d["f"] += num(r, "fat"); d["c"] += num(r, "carbs")
            if r["type"] == "алкоголь":
                d["alco"] += kcal
        elif r["type"] in ("тренировка", "шаги"):
            d["out"] += kcal
    if not days:
        print("Журнал пуст.")
        return

    print(f"{'дата':<12}{'съедено':>9}{'Б':>6}{'Ж':>6}{'У':>6}{'расход*':>9}{'баланс':>9}{'к норме':>9}")
    for d in sorted(days)[-args.days:]:
        v = days[d]
        credited = v["out"] * ACTIVITY_DISCOUNT
        net = v["in"] - credited
        vs = f"{net - norm:+.0f}" if norm else "—"
        print(f"{d:<12}{v['in']:>9.0f}{v['p']:>6.0f}{v['f']:>6.0f}{v['c']:>6.0f}{credited:>9.0f}{net:>9.0f}{vs:>9}")
    print("* расход тренировок и шагов уже с дисконтом 50%")

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_days = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    spent = sum(days[d]["in"] - days[d]["out"] * ACTIVITY_DISCOUNT for d in week_days if d in days)
    logged = sum(1 for d in week_days if d in days and days[d]["in"] > 0)
    if norm:
        budget = norm * 7
        left = budget - spent
        remaining_days = 7 - (today.weekday() + 1) + (0 if today.isoformat() in days else 1)
        print(f"\nНеделя {monday.isocalendar()[1]}: потрачено {spent:.0f} из {budget} ккал "
              f"(дней с записями: {logged}). Остаток: {left:+.0f} ккал.")
        if remaining_days > 0:
            per_day = left / remaining_days
            note = ""
            if floor and per_day < floor:
                note = f" — ниже пола {floor}, остаток переносится на следующую неделю"
            print(f"На каждый из оставшихся {remaining_days} дн.: {per_day:.0f} ккал{note}.")

    weights = [(r["date"], num(r, "weight_kg")) for r in load_rows("data/measurements.csv") if num(r, "weight_kg") > 0]
    if weights:
        weights.sort()
        last7 = [w for _, w in weights[-7:]]
        prev7 = [w for _, w in weights[-14:-7]]
        avg = sum(last7) / len(last7)
        line = f"\nВес: последний {weights[-1][1]:.1f} кг ({weights[-1][0]}), среднее за 7 замеров {avg:.2f} кг"
        if prev7:
            line += f", тренд {avg - sum(prev7)/len(prev7):+.2f} кг к предыдущей неделе"
        print(line + ".")

if __name__ == "__main__":
    sys.exit(main())
