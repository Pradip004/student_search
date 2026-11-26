import io
from django.http import HttpResponse
from openpyxl import Workbook
from docx import Document
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

HEADERS = ["Type", "Name", "Email", "Phone", "Department",
           "Course", "Year", "Designation", "Status"]


def rows(qs):
    return [[p.person_type, p.name, p.email, p.phone, p.department,
             p.course, p.year or "", p.designation, p.status] for p in qs]


def to_excel(qs):
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in rows(qs):
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="results.xlsx"'},
    )


def to_word(qs):
    doc = Document()
    doc.add_heading("Search Results", 1)
    table = doc.add_table(rows=1, cols=len(HEADERS))
    table.style = "Table Grid"
    for i, h in enumerate(HEADERS):
        table.rows[0].cells[i].text = h
    for r in rows(qs):
        cells = table.add_row().cells
        for i, value in enumerate(r):
            cells[i].text = str(value)
    buf = io.BytesIO()
    doc.save(buf)
    return HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="results.docx"'},
    )


def to_pdf(qs):
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=landscape(A4))
    data = [HEADERS] + [[str(v) for v in r] for r in rows(qs)]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    pdf.build([table])
    return HttpResponse(
        buf.getvalue(),
        content_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="results.pdf"'},
    )