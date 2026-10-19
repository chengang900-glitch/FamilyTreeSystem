"""传统竖排与欧式横行的 PDF 排版；所有正文按列续页，不截断。"""
import io
import math
import re
from datetime import datetime, timedelta, timezone


def _groups(content):
    groups, current = [], None
    for kind, text in content:
        if kind == 'h':
            current = {'title': str(text), 'entries': []}
            groups.append(current)
        elif kind == 'p':
            if current is None:
                current = {'title': '世系', 'entries': []}
                groups.append(current)
            current['entries'].append({'name': str(text), 'details': []})
        elif kind == 's' and current and current['entries']:
            current['entries'][-1]['details'].append(str(text))
    return groups


def _columns(text, height, size):
    leading = size * 1.25
    count = max(1, math.floor(height / leading))
    result = []
    for line in str(text).replace('\t', ' ').splitlines() or ['']:
        for start in range(0, len(line), count):
            result.append((line[start:start + count], size, leading))
    return result


def _paginate(entries, height, slots):
    """同一人的长文续页时重印姓名，并保证至少一列正文能前进。"""
    pages = [[]]
    for entry in entries:
        name = _columns(entry['name'], height, 12)
        columns = name + [col for detail in entry['details'] for col in _columns(detail, height, 9.5)]
        start = 0
        while start < len(columns):
            if len(pages[-1]) == slots:
                pages.append([])
            page = pages[-1]
            if start and not page:
                header = _columns(entry['name'] + '（续）', height, 12)
                page.extend(header if len(header) < slots else [('续', 9.5, 12)])
            take = min(slots - len(page), len(columns) - start)
            page.extend(columns[start:start + take])
            start += take
        if len(pages[-1]) < slots:
            pages[-1].append(('', 9.5, 12))
    return pages


def _vertical(canvas, font, columns, right, top, step=15):
    for index, (text, size, leading) in enumerate(columns):
        canvas.setFont(font, size)
        x = right - step * (index + .5)
        for row, char in enumerate(text):
            canvas.drawCentredString(x, top - size - row * leading, char)


def _fit_vertical(canvas, font, text, x, y, width, height, size=18):
    if not text:
        return
    while True:
        columns = _columns(text, height - 12, size)
        step = size * 1.3
        if len(columns) * step <= width - 8 or size <= 1:
            break
        size *= .9
    right = x + (width + len(columns) * step) / 2
    _vertical(canvas, font, columns, right, y + height - 6, step)


