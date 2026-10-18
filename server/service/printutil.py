"""付印输出：PDF（ReportLab）与 Word（python-docx）"""
from pathlib import Path

PAPER_MM = {
    'A4': (210, 297),
    'A5': (148, 210),
    '16K': (195, 270),
    '32K': (130, 184),
}

FONT_CANDIDATES = [
    ('CJK', 'C:/Windows/Fonts/msyh.ttc', 0),
    ('CJK', 'C:/Windows/Fonts/simsun.ttc', 0),
    ('CJK', 'C:/Windows/Fonts/simhei.ttf', 0),
    ('CJK', 'C:/Windows/Fonts/simsun.ttf', 0),
    ('CJK', '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc', 0),
    ('CJK', '/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc', 0),
    ('CJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 0),
]

_font_registered = False
_font_name = 'Helvetica'


def register_font():
    """注册中文字体，返回可用字体名"""
    global _font_registered, _font_name
    if _font_registered:
        return _font_name
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        for name, path, idx in FONT_CANDIDATES:
            if Path(path).exists():
                try:
                    pdfmetrics.registerFont(TTFont(name, path, subfontIndex=idx))
                    _font_name = name
                    break
                except Exception:
                    continue
    except Exception:
        pass
    _font_registered = True
    return _font_name


def paper_size(key):
    from reportlab.lib.pagesizes import mm
    w, h = PAPER_MM.get((key or 'A4').upper(), PAPER_MM['A4'])
    return w * mm, h * mm
