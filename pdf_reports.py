"""A4 collection report PDF generation for SM MOIDEEN TRADERS.

The report is built with reportlab platypus. Tables are packed page by page so
that every page repeat its column headers, shows the balance brought forward
from the previous page, and shows the balance carried forward to the next page.
A running balance column makes the movement of every row visible.
"""

from datetime import datetime
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, PAGE_H = A4
MARGIN_X = 11 * mm
MARGIN_TOP = 15 * mm
MARGIN_BOTTOM = 15 * mm
CONTENT_W = PAGE_W - (2 * MARGIN_X)
CONTENT_H = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM

COL_PAD = 3

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _register_fonts():
    """Use a Unicode TrueType font when available so the rupee sign renders."""
    global FONT, FONT_BOLD
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidate_pairs = [
        (os.path.join(windir, "Fonts", "arial.ttf"), os.path.join(windir, "Fonts", "arialbd.ttf")),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    for regular, bold in candidate_pairs:
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("ReportSans", regular))
                pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
                FONT = "ReportSans"
                FONT_BOLD = "ReportSans-Bold"
                return
            except Exception:
                continue


_register_fonts()

S_TITLE = ParagraphStyle("title", fontName=FONT_BOLD, fontSize=15, leading=18,
                         alignment=TA_CENTER, textColor=colors.HexColor("#14532d"))
S_SUBTITLE = ParagraphStyle("subtitle", fontName=FONT, fontSize=8.5, leading=11,
                            alignment=TA_CENTER, textColor=colors.HexColor("#4b5563"))
S_SECTION = ParagraphStyle("section", fontName=FONT_BOLD, fontSize=10, leading=13,
                           alignment=TA_CENTER, textColor=colors.HexColor("#14532d"))
S_CELL = ParagraphStyle("cell", fontName=FONT, fontSize=7.5, leading=9.6,
                        alignment=TA_LEFT, textColor=colors.HexColor("#1f2937"))
S_CELL_R = ParagraphStyle("cellr", parent=S_CELL, alignment=TA_RIGHT)
S_HEAD = ParagraphStyle("head", fontName=FONT_BOLD, fontSize=7.3, leading=9,
                        alignment=TA_CENTER, textColor=colors.white)
S_METRIC_LABEL = ParagraphStyle("mlabel", fontName=FONT, fontSize=6.6, leading=8,
                                alignment=TA_CENTER, textColor=colors.HexColor("#6b7280"))
S_METRIC_VALUE = ParagraphStyle("mvalue", fontName=FONT_BOLD, fontSize=10, leading=12,
                                alignment=TA_CENTER, textColor=colors.HexColor("#14532d"))
S_NOTE = ParagraphStyle("note", fontName=FONT, fontSize=7.5, leading=10,
                        textColor=colors.HexColor("#6b7280"))

COL_WIDTHS = [47, 96, 58, 56, 62, 52, 52, 54, 56]
HEADERS = ["Token", "Customer", "Phone", "Collection Date", "Items",
           "Total", "Paid", "Balance", "Running Balance"]
NUMERIC_COLS = (5, 6, 7, 8)

GRID_COLOR = colors.HexColor("#d1d5db")
PRIMARY = colors.HexColor("#14532d")
LIGHT_ROW = colors.HexColor("#f8f8f5")


