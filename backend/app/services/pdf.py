"""PDF generation (reportlab): rent receipts and move-out settlements.

Built-in PDF fonts have no ₹ glyph, so amounts are printed as "Rs. 1,50,000".
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5, A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.utils.formatting import inr


def rs(amount: int) -> str:
    return inr(amount, symbol="Rs. ")


def _table(rows: list[list[str]], col_widths) -> Table:
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _styles():
    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=18, spaceAfter=2, textColor=colors.HexColor("#0f172a"))
    sub = ParagraphStyle("s", parent=ss["Normal"], fontSize=9, textColor=colors.HexColor("#64748b"), alignment=1)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=10, leading=14)
    return title, sub, body


def receipt_pdf(*, receipt_number: str, owner_name: str, owner_phone: str | None, tenant_name: str,
                property_name: str, unit_name: str, month_label: str, amount: int, mode: str,
                reference: str | None, paid_on: str, amount_due: int, total_paid: int) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A5, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=f"Rent receipt {receipt_number}")
    title, sub, body = _styles()
    balance = max(0, amount_due - total_paid)
    rows = [
        ["Receipt no.", receipt_number],
        ["Date", paid_on],
        ["Received from", tenant_name],
        ["Property", f"{property_name} – {unit_name}"],
        ["Rent month", month_label],
        ["Amount received", rs(amount)],
        ["Payment mode", mode + (f" (Ref: {reference})" if reference else "")],
        ["Rent for month", rs(amount_due)],
        ["Balance pending", rs(balance) if balance else "Nil – fully paid"],
    ]
    w = doc.width
    story = [
        Paragraph("RENT RECEIPT", title),
        Paragraph(escape(f"Issued by {owner_name}" + (f" · {owner_phone}" if owner_phone else "")), sub),
        Spacer(1, 8 * mm),
        _table(rows, [w * 0.38, w * 0.62]),
        Spacer(1, 10 * mm),
        Paragraph(f"Received with thanks a sum of <b>{rs(amount)}</b> towards rent for {month_label}.", body),
        Spacer(1, 14 * mm),
        Paragraph(f"<b>{escape(owner_name)}</b><br/>(Owner)", body),
        Spacer(1, 6 * mm),
        Paragraph("This is a computer-generated receipt and does not need a signature.", sub),
    ]
    doc.build(story)
    return buf.getvalue()


def settlement_pdf(*, owner_name: str, tenant_name: str, property_name: str, unit_name: str,
                   agreement_start: str, vacate_date: str, deposit: int, pending_rent: int,
                   pending_months: list[tuple[str, int]], deductions: list[tuple[str, int]],
                   refund: int, notes: str | None, generated_on: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title="Deposit settlement")
    title, sub, body = _styles()
    w = doc.width
    info = [
        ["Tenant", tenant_name],
        ["Property", f"{property_name} – {unit_name}"],
        ["Agreement start", agreement_start],
        ["Vacate date", vacate_date],
    ]
    calc = [["Security deposit", rs(deposit)]]
    for label, amt in pending_months:
        calc.append([f"Less: pending rent {label}", f"- {rs(amt)}"])
    if not pending_months:
        calc.append(["Less: pending rent", rs(0)])
    for label, amt in deductions:
        calc.append([f"Less: {label}", f"- {rs(amt)}"])
    calc.append(["Refund to tenant" if refund >= 0 else "Amount payable by tenant", rs(abs(refund))])
    calc_t = _table(calc, [w * 0.65, w * 0.35])
    calc_t.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#0f172a")),
    ]))
    story = [
        Paragraph("DEPOSIT SETTLEMENT", title),
        Paragraph(escape(f"Issued by {owner_name} on {generated_on}"), sub),
        Spacer(1, 8 * mm),
        _table(info, [w * 0.35, w * 0.65]),
        Spacer(1, 8 * mm),
        calc_t,
    ]
    if notes:
        story += [Spacer(1, 6 * mm), Paragraph(f"<b>Notes:</b> {escape(notes)}", body)]
    story += [
        Spacer(1, 20 * mm),
        Table([["Owner signature", "Tenant signature"]], colWidths=[w / 2, w / 2],
              style=[("FONTSIZE", (0, 0), (-1, -1), 10), ("LINEABOVE", (0, 0), (0, 0), 0.5, colors.black),
                     ("LINEABOVE", (1, 0), (1, 0), 0.5, colors.black)]),
    ]
    doc.build(story)
    return buf.getvalue()
