# -*- coding: utf-8 -*-
"""Сборка PDF «Буги-вуги Ганон»: music21 -> MusicXML -> verovio -> SVG -> PDF."""

import io
import os

import cairosvg
import verovio
from music21 import bar as bar_module
from music21 import (articulations, chord, clef, duration, expressions, layout,
                     meter, note, pitch, stream, tie)
import xml.etree.ElementTree as ET
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

import content as C

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build')
OUT = os.path.join(HERE, 'out')
XML_DIR = os.path.join(OUT, 'musicxml')
for d in (BUILD, OUT, XML_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------- страница ---
PW, PH = A4                      # 595.28 x 841.89 pt
ML, MR, MT, MB = 48, 48, 48, 52
CW = PW - ML - MR                # ширина наборной полосы

FONT_DIR = '/usr/share/fonts/truetype/dejavu'
pdfmetrics.registerFont(TTFont('DJ', os.path.join(FONT_DIR, 'DejaVuSerif.ttf')))
pdfmetrics.registerFont(TTFont('DJ-B', os.path.join(FONT_DIR, 'DejaVuSerif-Bold.ttf')))
pdfmetrics.registerFont(TTFont('DJS', os.path.join(FONT_DIR, 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('DJS-B', os.path.join(FONT_DIR, 'DejaVuSans-Bold.ttf')))

INK = Color(.11, .11, .12)
MUTED = Color(.42, .42, .45)
RULE = Color(.80, .80, .82)
ACCENT = Color(.55, .22, .10)

# ------------------------------------------------------------------ музыка ---
DEG2IV = {'1': 'P1', '2': 'M2', 'b3': 'm3', '3': 'M3', '4': 'P4',
          'b5': 'd5', '5': 'P5', '6': 'M6', 'b7': 'm7', '7': 'M7'}


def deg_pitch(root, deg, octaves):
    p = root.transpose(DEG2IV[deg])
    for _ in range(octaves):
        p = p.transpose('P8')
    return p


def root_in_band(keyname, lo_midi, hi_midi):
    """Тоника тональности в заданном регистровом коридоре."""
    for octv in range(0, 8):
        p = pitch.Pitch(keyname + str(octv))
        if lo_midi <= p.midi <= hi_midi:
            return p
    raise ValueError(f'{keyname} не укладывается в {lo_midi}-{hi_midi}')


def make_events(events, root, with_fingering=True):
    """Список music21-объектов из спецификации событий.

    with_fingering: True/False либо число — сколько первых событий
    несут аппликатуру (у повторяющихся фигур её достаточно показать
    один раз, иначе цифры забивают нотный текст).
    """
    limit = (len(events) if with_fingering is True
             else 0 if with_fingering is False else int(with_fingering))
    out = []
    for idx, e in enumerate(events):
        if e['degrees'] is None:
            out.append(note.Rest(quarterLength=e['ql']))
            continue

        if e.get('grace'):
            gp = [deg_pitch(root, d, o) for d, o in e['grace']]
            g = (note.Note(gp[0]) if len(gp) == 1 else chord.Chord(gp))
            g.duration = duration.Duration(0.5)
            g = g.getGrace()
            g.duration.slash = True
            out.append(g)

        ps = [deg_pitch(root, d, o) for d, o in e['degrees']]
        obj = note.Note(ps[0]) if len(ps) == 1 else chord.Chord(ps)
        obj.quarterLength = e['ql']
        if idx < limit and e.get('fingers'):
            for f in e['fingers']:                      # снизу вверх
                obj.articulations.append(articulations.Fingering(f))
        if e.get('accent'):
            obj.articulations.append(articulations.Accent())
        out.append(obj)
    return out


def bar(events, root, with_fingering=True, number=None):
    m = stream.Measure(number=number)
    for o in make_events(events, root, with_fingering):
        m.append(o)
    return m


KEY_LABEL = {'C': 'C', 'F': 'F', 'B-': 'Bb', 'E-': 'Eb', 'A-': 'Ab',
             'C#': 'C#', 'F#': 'F#', 'B': 'B', 'E': 'E', 'A': 'A', 'D': 'D', 'G': 'G'}


def label(m, text):
    te = expressions.TextExpression(text)
    te.placement = 'above'
    te.style.fontSize = 9
    te.style.fontWeight = 'bold'
    m.insert(0, te)
    return m


def single_staff_score(spec, clef_obj, band):
    """Упражнение для одной руки: 2 такта в C + секвенция по квинтовому кругу."""
    part = stream.PartStaff()
    part.append(clef_obj)
    part.append(meter.TimeSignature('4/4'))

    n = 1
    c_root = root_in_band('C', *band)
    fing = spec.get('fing_limit', True)
    for i in range(2):
        m = bar(spec['pattern'], c_root, fing if i == 0 else False, n)
        if i == 0:
            label(m, 'C')
        if i == 1:
            m.rightBarline = bar_module.Barline('double')
        part.append(m); n += 1

    if spec.get('seq'):
        for i, k in enumerate(C.CIRCLE_OF_FOURTHS):
            r = root_in_band(k, *band)
            m = bar(spec['pattern'], r, False, n)
            label(m, KEY_LABEL[k])
            part.append(m); n += 1

    sc = stream.Score()
    sc.insert(0, part)
    return sc


def grand_staff_score(rh_bars, lh_bars):
    """Два нотоносца, скреплённые акколадой."""
    top = stream.PartStaff(); top.append(clef.TrebleClef()); top.append(meter.TimeSignature('4/4'))
    bot = stream.PartStaff(); bot.append(clef.BassClef()); bot.append(meter.TimeSignature('4/4'))
    for i, (rb, lb) in enumerate(zip(rh_bars, lh_bars), start=1):
        rb.number = i; lb.number = i
        top.append(rb); bot.append(lb)
    sc = stream.Score()
    sc.insert(0, top); sc.insert(0, bot)
    sc.insert(0, layout.StaffGroup([top, bot], symbol='brace', barTogether=True))
    return sc


def build_exercise_score(spec):
    if spec['hand'] == 'L':
        return single_staff_score(spec, clef.BassClef(), (35, 46))
    if spec['hand'] == 'R':
        return single_staff_score(spec, clef.TrebleClef(), spec.get('band', (63, 74)))

    lo = root_in_band('C', 35, 46)
    hi = root_in_band('C', 58, 69)

    if spec['num'] == 15:                                    # три против восьми
        # правая группируется по три восьмых и переходит через тактовую черту,
        # поэтому поток событий режется по тактам с лигами
        flat = C.CROSS_RH * 2                                 # 24 четверти = 6 тактов
        flat = [flat[0]] + [dict(x, fingers=None) for x in flat[1:]]
        rh, m, filled = [], stream.Measure(), 0.0
        for e in flat:
            left = e['ql']
            first = True
            while left > 1e-9:
                take = min(left, 4.0 - filled)
                o = make_events([e], hi)[0]
                o.quarterLength = take
                if take < e['ql']:
                    t = tie.Tie('start' if first else 'stop')
                    if isinstance(o, chord.Chord):
                        for nn in o.notes:
                            nn.tie = tie.Tie(t.type)
                    else:
                        o.tie = t
                if not first:
                    o.articulations = []
                m.append(o)
                filled += take; left -= take; first = False
                if filled >= 4.0 - 1e-9:
                    rh.append(m); m = stream.Measure(); filled = 0.0
        if filled > 0:
            rh.append(m)
        lh = [bar(C.CROSS_LH, lo, i == 0) for i in range(len(rh))]
        return grand_staff_score(rh, lh)

    if spec['num'] == 16:
        rh = [bar(C.SYNC_RH, hi, i == 0) for i in range(8)]
        lh = [bar(C.SYNC_LH, lo, i == 0) for i in range(8)]
        return grand_staff_score(rh, lh)

    # №17 — блюзовый квадрат
    rh, lh = [], []
    for i, deg in enumerate(C.BLUES_12):
        lr = deg_pitch(lo, deg, 0)
        hr = deg_pitch(hi, deg, 0)
        if lr.midi > 46:
            lr = lr.transpose('-P8')
        lh.append(bar(C.SHUFFLE, lr, i == 0))
        rh.append(bar(C.BLUES_RH, hr, i == 0))
    return grand_staff_score(rh, lh)


# --------------------------------------------------------------- гравировка ---
def postprocess_xml(path, breaks_before=(), brace=False):
    """music21 не выгружает акколаду и разрывы строк — дописываем их вручную."""
    tree = ET.parse(path)
    root = tree.getroot()

    if brace:
        pl = root.find('part-list')
        start = ET.Element('part-group', {'number': '1', 'type': 'start'})
        ET.SubElement(start, 'group-symbol').text = 'brace'
        ET.SubElement(start, 'group-barline').text = 'yes'
        pl.insert(0, start)
        pl.append(ET.Element('part-group', {'number': '1', 'type': 'stop'}))

    if breaks_before:
        want = {str(n) for n in breaks_before}
        for part in root.findall('part'):
            for m in part.findall('measure'):
                if m.get('number') in want:
                    m.insert(0, ET.Element('print', {'new-system': 'yes'}))
    tree.write(path, encoding='UTF-8', xml_declaration=True)


def write_xml(score, tag, breaks_before=(), brace=False):
    xml = os.path.join(XML_DIR, f'{tag}.musicxml')
    score.write('musicxml', fp=xml)
    postprocess_xml(xml, breaks_before, brace)
    return xml


def render_xml(xml, page_width, encoded=True):
    tk = verovio.toolkit()
    tk.setOptions({
        'scale': 100,
        'pageWidth': int(page_width),
        'pageHeight': 60000,
        'adjustPageHeight': True,
        'pageMarginTop': 0, 'pageMarginBottom': 0,
        'pageMarginLeft': 45, 'pageMarginRight': 10,
        'header': 'none', 'footer': 'none',
        'breaks': 'encoded' if encoded else 'auto',
        'spacingStaff': 14, 'spacingSystem': 12,
        'svgViewBox': True,
    })
    if not tk.loadFile(xml):
        raise RuntimeError(f'verovio не смог загрузить {xml}')
    pdf_bytes = cairosvg.svg2pdf(bytestring=tk.renderToSVG(1).encode('utf-8'))
    return PdfReader(io.BytesIO(pdf_bytes)).pages[0]


def engrave_to_fit(xml, avail_h, pw_min=1150, pw_max=5200):
    """Подбирает ширину виртуальной страницы так, чтобы ноты заполнили
    и всю наборную ширину, и всю оставшуюся высоту."""
    probe = render_xml(xml, 1600)
    h = float(probe.mediabox.height)          # не зависит от pageWidth
    target_ratio = avail_h / CW               # желаемое h/w
    pw = (h / target_ratio) / 0.75            # 1 условная единица = 0.75 pt
    pw = max(pw_min, min(pw_max, pw))
    return render_xml(xml, pw)


def breaks_plan(spec):
    """Номера тактов, с которых начинается новая строка."""
    if spec['hand'] in ('L', 'R'):
        return (3, 6, 9, 12)             # [1-2] [3-5] [6-8] [9-11] [12-14]
    if spec['num'] == 15:
        return (4,)                      # 6 тактов: [1-3] [4-6]
    if spec['num'] == 16:
        return (5,)                      # 8 тактов: [1-4] [5-8]
    return (4, 7, 10)                    # №17: 12 тактов по три


# ------------------------------------------------------------------ вёрстка ---
def wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if pdfmetrics.stringWidth(t, font, size) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_paragraph(c, text, x, y, width, font='DJ', size=9.6, leading=13.4, color=INK):
    c.setFont(font, size); c.setFillColor(color)
    for line in wrap(text, font, size, width):
        c.drawString(x, y, line)
        y -= leading
    return y


PART_TITLES = {
    1: 'Часть I. Левая рука — басовые фигуры',
    2: 'Часть II. Правая рука',
    3: 'Часть III. Координация',
    4: 'Часть IV. Применение',
}


def footer(c, page_no):
    c.setFont('DJ', 8); c.setFillColor(MUTED)
    c.drawCentredString(PW / 2, MB - 24, str(page_no))


def focus_box(c, text, y):
    lines = wrap(text, 'DJ', 9, CW - 22)[:3]
    h = 20 + 11.5 * len(lines)
    c.setFillColor(Color(.965, .955, .942))
    c.setStrokeColor(Color(.875, .855, .80)); c.setLineWidth(.6)
    c.rect(ML, y - h, CW, h, fill=1, stroke=1)
    c.setFont('DJS-B', 7.4); c.setFillColor(ACCENT)
    c.drawString(ML + 11, y - 13, 'НА ЧТО СМОТРЕТЬ')
    c.setFont('DJ', 9); c.setFillColor(INK)
    yy = y - 26
    for ln in lines:
        c.drawString(ML + 11, yy, ln)
        yy -= 11.5
    return y - h


def render_head(c, spec, show_part_header):
    """Шапка страницы. При c=None только считает высоту, ничего не рисует."""
    draw = c is not None
    y = PH - MT

    if show_part_header:
        if draw:
            c.setFont('DJS-B', 8.4); c.setFillColor(ACCENT)
            c.drawString(ML, y, PART_TITLES[spec['part']].upper())
        y -= 8
        if draw:
            c.setStrokeColor(ACCENT); c.setLineWidth(1.1)
            c.line(ML, y, ML + CW, y)
        y -= 26

    if draw:
        c.setFont('DJS-B', 16.5); c.setFillColor(INK)
        c.drawString(ML, y, f"№ {spec['num']}. {spec['title']}")
    y -= 14
    if spec.get('subtitle'):
        if draw:
            c.setFont('DJ', 10); c.setFillColor(MUTED)
            c.drawString(ML, y, spec['subtitle'])
        y -= 6
    y -= 12
    if draw:
        c.setStrokeColor(RULE); c.setLineWidth(.6)
        c.line(ML, y, ML + CW, y)
    y -= 18

    if draw:
        y = draw_paragraph(c, spec['text'], ML, y, CW)
    else:
        y -= 13.4 * len(wrap(spec['text'], 'DJ', 9.6, CW))
    if spec.get('swing'):
        y -= 4
        if draw:
            c.setFont('DJ', 9); c.setFillColor(ACCENT)
            c.drawString(ML, y, 'Восьмые свингуются: играйте триольно.')
        y -= 13
    return y - 16


def score_budget(spec, show_part_header):
    """Сколько места по вертикали остаётся под ноты."""
    y = render_head(None, spec, show_part_header)
    focus_h = 20 + 11.5 * len(wrap(spec['focus'], 'DJ', 9, CW - 22)[:3])
    return y, y - (MB + focus_h + 20)


def compose_exercise(spec, score_page, show_part_header, page_no):
    """Страница упражнения: заголовок, текст, ноты, врезка."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    y = render_head(c, spec, show_part_header)

    sw = float(score_page.mediabox.width)
    sh = float(score_page.mediabox.height)
    _, avail_h = score_budget(spec, show_part_header)
    k = min(CW / sw, avail_h / sh)
    score_y = y - sh * k

    focus_box(c, spec['focus'], score_y - 20)
    footer(c, page_no)
    c.save()

    base = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    x = ML + (CW - sw * k) / 2
    base.merge_transformed_page(
        score_page, Transformation().scale(k).translate(x, score_y))
    return base


# ------------------------------------------------------------- преамбула -----
def title_page():
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setFillColor(INK)
    c.setFont('DJS-B', 34); c.drawString(ML, PH - 210, 'Буги-вуги')
    c.setFont('DJS-B', 34); c.drawString(ML, PH - 252, 'Ганон')
    c.setStrokeColor(ACCENT); c.setLineWidth(2.4)
    c.line(ML, PH - 276, ML + 150, PH - 276)
    c.setFont('DJ', 13); c.setFillColor(MUTED)
    c.drawString(ML, PH - 306, '17 упражнений с аппликатурой')
    c.drawString(ML, PH - 326, 'на технику буги-вуги и барелхаус-фортепиано')

    c.setFont('DJ', 9.6); c.setFillColor(INK)
    y = 320
    for ln in wrap('Оригинальный сборник, составленный по ханоновскому принципу: '
                   'каждая фигура даётся в до мажоре с аппликатурой, затем секвенцией '
                   'по квинтовому кругу через все двенадцать тональностей. Систематика '
                   'басовых фигур опирается на приложение Питера Сильвестра, постановка '
                   'движения — на ротационный принцип школы Таубман — Голандски.',
                   'DJ', 9.6, CW - 120):
        c.drawString(ML, y, ln); y -= 14
    c.setFont('DJ', 8.4); c.setFillColor(MUTED)
    c.drawString(ML, MB + 6, 'Материал оригинальный. Существующие сборники не воспроизводятся.')
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue())).pages[0]


HOWTO = [
    ('Ханоновский принцип', [
        'Каждое упражнение построено одинаково. Первый такт — фигура в до мажоре с '
        'аппликатурой, второй — тот же такт без цифр для самопроверки. Дальше, после '
        'двойной черты, та же фигура идёт секвенцией по квинтовому кругу и через '
        'одиннадцать тональностей возвращается в до мажор. Тональность каждого такта '
        'подписана буквой над нотоносцем.',
        'Аппликатура выписана только в модели, а у однородных фигур — лишь на первой '
        'группе. Это сделано намеренно: в буги-вуги аппликатура определяется не нотами, '
        'а положением руки, и должна сохраняться при переносе — меняется только выход '
        'на чёрные клавиши.']),
    ('Лестница темпов', [
        'Каждую фигуру проводите через четыре скорости: 60, 80, 100, 132 к четверти. '
        'На следующую ступень переходите только тогда, когда на предыдущей играете '
        'три раза подряд без сбоя. Метроном ставьте на вторую и четвёртую долю, а не на все четыре.']),
    ('Ротация вместо пальцев', [
        'Ломаная октава, качание на терции и разбитые децимы играются поворотом предплечья, '
        'а не независимыми пальцами. Проверка простая: положите правую ладонь на левое '
        'предплечье — при верном движении вы чувствуете поворот кости, а не напряжение мышц.',
        'Пальцевая игра в этих фигурах даёт зажим за считанные такты и приводит к травме. '
        'Если в предплечье появляется жжение — остановитесь, а не «дотерпите такт до конца».']),
    ('Порядок работы', [
        'Части I и II проходятся руками отдельно. К части III переходите только тогда, '
        'когда любая фигура левой руки идёт без участия внимания — левая в этом стиле '
        'не должна слушать правую.',
        'Разумный режим: одна фигура левой и одна правой в день, по десять–пятнадцать минут '
        'каждая, с полным опусканием рук между подходами.']),
]


def howto_page(page_no):
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    y = PH - MT
    c.setFont('DJS-B', 20); c.setFillColor(INK)
    c.drawString(ML, y, 'Как пользоваться сборником')
    y -= 12
    c.setStrokeColor(ACCENT); c.setLineWidth(1.6)
    c.line(ML, y, ML + 118, y)
    y -= 30

    for head, paras in HOWTO:
        c.setFont('DJS-B', 11.4); c.setFillColor(ACCENT)
        c.drawString(ML, y, head)
        y -= 17
        for p in paras:
            y = draw_paragraph(c, p, ML, y, CW)
            y -= 7
        y -= 12
    footer(c, page_no)
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue())).pages[0]


def contents_page(page_no):
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    y = PH - MT
    c.setFont('DJS-B', 20); c.setFillColor(INK)
    c.drawString(ML, y, 'Содержание')
    y -= 12
    c.setStrokeColor(ACCENT); c.setLineWidth(1.6)
    c.line(ML, y, ML + 78, y)
    y -= 30

    cur_part = None
    for i, spec in enumerate(C.EXERCISES):
        if spec['part'] != cur_part:
            cur_part = spec['part']
            y -= 6
            c.setFont('DJS-B', 9); c.setFillColor(ACCENT)
            c.drawString(ML, y, PART_TITLES[cur_part].upper())
            y -= 16
        c.setFont('DJ', 10); c.setFillColor(INK)
        label = f"№ {spec['num']}.  {spec['title']}"
        c.drawString(ML + 8, y, label)
        pg = 4 + i
        c.setFont('DJ', 10); c.setFillColor(MUTED)
        c.drawRightString(ML + CW, y, str(pg))
        w = pdfmetrics.stringWidth(label, 'DJ', 10)
        c.setStrokeColor(RULE); c.setLineWidth(.4)
        c.setDash(1, 3)
        c.line(ML + 14 + w, y + 2.5, ML + CW - 16, y + 2.5)
        c.setDash()
        y -= 17
    footer(c, page_no)
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue())).pages[0]


def main():
    writer = PdfWriter()
    writer.add_page(title_page())
    writer.add_page(howto_page(2))
    writer.add_page(contents_page(3))

    seen_parts = set()
    for i, spec in enumerate(C.EXERCISES):
        header = spec['part'] not in seen_parts
        seen_parts.add(spec['part'])
        score = build_exercise_score(spec)
        xml = write_xml(score, f"ex{spec['num']:02d}",
                        breaks_plan(spec), brace=(spec['hand'] == 'B'))
        _, avail_h = score_budget(spec, header)
        page = engrave_to_fit(xml, avail_h)
        writer.add_page(compose_exercise(spec, page, header, 4 + i))
        print(f"  № {spec['num']:>2}  {spec['title']}")

    out = os.path.join(OUT, 'Boogie-Woogie-Hanon.pdf')
    with open(out, 'wb') as f:
        writer.write(f)
    print('\nГотово:', out, os.path.getsize(out) // 1024, 'КБ,', len(writer.pages), 'страниц')


if __name__ == '__main__':
    main()