def _generation_label(title):
    match = re.fullmatch(r'第\s*(\d+)\s*世', title)
    if not match:
        return title.replace(' ', '')
    n = int(match[1])
    digits = '零一二三四五六七八九'
    if n < 10:
        number = digits[n]
    elif n < 100:
        number = (digits[n // 10] if n >= 20 else '') + '十' + (digits[n % 10] if n % 10 else '')
    else:
        number = str(n)
    return number + '世'


def _frame(canvas, font, fam, width, height, page, template):
    x, y, side = 24, 32, 46
    fw, fh = width - 48, height - 64
    canvas.setLineWidth(1.5)
    canvas.rect(x, y, fw, fh)
    canvas.setLineWidth(.5)
    canvas.rect(x + 3, y + 3, fw - 6, fh - 6)
    body_right = x + fw - side
    canvas.line(body_right, y + 3, body_right, y + fh - 3)
    sx, sw = body_right + 3, side - 6
    title_h, hall_h = fh * .4, fh * .24
    canvas.line(sx, y + fh - title_h, x + fw - 3, y + fh - title_h)
    canvas.line(sx, y + hall_h, x + fw - 3, y + hall_h)
    _fit_vertical(canvas, font, fam['name'], sx, y + fh - title_h, sw, title_h, 18)
    _fit_vertical(canvas, font, '世系录' if template == 'traditional' else '横行世系', sx, y + hall_h,
                  sw, fh - title_h - hall_h, 12)
    _fit_vertical(canvas, font, fam.get('hall_name') or '族谱', sx, y + 3, sw, hall_h - 3, 16)
    canvas.setFont(font, 8)
    canvas.drawCentredString(width / 2, 17, f'— {page} —')
    return x + 3, y + 3, body_right - x - 3, fh - 6


def render_vertical_pdf(fam, content, opts):
    from reportlab.pdfgen.canvas import Canvas
    from server.service.printutil import register_font, paper_size

    fam = dict(fam)
    font = register_font()
    width, height = paper_size(opts.get('paper', 'A4'))
    template = opts['template']
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(width, height), pageCompression=1)
    canvas.setTitle(fam['name'])
    canvas.setAuthor(opts.get('compiler') or fam.get('compiler') or '')
    page = 0
    if opts.get('add_cover', True):
        canvas.setLineWidth(1.5)
        canvas.rect(24, 32, width - 48, height - 64)
        _fit_vertical(canvas, font, fam['name'], width * .22, height * .35, width * .56, height * .52, 26)
        canvas.setFont(font, 10)
        compiler = opts.get('compiler') or fam.get('compiler') or ''
        # 署名按纸宽折行，不能让长署名超出边界。
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph
        from xml.sax.saxutils import escape
        para = Paragraph(escape(compiler) + ('　修辑' if compiler else ''),
                         ParagraphStyle('compiler', fontName=font, fontSize=9, leading=13, alignment=1, wordWrap='CJK'))
        _, ph = para.wrap(width - 72, height * .18)
        para.drawOn(canvas, 36, max(72, height * .27 - ph))
        canvas.drawCentredString(width / 2, 48, datetime.now(timezone(timedelta(hours=8))).strftime('%Y 年 %m 月'))
        canvas.showPage()
        page += 1
    groups = _groups(content)
    if not groups:
        page += 1
        _frame(canvas, font, fam, width, height, page, template)
        canvas.setFont(font, 11)
        canvas.drawCentredString((width - 46) / 2, height / 2, '暂无成员资料')
        canvas.showPage()
    for start in range(0, len(groups), 5):
        batch = groups[start:start + 5]
        # 尺寸必须与_frame返回的正文框一致；预估与导出共用本函数。
        bw, bh = width - 97, height - 70
        vertical = template == 'traditional'
        cell_h = bh / 5 if vertical else bh - 30
        col_w = bw - 30 if vertical else bw / 5
        slots = max(2, int((col_w - 12) / 15))
        chunks = [_paginate(g['entries'], cell_h - 20, slots) for g in batch]
        for continuation in range(max(map(len, chunks))):
            page += 1
            bx, by, bw, bh = _frame(canvas, font, fam, width, height, page, template)
            for index in range(5):
                if vertical:
                    row_h = bh / 5
                    top = by + bh - index * row_h
                    if index:
                        canvas.line(bx, top, bx + bw, top)
                    canvas.line(bx + bw - 30, top, bx + bw - 30, top - row_h)
                    right, text_top = bx + bw - 30 - 6, top - 10
                    if index < len(batch) and continuation < len(chunks[index]):
                        label = _generation_label(batch[index]['title'])
                        if continuation:
                            label += '续'
                        badge_h = min(row_h - 16, len(label) * 14 + 14)
                        badge_y = top - row_h / 2 - badge_h / 2
                        canvas.saveState()
                        canvas.setFillColorRGB(0, 0, 0)
                        canvas.roundRect(bx + bw - 26, badge_y, 22, badge_h, 2, fill=1, stroke=0)
                        canvas.setFillColorRGB(1, 1, 1)
                        _fit_vertical(canvas, font, label, bx + bw - 26, badge_y, 22, badge_h, 11)
                        canvas.restoreState()
                else:
                    col_w = bw / 5
                    left = bx + bw - (index + 1) * col_w
                    if index:
                        canvas.line(left + col_w, by, left + col_w, by + bh)
                    canvas.line(left, by + bh - 30, left + col_w, by + bh - 30)
                    right, text_top = left + col_w - 6, by + bh - 40
                    if index < len(batch) and continuation < len(chunks[index]):
                        canvas.setFont(font, 9)
                        label = _generation_label(batch[index]['title']) + ('续' if continuation else '')
                        canvas.drawCentredString(left + col_w / 2, by + bh - 19, label)
                if index < len(chunks) and continuation < len(chunks[index]):
                    _vertical(canvas, font, chunks[index][continuation], right, text_top)
            canvas.showPage()
    canvas.save()
    return buf.getvalue(), page
