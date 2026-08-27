"""最小的 .xlsx 写入器——不装任何第三方库。

Mac 上没有 openpyxl，也不想为了导一张表去装。xlsx 本身就是一个 zip，
里面几个固定的 XML，字符串直接内联（`t="inlineStr"`）就不用维护共享字符串表。

用法：

    from xlsx import Sheet, write_xlsx

    write_xlsx("out.xlsx", [
        Sheet("角色练度", ["名字", "等级"], [["莱万汀", 90], ["洛茜", 90]]),
    ])

数字会写成数字（能在 Excel 里排序、求和），其余一律当文本。
表头加粗并冻结首行，列宽按内容估算（中日韩字符按两个字宽算）。
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheets}
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


@dataclass
class Sheet:
    name: str
    header: list[str]
    rows: list[list] = field(default_factory=list)


def _col(n: int) -> str:
    """0 → A，25 → Z，26 → AA。"""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _width(text: str) -> int:
    """中日韩字符占两个字宽，别让中文列挤成一团。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in str(text))


def _cell(ref: str, value, style: int) -> str:
    st = f' s="{style}"' if style else ""
    if isinstance(value, bool) or value is None or value == "":
        return f'<c r="{ref}"{st}/>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{st}><v>{value}</v></c>'
    txt = escape(str(value))
    return f'<c r="{ref}"{st} t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    widths = [min(60, max(_width(h) + 2,
                          *(_width(r[i]) + 2 for r in sheet.rows) if sheet.rows else (0,)))
              for i, h in enumerate(sheet.header)]
    cols = "".join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(widths))
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '<sheetViews><sheetView workbookViewId="0">',
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>',
        '</sheetView></sheetViews>',
        f'<cols>{cols}</cols><sheetData>',
        '<row r="1">'
        + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(sheet.header))
        + "</row>",
    ]
    for n, row in enumerate(sheet.rows, start=2):
        out.append(f'<row r="{n}">'
                   + "".join(_cell(f"{_col(i)}{n}", v, 0) for i, v in enumerate(row))
                   + "</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def write_xlsx(path: str, sheets: list[Sheet]) -> str:
    ct = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(len(sheets)))
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
          ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          "<sheets>"
          + "".join(f'<sheet name="{escape(s.name)}" sheetId="{i+1}" r:id="rId{i+1}"/>'
                    for i, s in enumerate(sheets))
          + "</sheets></workbook>")
    wbr = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/'
                     f'officeDocument/2006/relationships/worksheet" '
                     f'Target="worksheets/sheet{i+1}.xml"/>' for i in range(len(sheets)))
           + f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/'
             'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
           + "</Relationships>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT.format(sheets=ct))
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbr)
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", _sheet_xml(s))
    return path