def _indian_group(digits: str) -> str:
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def inr(value) -> str:
    """Format a number as Indian rupees with the rupee sign."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    negative = amount < 0
    amount = abs(amount)
    whole = int(amount)
    paise = int(round((amount - whole) * 100))
    if paise == 100:
        whole += 1
        paise = 0
    text = "\u20B9" + _indian_group(str(whole)) + "." + f"{paise:02d}"
    return ("-" + text) if negative else text


def fmt_date(value) -> str:
    if not value:
        return "-"
    text = str(value)
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return text


def _esc(value) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _items_text(booking) -> str:
    parts = []
    mutton = float(booking.get("mutton_qty") or 0)
    chicken = float(booking.get("chicken_qty") or 0)
    if mutton > 0:
        parts.append(f"{mutton:g} Padi")
    if chicken > 0:
        parts.append(f"{chicken:g} Kg")
    return " / ".join(parts) if parts else "-"


def _height(flowable, width=CONTENT_W) -> float:
    return flowable.wrap(width, 100000)[1]


class _NumberedCanvas(pdfcanvas.Canvas):
    """Adds 'Page X of Y' and the configured footer message to every page."""

    def __init__(self, *args, footer_text="", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_states = []
        self._footer_text = footer_text or ""

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        for index, state in enumerate(self._saved_states):
            self.__dict__.update(state)
            self._draw_footer(total, index == total - 1)
            super().showPage()
        super().save()

    def _draw_footer(self, total, is_last):
        self.saveState()
        self.setFont(FONT, 7)
        self.setFillColor(colors.HexColor("#6b7280"))
        y = MARGIN_BOTTOM / 2
        if is_last and self._footer_text:
            self.drawCentredString(PAGE_W / 2, y + 11, self._footer_text[:130])
        self.drawCentredString(PAGE_W / 2, y, f"Page {self._pageNumber} of {total}")
        self.restoreState()


def _paragraph(text, style):
    return Paragraph(_esc(text), style)


def _header_row():
    return [Paragraph(_esc(h), S_HEAD) for h in HEADERS]


def _data_row(booking, running_balance):
    return [
        str(booking.get("token_number") or ""),
        _paragraph(booking.get("customer_name") or "", S_CELL),
        str(booking.get("phone") or ""),
        fmt_date(booking.get("function_date")),
        _paragraph(_items_text(booking), S_CELL),
        inr(booking.get("grand_total")),
        inr(booking.get("advance_paid")),
        inr(booking.get("balance")),
        inr(running_balance),
    ]


def _measured_row_heights(data_rows, opening_index=None, closing_index=None):
    """Return the exact rendered height of every row in a table.

    ReportLab adds more internal leading than a naive calculation suggests, so
    pagination must rely on ReportLab's own measurements or a page can overflow
    and be auto-split (which would lose the carry-forward balance rows).
    """
    table = Table(data_rows, colWidths=COL_WIDTHS)
    table.setStyle(_table_style(len(data_rows), opening_index, closing_index))
    table.wrap(CONTENT_W, 10 ** 9)
    return list(table._rowHeights)


def _table_style(row_count, opening_index=None, closing_index=None):
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), COL_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), COL_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), COL_PAD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), COL_PAD),
    ]
    for col in NUMERIC_COLS:
        commands.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
    commands.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_ROW]))
    if opening_index is not None:
        commands += [
            ("SPAN", (0, opening_index), (-1, opening_index)),
            ("BACKGROUND", (0, opening_index), (-1, opening_index), colors.HexColor("#eff6ff")),
            ("ALIGN", (0, opening_index), (-1, opening_index), "LEFT"),
        ]
    if closing_index is not None:
        commands += [
            ("SPAN", (0, closing_index), (-1, closing_index)),
            ("BACKGROUND", (0, closing_index), (-1, closing_index), colors.HexColor("#fef9c3")),
            ("ALIGN", (0, closing_index), (-1, closing_index), "LEFT"),
            ("FONTNAME", (0, closing_index), (-1, closing_index), FONT_BOLD),
        ]
    return TableStyle(commands)


def _summary_table(totals, opening, closing):
    def metric(label, value):
        return [Paragraph(_esc(label), S_METRIC_LABEL), Paragraph(_esc(value), S_METRIC_VALUE)]

    cells = [
        metric("Total Orders", str(totals.get("count", 0))),
        metric("Total Revenue", inr(totals.get("total", 0))),
        metric("Advance Collected", inr(totals.get("paid", 0))),
        metric("Opening Balance B/F", inr(opening)),
        metric("Period Balance", inr(totals.get("balance", 0))),
        metric("Closing Balance", inr(closing)),
    ]
    data = [
        [cells[0][0], cells[1][0], cells[2][0]],
        [cells[0][1], cells[1][1], cells[2][1]],
        [cells[3][0], cells[4][0], cells[5][0]],
        [cells[3][1], cells[4][1], cells[5][1]],
    ]
    table = Table(data, colWidths=[CONTENT_W / 3.0] * 3)
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (0, -1), 0.5, GRID_COLOR),
        ("BOX", (1, 0), (1, -1), 0.5, GRID_COLOR),
        ("BOX", (2, 0), (2, -1), 0.5, GRID_COLOR),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, GRID_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def build_report_pdf(settings, title, start_date, end_date, bookings, opening_balance,
                     totals, generated_at, search=None):
    """Return the report as PDF bytes, packed page by page on A4."""
    import io

    settings = settings or {}
    business = (settings.get("business_name") or "SM MOIDEEN TRADERS").strip()
    address = (settings.get("address") or "").strip()
    phone = (settings.get("phone") or "").strip()
    footer = (settings.get("receipt_footer") or "").strip()

    opening = round(float(opening_balance or 0), 2)
    booking_balance = round(float(totals.get("balance", 0) or 0), 2)
    closing = round(opening + booking_balance, 2)
    period = f"Period: {fmt_date(start_date)} to {fmt_date(end_date)}"

    contact = "  |  ".join(part for part in (address, f"Phone: {phone}" if phone else "") if part)

    first_header = [
        Paragraph(_esc(business), S_TITLE),
        Paragraph(_esc(contact), S_SUBTITLE) if contact else Spacer(1, 0),
        Paragraph(_esc(title), S_SECTION),
        Paragraph(_esc(period), S_SUBTITLE),
        Paragraph(_esc(f"Generated: {generated_at}"), S_SUBTITLE),
    ]
    if search and search.strip():
        first_header.append(Paragraph(_esc(f"Filter: {search.strip()}"), S_SUBTITLE))
    first_header.append(Spacer(1, 6))
    summary = _summary_table(totals, opening, closing)
    first_header.append(summary)
    qty_note = Paragraph(
        _esc(f"Mutton Biriyani: {float(totals.get('mutton', 0)):g} Padi   |   "
             f"Chicken 65: {float(totals.get('chicken', 0)):g} Kg"),
        S_NOTE,
    )
    first_header.append(Spacer(1, 5))
    first_header.append(qty_note)
    first_header.append(Spacer(1, 8))
    first_top_height = sum(_height(f) for f in first_header)

    continuation_header = [
        Paragraph(_esc(business), S_SECTION),
        Paragraph(_esc(f"{title} (continued)  |  {fmt_date(start_date)} to {fmt_date(end_date)}"), S_SUBTITLE),
        Spacer(1, 5),
    ]
    continuation_height = sum(_height(f) for f in continuation_header)

    def opening_paragraph(value):
        return Paragraph(_esc(f"Opening balance brought forward: {inr(value)}"), S_CELL)

    # Running balance per data row, never reset at page breaks.
    running = opening
    rows = []
    for booking in bookings:
        running = round(running + float(booking.get("balance") or 0), 2)
        rows.append((_data_row(booking, running), running))

    if not rows:
        note = Paragraph(_esc("No transactions found in the selected period."), S_CELL)
        rows = [([note] + [""] * (len(HEADERS) - 1), opening)]

    # Exact rendered heights straight from ReportLab. The header is measured
    # together with the data rows so its height matches on every page.
    data_rows = [_header_row()] + [cells for cells, _ in rows]
    measured = _measured_row_heights(data_rows)
    header_height = measured[0]
    data_heights = measured[1:]

    # Opening/closing rows are spanned across the full width, so they are always
    # a single line regardless of the amount. Measure a deliberately long
    # placeholder to guarantee they never wrap unnoticed.
    opening_sample = [opening_paragraph(99_99_99_999)] + [""] * (len(HEADERS) - 1)
    opening_row_height = _measured_row_heights([opening_sample], opening_index=0)[0]
    closing_sample = [Paragraph(
        _esc(f"Page closing balance: {inr(99_99_99_999)} (carried forward to next page)"),
        S_CELL,
    )] + [""] * (len(HEADERS) - 1)
    closing_row_height = _measured_row_heights([closing_sample], closing_index=0)[0]

    # Reserve a small safety margin so rounding in the frame never forces an
    # automatic split of a page that was packed to fit.
    SAFETY = 6.0
    first_available = (CONTENT_H - first_top_height - header_height
                       - closing_row_height - SAFETY)
    other_available = (CONTENT_H - continuation_height - header_height
                       - opening_row_height - closing_row_height - SAFETY)

    pages = []          # list of dicts: {"rows": [(cells, running)], "closing": float}
    current = []
    used = 0.0
    available = first_available
    for index, (cells, row_running) in enumerate(rows):
        height = data_heights[index]
        if current and used + height > available:
            pages.append({"rows": current, "closing": current[-1][1]})
            current = []
            used = 0.0
            available = other_available
        current.append((cells, row_running))
        used += height
    if current or not pages:
        pages.append({"rows": current, "closing": (current[-1][1] if current else opening)})

    story = []
    for page_index, page in enumerate(pages):
        is_first = page_index == 0
        is_last = page_index == len(pages) - 1
        carried = page["closing"]
        if is_first:
            story.extend(first_header)
        else:
            story.extend(continuation_header)

        table_data = [_header_row()]
        opening_index = None
        if not is_first:
            opening_index = len(table_data)
            page_opening = pages[page_index - 1]["closing"]
            table_data.append([opening_paragraph(page_opening)] + [""] * (len(HEADERS) - 1))
        for cells, _row_running in page["rows"]:
            table_data.append(cells)

        if is_last:
            closing_text = (f"Final closing balance (total outstanding up to "
                            f"{fmt_date(end_date)}): {inr(closing)}")
        else:
            closing_text = (f"Page closing balance: {inr(carried)} "
                            f"(carried forward to next page)")
        closing_index = len(table_data)
        table_data.append([Paragraph(_esc(closing_text), S_CELL)] + [""] * (len(HEADERS) - 1))

        table = Table(table_data, colWidths=COL_WIDTHS, repeatRows=1)
        table.setStyle(_table_style(len(table_data), opening_index, closing_index))
        story.append(table)
        if not is_last:
            story.append(PageBreak())

    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"{business} - {title}",
        author=business,
        pageCompression=0,
    )
    frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, CONTENT_H, id="main",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, footer_text=footer, **k))
    return buffer.getvalue()
