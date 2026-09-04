import os
from typing import Optional, Set
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import (
    SimpleDocTemplate, BaseDocTemplate, PageTemplate, Frame,
    Table, TableStyle, Paragraph, Spacer, KeepTogether, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfgen.canvas import Canvas
from epf_engine import natural_sort_key

styles = getSampleStyleSheet()
style_normal = styles["Normal"]
style_title = ParagraphStyle(name='Title', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, alignment=TA_CENTER, spaceAfter=12)
style_subtitle = ParagraphStyle(name='Subtitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=TA_CENTER)
style_header = ParagraphStyle(name='Header', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=TA_CENTER)
style_cell = ParagraphStyle(name='Cell', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=TA_CENTER)
style_cell_left = ParagraphStyle(name='CellLeft', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=TA_LEFT)
style_cell_right = ParagraphStyle(name='CellRight', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=TA_RIGHT)
style_cell_bold = ParagraphStyle(name='CellBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, alignment=TA_CENTER)
style_small = ParagraphStyle(name='Small', parent=styles['Normal'], fontName='Helvetica', fontSize=7, alignment=TA_CENTER)
style_amount = ParagraphStyle(name='Amount', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_RIGHT)
style_amount_bold = ParagraphStyle(name='AmountBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=TA_RIGHT)

# Employee Wage History -- Wages/EE/ER/EPS/Total row hierarchy (same Helvetica family and
# size scale as the styles above; grey text is the one genuinely new ingredient, needed to
# mute the EE/ER/EPS rows relative to the dominant Wages row).
style_wyh_label_wages = ParagraphStyle(name='WYHLabelWages', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=TA_LEFT)
style_wyh_val_wages = ParagraphStyle(name='WYHValWages', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=TA_RIGHT)
style_wyh_label_contrib = ParagraphStyle(name='WYHLabelContrib', parent=styles['Normal'], fontName='Helvetica', fontSize=8, textColor=colors.grey, alignment=TA_LEFT)
style_wyh_val_contrib = ParagraphStyle(name='WYHValContrib', parent=styles['Normal'], fontName='Helvetica', fontSize=8, textColor=colors.grey, alignment=TA_RIGHT)
style_wyh_label_total = ParagraphStyle(name='WYHLabelTotal', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=TA_LEFT)
style_wyh_val_total = ParagraphStyle(name='WYHValTotal', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=TA_RIGHT)
style_wyh_footnote = ParagraphStyle(name='WYHFootnote', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=7, textColor=colors.grey, alignment=TA_LEFT)

WYH_DIVIDER_COLOR = colors.HexColor('#CCCCCC')  # light gray -- matches the on-screen divider's intent, kept print-visible on white paper

def _build_pdf_doc(filename, orientation="portrait"):
    pagesize = landscape(A4) if orientation == "landscape" else A4
    doc = SimpleDocTemplate(
        filename,
        pagesize=pagesize,
        rightMargin=0.3*inch,
        leftMargin=0.3*inch,
        topMargin=0.3*inch,
        bottomMargin=0.3*inch
    )
    return doc

def _default_table_style():
    return TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ])

# --------------------------------------------------------------------------
# Form 9
# --------------------------------------------------------------------------
def generate_form_9_pdf(project, filepath: str, member_ids: Optional[Set[str]] = None):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    story.append(Paragraph("FORM 9 (REVISED)", style_title))
    story.append(Paragraph("THE EMPLOYEES' PROVIDENT FUND SCHEME, 1952 (PARA 36(1))", style_header))
    story.append(Paragraph("AND THE EMPLOYEES' PENSION SCHEME, 1995 (PARA 20) (PARA 16(1))", style_header))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<i>Return of employees who are entitled and required to become members of the Employees' Provident Fund and Pension Fund</i>", style_header))
    story.append(Spacer(1, 12))
    
    story.append(Paragraph(f"<b>Name & Address of the Factory/ Establishment :- </b> {project.name}, {project.address}", style_header))
    story.append(Paragraph(f"<b>Code No. of the Factory/ Establishment :- </b> {project.code or ''}", style_header))
    
    coverage = project.coverage_date if project.coverage_date else "______________________"
    story.append(Paragraph(f"<b>Date of Coverage :- </b> {coverage}", style_normal))
    story.append(Paragraph("<b>Industry in which the Factory/ Establishment is engaged :- </b> ______________________", style_normal))
    story.append(Paragraph("<b>If covered under the E.S.I. Act, E.S.I. Code No. :- </b> ______________________", style_normal))
    story.append(Spacer(1, 12))
    
    headers = [
        "Sr. No", "Member ID", "UAN", "Name of Employee\n(in block capital)",
        "Father's Name (or Husband's\nName in case of married women)",
        "Date of\nBirth", "Sex", "Date of Eligibility\nfor Membership",
        "Total Period of Previous Service\n(excluding period of break) as on\ndate of joining the fund",
        "Machine/ Folio No. of\nLedger Card Opened", "Initials of S.S.",
        "Date and Reason of\nLeaving Service",
        "D.C./S.S./A.A.O./A.C. Remarks\nand Initial on Settlement"
    ]
    
    header_row = [Paragraph(h.replace('\n', '<br/>'), style_cell_bold) for h in headers]
    data = [header_row]
    
    # Form 9 lists employees Member ID-wise (not master_list()'s default SL No. order --
    # other forms keep that convention, this is scoped to Form 9 only per user request).
    employees = sorted(project.master_list(), key=lambda e: natural_sort_key(e.member_id))
    if member_ids is not None:
        employees = [e for e in employees if e.member_id in member_ids]
    for i, emp in enumerate(employees, start=1):
        leaving = ", ".join(x for x in (emp.doe, emp.reason_leaving) if x)
        row = [
            Paragraph(str(i), style_cell),
            Paragraph(emp.member_id or "", style_cell_left),
            Paragraph(emp.uan or "", style_cell_left),
            Paragraph(emp.name or "", style_cell_left),
            Paragraph(emp.father_name or "", style_cell_left),
            Paragraph(emp.dob or "", style_cell),
            Paragraph(emp.sex or "", style_cell),
            Paragraph(emp.doj or "", style_cell),
            Paragraph("", style_cell),
            Paragraph("", style_cell),
            Paragraph("", style_cell),
            Paragraph(leaving, style_cell_left),
            Paragraph("", style_cell)
        ]
        data.append(row)
        
    if not employees:
        for i in range(1, 11):
            data.append([Paragraph(str(i), style_cell)] + [Paragraph("", style_cell)] * 12)
            
    available_width = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
    weights = [0.04, 0.08, 0.10, 0.13, 0.13, 0.08, 0.05, 0.08, 0.06, 0.06, 0.04, 0.08, 0.07]
    col_widths = [w * available_width for w in weights]
    
    table = Table(data, colWidths=col_widths, repeatRows=1)
    tstyle = _default_table_style()
    tstyle.add('VALIGN', (0,0), (-1,-1), 'TOP')
    tstyle.add('BACKGROUND', (0,0), (-1,0), colors.lightgrey)
    table.setStyle(tstyle)
    story.append(table)
    
    story.append(Spacer(1, 24))
    story.append(Paragraph("Signature of the Employer or other Authorised Officer of the Factory/Establishment", style_header))
    
    doc.build(story)
    return filepath

# --------------------------------------------------------------------------
# Monthly Wage Entry -- one-month snapshot, mirrors the on-screen bulk-entry grid
# --------------------------------------------------------------------------
MWE_ACCENT = colors.HexColor('#1F3A5F')
MWE_ZEBRA = colors.HexColor('#F4F6F9')

style_mwe_title = ParagraphStyle(name='MWETitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=15, alignment=TA_CENTER, textColor=MWE_ACCENT, spaceAfter=2)
style_mwe_subtitle = ParagraphStyle(name='MWESubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=10)
style_mwe_meta = ParagraphStyle(name='MWEMeta', parent=styles['Normal'], fontName='Helvetica', fontSize=9, alignment=TA_LEFT)
style_mwe_header = ParagraphStyle(name='MWEHeaderCell', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, alignment=TA_CENTER, textColor=colors.white)
style_mwe_cell = ParagraphStyle(name='MWECell', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=TA_CENTER)
style_mwe_cell_left = ParagraphStyle(name='MWECellLeft', parent=styles['Normal'], fontName='Helvetica', fontSize=8, alignment=TA_LEFT)
style_mwe_flag = ParagraphStyle(name='MWEFlag', parent=styles['Normal'], fontName='Helvetica', fontSize=7, alignment=TA_LEFT, textColor=colors.HexColor('#555555'))
style_mwe_total_label = ParagraphStyle(name='MWETotalLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=TA_RIGHT)
style_mwe_total_val = ParagraphStyle(name='MWETotalVal', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, alignment=TA_CENTER)
style_mwe_year_big = ParagraphStyle(name='MWEYearBig', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=22, leading=26, alignment=TA_CENTER, textColor=colors.black, spaceAfter=6)


def _mwe_parse_ddmmyyyy(s):
    if not s:
        return None
    parts = str(s).strip().split("-")
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        return (y, m, d)
    except ValueError:
        return None


def generate_monthly_wage_entry_pdf(project, est, employees, filepath: str, month_idx: int,
                                     month_abbr: str, cal_year, cal_month, days_in_month: int):
    """One month's Monthly Wage Entry grid, exactly as shown on-screen, as a standalone
    PDF -- not a statutory form, just an elegant printable/shareable record of what was
    entered. `employees` are epf_engine.Employee objects for this financial year (from
    project.build_employees_for_year); only those with wage data in this month are
    included, same as the on-screen grid's own "has data" convention elsewhere
    (count_ecr_employees_for_month). `est` is the year-scoped Establishment (from
    project.build_establishment_for_year) whose worker_epf_rate/eps_rate/employer_*
    rate properties drive the EE/ER/Pension math via Employee.month_rows() -- the same
    calculation engine every other form (3A/6A/9) already uses, so these figures can
    never drift from the grid's own numbers."""
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []

    story.append(Paragraph("MONTHLY WAGE ENTRY", style_mwe_title))
    story.append(Paragraph(f"{month_abbr} {cal_year or ''} &nbsp;&bull;&nbsp; {est.name}", style_mwe_subtitle))

    meta_bits = [f"<b>Establishment Code:</b> {est.code or '—'}"]
    if est.address:
        meta_bits.append(f"<b>Address:</b> {est.address}")
    meta_bits.append(f"<b>Financial Year:</b> {est.year_from}-{str(est.year_to)[-2:]}")
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(meta_bits), style_mwe_meta))
    story.append(Spacer(1, 10))

    from epf_engine import get_wage_ceilings_for_year
    wage_ceilings = get_wage_ceilings_for_year(est.year_from)

    headers = [
        "Sl\nNo.", "Member ID", "UAN", "Name", "Days\nin Mth", "NCP\nDays", "Work\nDays",
        "Gross\nWages", "EPF\nWages", "EPS\nWages", "EE Share", "ER PF", "Pension", "Notes"
    ]
    header_row = [Paragraph(h.replace('\n', '<br/>'), style_mwe_header) for h in headers]
    data = [header_row]

    totals = {"gross": 0, "epf": 0, "eps": 0, "ee": 0, "erpf": 0, "pension": 0}
    row_count = 0

    for emp in employees:
        gross = emp.gross_wages[month_idx] if month_idx is not None and month_idx < len(emp.gross_wages) else 0
        if not gross:
            continue
        # month_rows() returns (wages, w_epf, w_eps, w_total, e_epf, e_eps, e_total) -- all
        # CONTRIBUTION amounts except index 0. The grid's "EPS Wages" column is a WAGE BASE
        # (what EPS is calculated ON), which month_rows() never returns at all -- mirrored
        # here from wages.js's calcBulkRow(), the only other place this figure is computed.
        mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                               est.employer_epf_rate, est.employer_eps_rate,
                               wage_ceilings=wage_ceilings)
        wages, w_epf, w_eps, w_total, e_epf, e_eps, e_total = mrows[month_idx]

        wage_raw = int(round(float(emp.wages[month_idx]))) if emp.wages[month_idx] else 0
        ceiling = wage_ceilings[month_idx] if wage_ceilings and month_idx < len(wage_ceilings) else 15000
        if est.employer_eps_rate > 0:
            if emp.age_crosses_58:
                eps_wage_base = 0
            elif emp.pohw:
                eps_wage_base = wage_raw
            else:
                eps_wage_base = min(wage_raw, ceiling)
        else:
            eps_wage_base = 0

        ncp = emp.ncp_days[month_idx] if hasattr(emp, 'ncp_days') and month_idx < len(emp.ncp_days) else 0
        work_days = max(0, days_in_month - (ncp or 0))

        flags = []
        if emp.higher_epf_ee: flags.append("Higher EPF (EE)")
        if emp.higher_epf_er: flags.append("Higher EPF (ER)")
        if emp.age_crosses_58: flags.append("Age &gt; 58")
        if emp.pohw: flags.append("PoHW")
        if emp.pohw_additional_1_16: flags.append("+1.16%")
        m = project.master.get(emp.member_id)
        if m:
            doj = _mwe_parse_ddmmyyyy(m.doj)
            doe = _mwe_parse_ddmmyyyy(m.doe)
            if doe and cal_year and doe[:2] == (cal_year, cal_month):
                flags.append("<b>Exited this month</b>")
            elif doj and cal_year and doj[:2] == (cal_year, cal_month):
                flags.append("<b>Joined this month</b>")

        row_count += 1
        data.append([
            Paragraph(str(row_count), style_mwe_cell),
            Paragraph(emp.member_id or "", style_mwe_cell_left),
            Paragraph(emp.uan or "", style_mwe_cell_left),
            Paragraph(emp.name or "", style_mwe_cell_left),
            Paragraph(str(days_in_month), style_mwe_cell),
            Paragraph(str(ncp or 0), style_mwe_cell),
            Paragraph(str(work_days), style_mwe_cell),
            Paragraph(f"{gross:,.0f}", style_mwe_cell),
            Paragraph(f"{wages:,.0f}", style_mwe_cell),
            Paragraph(f"{eps_wage_base:,.0f}", style_mwe_cell),
            Paragraph(f"{w_epf:,.0f}", style_mwe_cell),
            Paragraph(f"{e_epf:,.0f}", style_mwe_cell),
            Paragraph(f"{e_eps:,.0f}", style_mwe_cell),
            Paragraph(", ".join(flags), style_mwe_flag),
        ])
        totals["gross"] += gross; totals["epf"] += wages; totals["eps"] += eps_wage_base
        totals["ee"] += w_epf; totals["erpf"] += e_epf; totals["pension"] += e_eps

    if row_count == 0:
        data.append([Paragraph("No wage data entered for this month.", style_mwe_cell_left)] + [Paragraph("", style_mwe_cell)] * 13)
    else:
        data.append([
            Paragraph("", style_mwe_cell), Paragraph("", style_mwe_cell), Paragraph("", style_mwe_cell),
            Paragraph(f"TOTAL ({row_count} employees)", style_mwe_total_label),
            Paragraph("", style_mwe_cell), Paragraph("", style_mwe_cell), Paragraph("", style_mwe_cell),
            Paragraph(f"{totals['gross']:,.0f}", style_mwe_total_val),
            Paragraph(f"{totals['epf']:,.0f}", style_mwe_total_val),
            Paragraph(f"{totals['eps']:,.0f}", style_mwe_total_val),
            Paragraph(f"{totals['ee']:,.0f}", style_mwe_total_val),
            Paragraph(f"{totals['erpf']:,.0f}", style_mwe_total_val),
            Paragraph(f"{totals['pension']:,.0f}", style_mwe_total_val),
            Paragraph("", style_mwe_cell),
        ])

    available_width = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
    weights = [0.03, 0.09, 0.09, 0.12, 0.04, 0.04, 0.05, 0.07, 0.07, 0.06, 0.06, 0.06, 0.06, 0.16]
    col_widths = [w * available_width for w in weights]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    tstyle = TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D5DBE3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BACKGROUND', (0, 0), (-1, 0), MWE_ACCENT),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, MWE_ZEBRA]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E4E9F0')),
        ('LINEABOVE', (0, -1), (-1, -1), 1, MWE_ACCENT),
    ])
    table.setStyle(tstyle)
    story.append(table)

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        f"Generated from Monthly Wage Entry &mdash; not a statutory form. "
        f"Rates applied: EE {est.worker_epf_rate}% &bull; ER EPF {est.employer_epf_rate}% &bull; ER EPS {est.employer_eps_rate}%.",
        style_mwe_flag
    ))

    doc.build(story)
    return filepath


# --------------------------------------------------------------------------
# Yearly Wage Checklist -- one per-employee block per financial year, mirrors the
# Wage Entry page's whole-year view; used to spot-check that every month's wages/
# contributions were actually entered for every employee.
# --------------------------------------------------------------------------
MWE_YEARLY_ROW_DEFS = [
    ("Gross Wages", "gross"), ("EPF Wages", "epf"), ("EPS Wages", "eps_wage"),
    ("EE Share", "ee_share"), ("EPS Cont.", "eps_cont"), ("ER Share", "er_share"),
]


def generate_yearly_wage_checklist_pdf(project, est, employees, filepath: str):
    """One block per employee (serial-numbered identity line + a 6-row x 12-month table),
    for every employee with at least one wage entry that financial year (same inclusion as
    project.build_employees_for_year -- matches Form 3A/6A's own convention), plus a
    month-wise employee headcount summary and a Grand Total block summing every employee
    month-by-month. Not a statutory form -- a checklist for spotting missing months at a
    glance. `est`/`employees` come from project.build_establishment_for_year(key) /
    project.build_employees_for_year(key). Reuses Employee.month_rows() for EE Share/EPS
    Cont./ER Share -- see generate_monthly_wage_entry_pdf's docstring for why the EPS Wages
    figure (a wage BASE, not a contribution) has to be computed separately, mirroring
    wages.js's calcBulkRow(), since month_rows() never returns it. Establishment code/
    address are drawn as a running header on every page (via onFirstPage/onLaterPages)
    rather than a story Paragraph, since Establishment Code/Address is used both as a
    one-time cover line, and now the requirement is that it repeats per page. From page 2
    onward the header also carries the establishment name (top-left, after the code) and
    the FY label (top-right) -- page 1 already shows both prominently in the title block,
    so repeating them there would be redundant. Page numbering ("Page X of N", bottom-
    right) reuses the proven _wyh_make_numbered_canvas two-pass NumberedCanvas factory."""
    pagesize = landscape(A4)
    est_code = est.code or "-"
    est_address = est.address or ""
    fy_label = f"FY {est.year_from}-{str(est.year_to)[-2:]}"

    def _draw_running_header(canvas, doc_):
        canvas.saveState()
        page_w, page_h = pagesize
        page_num = canvas.getPageNumber()
        canvas.setFont('Helvetica-Bold', 9)
        line1 = f"Establishment Code: {est_code}"
        if page_num >= 2:
            line1 += f"    |    Name: {est.name or '-'}"
        canvas.drawString(doc_.leftMargin, page_h - 16, line1)
        if page_num >= 2:
            canvas.setFont('Helvetica-Bold', 10)
            canvas.drawRightString(page_w - doc_.rightMargin, page_h - 16, fy_label)
        if est_address:
            canvas.setFont('Helvetica', 8)
            canvas.drawString(doc_.leftMargin, page_h - 28, f"Address: {est_address}")
        canvas.setStrokeColor(colors.HexColor('#D5DBE3'))
        canvas.setLineWidth(0.75)
        canvas.line(doc_.leftMargin, page_h - 34, page_w - doc_.rightMargin, page_h - 34)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        filepath, pagesize=pagesize,
        rightMargin=0.3 * inch, leftMargin=0.3 * inch,
        topMargin=0.58 * inch, bottomMargin=0.45 * inch
    )
    story = []

    story.append(Paragraph(fy_label, style_mwe_year_big))
    story.append(Paragraph("YEARLY WAGE CHECKLIST", style_mwe_title))
    story.append(Paragraph(
        f"Financial Year {est.year_from}-{str(est.year_to)[-2:]} &nbsp;&bull;&nbsp; {est.name}",
        style_mwe_subtitle
    ))
    story.append(Spacer(1, 6))

    from epf_engine import get_wage_ceilings_for_year
    wage_ceilings = get_wage_ceilings_for_year(est.year_from)

    available_width = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
    label_w = 0.09 * available_width
    month_w = (available_width - label_w) / 13
    col_widths = [label_w] + [month_w] * 13

    def build_block(rows_by_key):
        header = ([Paragraph("", style_mwe_header)]
                  + [Paragraph(m, style_mwe_header) for m in FORM_3A_MONTHS]
                  + [Paragraph("Total", style_mwe_header)])
        rows = [header]
        for label, key in MWE_YEARLY_ROW_DEFS:
            vals = rows_by_key[key]
            row = [Paragraph(label, style_mwe_cell_left)] + [
                Paragraph(f"{v:,.0f}" if v else "-", style_mwe_cell) for v in vals
            ]
            row.append(Paragraph(f"{sum(vals):,.0f}", style_mwe_cell))
            rows.append(row)
        t = Table(rows, colWidths=col_widths)
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D5DBE3')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BACKGROUND', (0, 0), (-1, 0), MWE_ACCENT),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, MWE_ZEBRA]),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ]))
        return t

    grand = {key: [0.0] * 12 for _, key in MWE_YEARLY_ROW_DEFS}
    monthly_headcount = [0] * 12
    emp_blocks = []

    for emp in employees:
        mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                               est.employer_epf_rate, est.employer_eps_rate,
                               wage_ceilings=wage_ceilings)
        rows_by_key = {key: [] for _, key in MWE_YEARLY_ROW_DEFS}
        for i in range(12):
            wages, w_epf, w_eps, w_total, e_epf, e_eps, e_total = mrows[i]
            gross = emp.gross_wages[i] if i < len(emp.gross_wages) else 0
            wage_raw = emp.wages[i] if i < len(emp.wages) else 0
            ceiling = wage_ceilings[i] if wage_ceilings and i < len(wage_ceilings) else 15000
            if est.employer_eps_rate > 0:
                if emp.age_crosses_58:
                    eps_wage_base = 0
                elif emp.pohw:
                    eps_wage_base = wage_raw
                else:
                    eps_wage_base = min(wage_raw, ceiling)
            else:
                eps_wage_base = 0
            rows_by_key["gross"].append(gross)
            rows_by_key["epf"].append(wages)
            rows_by_key["eps_wage"].append(eps_wage_base)
            rows_by_key["ee_share"].append(w_epf)
            rows_by_key["eps_cont"].append(e_eps)
            rows_by_key["er_share"].append(e_epf)
            if gross:
                monthly_headcount[i] += 1

        emp_blocks.append((emp, rows_by_key))
        for _, key in MWE_YEARLY_ROW_DEFS:
            for i in range(12):
                grand[key][i] += rows_by_key[key][i]

    emp_count = len(emp_blocks)

    if emp_count == 0:
        story.append(Paragraph("No employees on file for this financial year.", style_mwe_cell_left))
    else:
        story.append(Paragraph("EMPLOYEES WITH WAGES ENTERED &mdash; MONTH-WISE", style_mwe_total_label))
        story.append(Spacer(1, 4))
        count_header = ([Paragraph("", style_mwe_header)]
                         + [Paragraph(m, style_mwe_header) for m in FORM_3A_MONTHS]
                         + [Paragraph("Total Employees", style_mwe_header)])
        count_row = [Paragraph("No. of Employees", style_mwe_cell_left)] + [
            Paragraph(str(c) if c else "-", style_mwe_cell) for c in monthly_headcount
        ]
        count_row.append(Paragraph(str(emp_count), style_mwe_cell))
        count_table = Table([count_header, count_row], colWidths=col_widths)
        count_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D5DBE3')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BACKGROUND', (0, 0), (-1, 0), MWE_ACCENT),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ]))
        story.append(count_table)
        story.append(Spacer(1, 16))

        for serial, (emp, rows_by_key) in enumerate(emp_blocks, start=1):
            identity = (
                f"<b>{serial}. {emp.name or ''}</b> &nbsp;|&nbsp; UAN: {emp.uan or '-'} "
                f"&nbsp;|&nbsp; Member ID: {emp.member_id or '-'} "
                f"&nbsp;|&nbsp; DOB: {emp.dob or '-'} &nbsp;|&nbsp; DOJ: {emp.doj or '-'} "
                f"&nbsp;|&nbsp; DOL: {emp.doe or '-'} &nbsp;|&nbsp; Reason: {emp.reason_leaving or '-'}"
            )
            story.append(Paragraph(identity, style_mwe_meta))
            story.append(Spacer(1, 4))
            story.append(build_block(rows_by_key))
            story.append(Spacer(1, 14))

        story.append(Paragraph("GRAND TOTAL &mdash; ALL EMPLOYEES", style_mwe_total_label))
        story.append(Spacer(1, 4))
        story.append(build_block(grand))

    doc.build(
        story, onFirstPage=_draw_running_header, onLaterPages=_draw_running_header,
        canvasmaker=_wyh_make_numbered_canvas("")
    )
    return filepath


# --------------------------------------------------------------------------
# Form 3A
# --------------------------------------------------------------------------
FORM_3A_MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]


def _build_form_3a_employee_block(est, emp, aw):
    """Builds the flowables for ONE employee's Form 3A for ONE financial year (est is already
    scoped to that year via project.build_establishment_for_year). This is the single source
    of the Form 3A layout/formula -- shared by generate_form_3a_pdf (one year, many employees)
    and generate_form_3a_multi_year_pdf (one employee, many years) so neither reimplements it
    a second time. `aw` is the usable page width (doc.pagesize[0] - margins)."""
    block = []

    # Header
    block.append(Paragraph("(For Un-exempted Establishments only)", style_normal))
    block.append(Paragraph("FORM - 3A(R)", style_title))
    block.append(Paragraph("THE EMPLOYEE'S PROVIDENT FUND SCHEME, 1952 (PARA 35 & 43)", style_subtitle))
    block.append(Paragraph("THE EMPLOYEE'S PENSION SCHEME, 1995 (PARAGRAPH 20(4))", style_subtitle))
    block.append(Paragraph(f"<i>Contribution Card for the currency period April, {est.year_from} to March, {est.year_to}</i>", style_header))
    block.append(Spacer(1, 12))

    # Info Table
    member_id_display = emp.member_id or ""
    if emp.uan:
        member_id_display += f"  (UAN: {emp.uan})"

    rate_val = est.statutory_rate_text if est.is_post_1997 else f"{est.statutory_rate}%"

    info_data = [
        [Paragraph("1.", style_cell_left), Paragraph("Member ID", style_cell_left), Paragraph(":", style_cell_left), Paragraph(f"<b>{member_id_display}</b>", style_cell_left)],
        [Paragraph("2.", style_cell_left), Paragraph("Name of the Member", style_cell_left), Paragraph(":", style_cell_left), Paragraph(f"<b>{emp.name or ''}</b>", style_cell_left)],
        [Paragraph("3.", style_cell_left), Paragraph("Father's Name", style_cell_left), Paragraph(":", style_cell_left), Paragraph(emp.father_name or "", style_cell_left)],
        [Paragraph("4.", style_cell_left), Paragraph("Name & Address of the Establishment", style_cell_left), Paragraph(":", style_cell_left), Paragraph(f"{est.name}, {est.address}", style_cell_left)],
        [Paragraph("", style_cell_left), Paragraph("Code No. of the Establishment", style_cell_left), Paragraph(":", style_cell_left), Paragraph(f"<b>{est.code}</b>", style_cell_left)],
        [Paragraph("5.", style_cell_left), Paragraph("Statutory Rate of Contribution", style_cell_left), Paragraph(":", style_cell_left), Paragraph(rate_val, style_cell_left)],
        [Paragraph("", style_cell_left), Paragraph("Voluntary higher rate of employee's contribution, if any", style_cell_left), Paragraph(":", style_cell_left), Paragraph("", style_cell_left)]
    ]
    info_table = Table(info_data, colWidths=[30, 200, 20, 350], hAlign='LEFT')
    info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (0,-1), 0)
    ]))
    block.append(info_table)
    block.append(Spacer(1, 12))

    # 12-Month Table
    w_epf_rate, w_eps_rate = est.worker_epf_rate, est.worker_eps_rate
    e_epf_rate, e_eps_rate = est.employer_epf_rate, est.employer_eps_rate
    eps_label = est.eps_label

    table_data = [
        [
            Paragraph("Month", style_cell_bold),
            Paragraph("Wages", style_cell_bold),
            Paragraph("WORKER'S SHARE", style_cell_bold), "", "",
            Paragraph("EMPLOYER'S SHARE", style_cell_bold), "", "",
            Paragraph("REFUND OF<br/>ADVANCES", style_cell_bold),
            Paragraph("NCP<br/>DAYS", style_cell_bold),
            Paragraph("REMARKS", style_cell_bold)
        ],
        [
            "", "",
            Paragraph(f"EPF {w_epf_rate:g}%", style_cell_bold),
            Paragraph(f"{eps_label} {w_eps_rate:g}%", style_cell_bold),
            Paragraph("TOTAL", style_cell_bold),
            Paragraph(f"EPF {e_epf_rate:g}%", style_cell_bold),
            Paragraph(f"{eps_label} {e_eps_rate:g}%", style_cell_bold),
            Paragraph("TOTAL", style_cell_bold),
            "", "", ""
        ]
    ]

    month_rows = emp.month_rows(w_epf_rate, w_eps_rate, e_epf_rate, e_eps_rate)
    for i, m in enumerate(FORM_3A_MONTHS):
        wages, w_epf, w_eps, w_total, e_epf, e_eps, e_total = month_rows[i]
        table_data.append([
            Paragraph(m, style_cell),
            Paragraph(str(int(round(wages))) if wages else "", style_cell_right),
            Paragraph(str(int(round(w_epf))) if w_epf else "", style_cell_right),
            Paragraph(str(int(round(w_eps))) if w_eps else "", style_cell_right),
            Paragraph(str(int(round(w_total))) if w_total else "", style_cell_right),
            Paragraph(str(int(round(e_epf))) if e_epf else "", style_cell_right),
            Paragraph(str(int(round(e_eps))) if e_eps else "", style_cell_right),
            Paragraph(str(int(round(e_total))) if e_total else "", style_cell_right),
            Paragraph("", style_cell), Paragraph("", style_cell), Paragraph("", style_cell)
        ])

    wt, w_epf_t, w_eps_t, w_tot_t, e_epf_t, e_eps_t, e_tot_t = emp.annual_totals(
        w_epf_rate, w_eps_rate, e_epf_rate, e_eps_rate)

    table_data.append([
        Paragraph("Total", style_cell_bold),
        Paragraph(str(int(round(wt))) if wt else "", style_cell_right),
        Paragraph(str(int(round(w_epf_t))) if w_epf_t else "", style_cell_right),
        Paragraph(str(int(round(w_eps_t))) if w_eps_t else "", style_cell_right),
        Paragraph(str(int(round(w_tot_t))) if w_tot_t else "", style_cell_right),
        Paragraph(str(int(round(e_epf_t))) if e_epf_t else "", style_cell_right),
        Paragraph(str(int(round(e_eps_t))) if e_eps_t else "", style_cell_right),
        Paragraph(str(int(round(e_tot_t))) if e_tot_t else "", style_cell_right),
        Paragraph("", style_cell), Paragraph("", style_cell), Paragraph("", style_cell)
    ])

    t_weights = [0.1, 0.1, 0.09, 0.09, 0.09, 0.09, 0.09, 0.09, 0.08, 0.08, 0.1]
    t_col_widths = [w * aw for w in t_weights]

    table = Table(table_data, colWidths=t_col_widths)
    tstyle = _default_table_style()
    tstyle.add('SPAN', (0,0), (0,1))
    tstyle.add('SPAN', (1,0), (1,1))
    tstyle.add('SPAN', (2,0), (4,0))
    tstyle.add('SPAN', (5,0), (7,0))
    tstyle.add('SPAN', (8,0), (8,1))
    tstyle.add('SPAN', (9,0), (9,1))
    tstyle.add('SPAN', (10,0), (10,1))
    tstyle.add('BACKGROUND', (0,0), (-1,1), colors.lightgrey)
    table.setStyle(tstyle)
    block.append(table)

    block.append(Spacer(1, 12))

    # Footer
    cert1 = "Certified that the total amount of contribution indicated in this card has already been remitted in full in EPF A/c. No. 1 and A/c No. 10 vide note below."
    block.append(Paragraph(cert1, style_cell_left))

    block.append(Spacer(1, 6))
    block.append(Paragraph(f"(a) Date of leaving Service: {emp.doe or ''}                                (b) Reason for leaving service: {emp.reason_leaving or ''}", style_cell_left))
    block.append(Spacer(1, 6))

    cert2 = "Certified that the difference between the total of the contributions shown under Cols. 3 & 4 of the above table and that arrived at on the total wages shown in Col. 2 at the prescribed rate is solely due to the rounding off of contribution to the nearest rupee under the rules."
    block.append(Paragraph(cert2, style_cell_left))
    block.append(Spacer(1, 24))

    sig_data = [
        [Paragraph("Date:", style_cell_left), Paragraph("Signature of the Employer with seal", style_cell_right)]
    ]
    sig_table = Table(sig_data, colWidths=[aw/2, aw/2])
    block.append(sig_table)

    return block


def generate_form_3a_pdf(project, year_key: str, filepath: str, member_ids: Optional[Set[str]] = None):
    doc = _build_pdf_doc(filepath, orientation="portrait")
    story = []

    est = project.build_establishment_for_year(year_key)
    employees = project.build_employees_for_year(year_key)
    employees = [emp for emp in employees if sum(w or 0 for w in (emp.wages or [])) > 0]
    if member_ids is not None:
        employees = [emp for emp in employees if emp.member_id in member_ids]

    if not employees:
        story.append(Paragraph("No employees with wages found for this currency period.", style_title))
        doc.build(story)
        return filepath

    aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin

    for emp_idx, emp in enumerate(employees):
        block = _build_form_3a_employee_block(est, emp, aw)
        story.append(KeepTogether(block))
        if emp_idx < len(employees) - 1:
            story.append(PageBreak())

    doc.build(story)
    return filepath


def generate_form_3a_multi_year_pdf(project, year_keys, member_id: str, filepath: str) -> dict:
    """One employee, multiple financial years, combined into a single PDF -- one Form 3A
    page-block per requested year, in the given order, built with the exact same
    _build_form_3a_employee_block() used by the single-year generator above. Years where this
    employee has no wage data (not yet joined, already left, or the year doesn't exist at all)
    are skipped rather than producing a blank/erroring page; the caller gets back which years
    actually made it into the PDF and which were skipped and why, so nothing goes missing
    silently."""
    doc = _build_pdf_doc(filepath, orientation="portrait")
    story = []
    aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin

    generated_years = []
    skipped_years = []

    for year_key in year_keys:
        if year_key not in project.years:
            skipped_years.append({"year": year_key, "reason": "Financial year not found"})
            continue

        est = project.build_establishment_for_year(year_key)
        employees = project.build_employees_for_year(year_key)
        emp = next((e for e in employees if e.member_id == member_id), None)
        if not emp:
            skipped_years.append({"year": year_key, "reason": "Employee not on record for this year"})
            continue

        total_w = sum(w or 0 for w in (emp.wages or []))
        if total_w <= 0:
            skipped_years.append({"year": year_key, "reason": "No wage data for this employee in this year"})
            continue

        if generated_years:
            story.append(PageBreak())
        story.append(KeepTogether(_build_form_3a_employee_block(est, emp, aw)))
        generated_years.append(year_key)

    if not generated_years:
        return {"generated_years": [], "skipped_years": skipped_years, "path": None}

    doc.build(story)
    return {"generated_years": generated_years, "skipped_years": skipped_years, "path": filepath}

# --------------------------------------------------------------------------
# Form 6A
# --------------------------------------------------------------------------
def generate_form_6a_pdf(project, year_key: str, filepath: str, member_ids: Optional[Set[str]] = None):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []

    est = project.build_establishment_for_year(year_key)
    employees = project.build_employees_for_year(year_key)
    employees = [emp for emp in employees if sum(w or 0 for w in (emp.wages or [])) > 0]
    if member_ids is not None:
        employees = [emp for emp in employees if emp.member_id in member_ids]
    
    story.append(Paragraph("FORM 6 A", style_title))
    story.append(Paragraph("THE EMPLOYEE'S PROVIDENT FUND, 1952 (PARAGRAPH 43)", style_subtitle))
    story.append(Paragraph("THE EMPLOYEE'S PENSION SCHEME, 1995 (PARAGRAPH 20(4))", style_subtitle))
    story.append(Paragraph(f"<i>Annual Statement of Contribution for the currency period from 1st April {est.year_from} to 31st March {est.year_to}</i>", style_header))
    story.append(Spacer(1, 12))
    
    story.append(Paragraph(f"<b>Name & Address of the Establishment :- </b> {est.name}, {est.address}", style_header))
    story.append(Paragraph(f"<b>Code No. of the Establishment :- </b> {est.code}", style_header))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<i>Statutory Rate of Contribution : {est.statutory_rate_text}</i>", style_header))
    story.append(Spacer(1, 12))
    
    headers_row1 = [
        "SL.NO", "MEMBER ID", "NAME OF EMPLOYEES", "WAGES BASIC Rs.",
        "WORKER'S CONTRIBUTION", "", "TOTAL",
        "EMPLOYER'S CONTRIBUTION", "", "TOTAL", "REMARKS"
    ]
    headers_row2 = [
        "", "", "", "",
        f"EPF CONTRIBUTION @ {est.worker_epf_rate:g}% Rs.",
        f"{est.eps_label} CONTRIBUTION @{est.worker_eps_rate:g}% Rs.",
        "",
        f"EPF CONTRIBUTION @ {est.employer_epf_rate:g}% Rs.",
        f"{est.eps_label} CONTRIBUTION @{est.employer_eps_rate:g}% Rs.",
        "", ""
    ]
    headers_row3 = [str(i) for i in range(1, 12)]
    
    hr1 = [Paragraph(h, style_cell_bold) for h in headers_row1]
    hr2 = [Paragraph(h, style_cell_bold) for h in headers_row2]
    hr3 = [Paragraph(h, style_cell_bold) for h in headers_row3]
    
    data = [hr1, hr2, hr3]
    grand = [0, 0, 0, 0, 0, 0, 0]
    
    for sl, emp in enumerate(employees, start=1):
        member_id_display = emp.member_id or ""
        if emp.uan:
            member_id_display += f"  (UAN: {emp.uan})"
        
        wt, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot = emp.annual_totals(
            est.worker_epf_rate, est.worker_eps_rate, est.employer_epf_rate, est.employer_eps_rate)
            
        row_vals = [int(round(wt)), int(round(w_epf)), int(round(w_eps)), int(round(w_tot)),
                    int(round(e_epf)), int(round(e_eps)), int(round(e_tot))]
        for i, val in enumerate(row_vals):
            grand[i] += val
            
        data.append([
            Paragraph(str(sl), style_cell),
            Paragraph(member_id_display, style_cell_left),
            Paragraph(emp.name or "", style_cell_left),
            Paragraph(str(row_vals[0]) if row_vals[0] else "", style_cell_right),
            Paragraph(str(row_vals[1]) if row_vals[1] else "", style_cell_right),
            Paragraph(str(row_vals[2]) if row_vals[2] else "", style_cell_right),
            Paragraph(str(row_vals[3]) if row_vals[3] else "", style_cell_right),
            Paragraph(str(row_vals[4]) if row_vals[4] else "", style_cell_right),
            Paragraph(str(row_vals[5]) if row_vals[5] else "", style_cell_right),
            Paragraph(str(row_vals[6]) if row_vals[6] else "", style_cell_right),
            Paragraph("", style_cell)
        ])
        
    data.append([
        Paragraph("<b>GRAND TOTAL</b>", style_cell_bold), "", "",
        Paragraph(f"<b>{int(round(grand[0]))}</b>", style_cell_right),
        Paragraph(f"<b>{int(round(grand[1]))}</b>", style_cell_right),
        Paragraph(f"<b>{int(round(grand[2]))}</b>", style_cell_right),
        Paragraph(f"<b>{int(round(grand[3]))}</b>", style_cell_right),
        Paragraph(f"<b>{int(round(grand[4]))}</b>", style_cell_right),
        Paragraph(f"<b>{int(round(grand[5]))}</b>", style_cell_right),
        Paragraph(f"<b>{int(round(grand[6]))}</b>", style_cell_right),
        Paragraph("", style_cell)
    ])
    
    aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
    weights = [0.04, 0.12, 0.16, 0.08, 0.09, 0.09, 0.08, 0.09, 0.09, 0.08, 0.08]
    col_widths = [w * aw for w in weights]
    
    table = Table(data, colWidths=col_widths, repeatRows=3)
    tstyle = _default_table_style()
    tstyle.add('SPAN', (0,0), (0,1))
    tstyle.add('SPAN', (1,0), (1,1))
    tstyle.add('SPAN', (2,0), (2,1))
    tstyle.add('SPAN', (3,0), (3,1))
    tstyle.add('SPAN', (4,0), (5,0))
    tstyle.add('SPAN', (6,0), (6,1))
    tstyle.add('SPAN', (7,0), (8,0))
    tstyle.add('SPAN', (9,0), (9,1))
    tstyle.add('SPAN', (10,0), (10,1))
    tstyle.add('SPAN', (0,-1), (2,-1))
    tstyle.add('BACKGROUND', (0,0), (-1,2), colors.lightgrey)
    table.setStyle(tstyle)
    story.append(table)
    
    story.append(Spacer(1, 24))
    
    doc.build(story)
    return filepath

# --------------------------------------------------------------------------
# Form 12A
# --------------------------------------------------------------------------
def generate_form_12a_pdf(project, year_key: str, filepath: str, member_ids: Optional[Set[str]] = None):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []

    est = project.build_establishment_for_year(year_key)
    employees = project.build_employees_for_year(year_key)
    if member_ids is not None:
        employees = [emp for emp in employees if emp.member_id in member_ids]
    yr_record = project.years.get(year_key)
    all_remittances = yr_record.remittances if yr_record and hasattr(yr_record, 'remittances') else []
    
    story.append(Paragraph("FORM 12 A", style_title))
    story.append(Paragraph("THE EMPLOYEES' PROVIDENT FUND SCHEME, 1952 (PARAGRAPH 38)", style_subtitle))
    story.append(Paragraph(f"<i>Statement of Contribution for the currency period from 1st April {est.year_from} to 31st March {est.year_to}</i>", style_header))
    story.append(Spacer(1, 12))
    
    story.append(Paragraph(f"<b>Name & Address of the Establishment :- </b> {est.name}, {est.address}", style_title))
    story.append(Paragraph(f"<b>Code No. of the Establishment :- </b> {est.code}", style_title))
    story.append(Spacer(1, 12))
    
    headers = [
        "Wages Month", "TRRN", "CRRN", "Members", "A/c No.1\n(EE+ER) Rs.",
        "A/c No.2\n(Admin Chgs.) Rs.", "A/c No.10\n(Pension Fund) Rs.", "A/c No.21\n(EDLI) Rs.",
        "A/c No.22\n(EDLI Admin) Rs.", "Total\nRs.", "Credit Date"
    ]
    
    data = [[Paragraph(h.replace('\n', '<br/>'), style_cell_bold) for h in headers]]
    
    from epf_engine import calendar_year_for_month, get_month_num, account2_rate_percent, account22_rate_percent, ACCOUNT_21_RATE, ACCOUNT_22_MIN, ACCOUNT_2_MIN, MONTHS
    
    all_month_rows = [emp.month_rows(est.worker_epf_rate, est.worker_eps_rate, est.employer_epf_rate, est.employer_eps_rate) for emp in employees]
    
    grand = [0] * 7 # members (summed? no), a1, a2, a10, a21, a22, total
    
    for i, month_label in enumerate(MONTHS):
        cal_year = calendar_year_for_month(month_label, est.year_from, est.year_to)
        a2_rate = account2_rate_percent(cal_year, get_month_num(month_label))
        a22_rate = account22_rate_percent(cal_year, get_month_num(month_label))
        
        month_remittances = [r for r in all_remittances if r.get("month_label") == month_label]
        
        if not month_remittances:
            wages_total = sum(rows[i][0] for rows in all_month_rows)
            ee_total = sum(rows[i][1] for rows in all_month_rows)
            er_total = sum(rows[i][4] for rows in all_month_rows)
            a10_total = sum(rows[i][5] for rows in all_month_rows)
            
            a2_amt = max(round(wages_total * a2_rate / 100), ACCOUNT_2_MIN) if wages_total > 0 else 0
            a21_amt = round(wages_total * ACCOUNT_21_RATE / 100)
            a22_amt = (max(round(wages_total * a22_rate / 100), ACCOUNT_22_MIN) if (a22_rate > 0 and wages_total > 0) else 0)
            
            members = sum(1 for rows in all_month_rows if rows[i][0] > 0)
            acc_01 = ee_total + er_total
            
            month_remittances.append({
                "trrn": "-", "crrn": "-", "members": members, "acc_01": acc_01, "acc_02": a2_amt,
                "acc_10": a10_total, "acc_21": a21_amt, "acc_22": a22_amt, "credit_date": "-"
            })
            
        for idx, r in enumerate(month_remittances):
            trrn = r.get("trrn") or "-"
            crrn = r.get("crrn") or "-"
            members = int(r.get("members", 0))
            a1 = int(r.get("acc_01", 0))
            a2 = int(r.get("acc_02", 0))
            a10 = int(r.get("acc_10", 0))
            a21 = int(r.get("acc_21", 0))
            a22 = int(r.get("acc_22", 0))
            cdate = r.get("credit_date") or "-"
            
            tot = a1 + a2 + a10 + a21 + a22
            
            grand[0] += members; grand[1] += a1; grand[2] += a2; grand[3] += a10; grand[4] += a21; grand[5] += a22; grand[6] += tot
            
            
            if idx == 0:
                parts = month_label.split(" Paid in ")
                if len(parts) == 2:
                    wage_month = parts[0]
                    paid_month = parts[1]
                    wage_yr = calendar_year_for_month(wage_month, est.year_from, est.year_to)
                    paid_yr = calendar_year_for_month(paid_month, est.year_from, est.year_to)
                    display_month = f"{wage_month} {wage_yr} Paid in {paid_month} {paid_yr}"
                else:
                    display_month = month_label
            else:
                display_month = ""
            
            data.append([
                Paragraph(display_month, style_cell),
                Paragraph(str(trrn), style_cell),
                Paragraph(str(crrn), style_cell),
                Paragraph(str(members), style_amount),
                Paragraph(str(a1), style_amount),
                Paragraph(str(a2), style_amount),
                Paragraph(str(a10), style_amount),
                Paragraph(str(a21), style_amount),
                Paragraph(str(a22), style_amount),
                Paragraph(str(tot), style_amount),
                Paragraph(str(cdate), style_cell)
            ])
            
    data.append([
        Paragraph("<b>GRAND TOTAL</b>", style_cell_bold), "", "",
        Paragraph(f"<b>{grand[0]}</b>", style_amount_bold),
        Paragraph(f"<b>{grand[1]}</b>", style_amount_bold),
        Paragraph(f"<b>{grand[2]}</b>", style_amount_bold),
        Paragraph(f"<b>{grand[3]}</b>", style_amount_bold),
        Paragraph(f"<b>{grand[4]}</b>", style_amount_bold),
        Paragraph(f"<b>{grand[5]}</b>", style_amount_bold),
        Paragraph(f"<b>{grand[6]}</b>", style_amount_bold),
        ""
    ])
    
    aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
    weights = [0.12, 0.09, 0.09, 0.06, 0.10, 0.10, 0.10, 0.08, 0.08, 0.09, 0.09]
    col_widths = [w * aw for w in weights]
    
    table = Table(data, colWidths=col_widths, repeatRows=1)
    tstyle = _default_table_style()
    tstyle.add('BOTTOMPADDING', (0, 0), (-1, -1), 2)
    tstyle.add('TOPPADDING', (0, 0), (-1, -1), 2)
    tstyle.add('SPAN', (0,-1), (2,-1))
    tstyle.add('BACKGROUND', (0,0), (-1,0), colors.lightgrey)
    table.setStyle(tstyle)
    story.append(table)
    
    doc.build(story)
    return filepath

# --------------------------------------------------------------------------
# Form 5
# --------------------------------------------------------------------------
def generate_form_5_pdf(project, filepath: str, member_ids: Optional[Set[str]] = None):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    from epf_engine import employees_joined_in_month, calendar_year_for_month, get_month_num, MONTHS
    
    from datetime import datetime
    MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    
    curr_yr = project.current_year() if (hasattr(project, 'current_year') and project.current_year()) else None
    est_obj = getattr(project, 'est', None)
    est_from = est_obj.year_from if est_obj else (curr_yr.year_from if curr_yr else 0)
    est_to = est_obj.year_to if est_obj else (curr_yr.year_to if curr_yr else 0)

    forms_generated = 0
    for month_abbr in MONTHS:
        cal_year = calendar_year_for_month(month_abbr, est_from, est_to)
        cal_month = get_month_num(month_abbr)
        if cal_year is None: continue
        
        matches = employees_joined_in_month(project, cal_year, cal_month, member_ids=member_ids)
        if not matches: continue
        
        forms_generated += 1
        block = []
        month_label = f"{MONTH_NAMES[cal_month - 1]}, {cal_year}"
        
        block.append(Paragraph("FORM 5", style_title))
        block.append(Paragraph("THE EMPLOYEES' PROVIDENT FUND SCHEME, 1952 (PARAGRAPH 36 (2) (a) AND (b))", style_subtitle))
        block.append(Paragraph("EMPLOYEES' PENSION SCHEME, 1995 (PARAGRAPH 20 (4))", style_subtitle))
        block.append(Spacer(1, 6))
        block.append(Paragraph(f"<i>Return of Employees' qualifying for membership of the Employees' Provident Fund, Employees' Pension Scheme & Employees' Deposit Linked Insurance Fund for the first time during the month of: {month_label}</i>", style_header))
        block.append(Paragraph("To be sent to the Commissioner with Form 2", style_header))
        block.append(Spacer(1, 12))
        
        block.append(Paragraph(f"<b>Name & Address of the Factory/ Establishment :- </b> {project.name}, {project.address}", style_header))
        block.append(Spacer(1, 12))
        
        headers = [
            "S No", "Member ID", "UAN", "Name of the Member",
            "Father's Name or Husband's\nName in case of married women",
            "Age/ Date of\nBirth", "Sex", "Date of Eligibility\nfor Service",
            "Total Period of Previous Service\n(excluding period of breaks) as on\nthe date of joining the fund", "Remarks"
        ]
        
        data = [[Paragraph(h.replace('\n', '<br/>'), style_cell_bold) for h in headers]]
        
        for i, m in enumerate(matches, start=1):
            data.append([
                Paragraph(str(i), style_cell),
                Paragraph(m.member_id or "", style_cell_left),
                Paragraph(m.uan or "", style_cell_left),
                Paragraph(m.name or "", style_cell_left),
                Paragraph(m.father_name or "", style_cell_left),
                Paragraph(m.dob or "", style_cell),
                Paragraph(m.sex or "", style_cell),
                Paragraph(m.doj or "", style_cell),
                Paragraph("", style_cell),
                Paragraph("", style_cell)
            ])
            
        aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
        weights = [0.04, 0.1, 0.1, 0.14, 0.16, 0.08, 0.06, 0.1, 0.12, 0.1]
        col_widths = [w * aw for w in weights]
        
        table = Table(data, colWidths=col_widths, repeatRows=1)
        tstyle = _default_table_style()
        tstyle.add('BACKGROUND', (0,0), (-1,0), colors.lightgrey)
        table.setStyle(tstyle)
        block.append(table)
        block.append(Spacer(1, 24))
        
        notes = "Note: Please furnish details of the membership in remarks column if the employee was a member of Employees' Provident Fund and Employees' Family Pension scheme before joining yourself/ factory. i.e. Member ID and/ or the name and particulars of the last employer."
        block.append(Paragraph(notes, style_cell_left))
        
        story.append(KeepTogether(block))
        story.append(PageBreak())
        
    if forms_generated == 0:
        story.append(Paragraph("No employees joined in this period.", style_title))
        
    doc.build(story)
    return filepath

# --------------------------------------------------------------------------
# Form 10
# --------------------------------------------------------------------------
def generate_form_10_pdf(project, filepath: str, member_ids: Optional[Set[str]] = None):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    from epf_engine import employees_left_in_month, calendar_year_for_month, get_month_num, MONTHS
    
    from datetime import datetime
    MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    
    curr_yr = project.current_year() if (hasattr(project, 'current_year') and project.current_year()) else None
    est_obj = getattr(project, 'est', None)
    est_from = est_obj.year_from if est_obj else (curr_yr.year_from if curr_yr else 0)
    est_to = est_obj.year_to if est_obj else (curr_yr.year_to if curr_yr else 0)

    forms_generated = 0
    for month_abbr in MONTHS:
        cal_year = calendar_year_for_month(month_abbr, est_from, est_to)
        cal_month = get_month_num(month_abbr)
        if cal_year is None: continue
        
        matches = employees_left_in_month(project, cal_year, cal_month, member_ids=member_ids)
        if not matches: continue
        
        forms_generated += 1
        block = []
        month_label = f"{MONTH_NAMES[cal_month - 1]}, {cal_year}"
        
        block.append(Paragraph("FORM 10", style_title))
        block.append(Paragraph("THE EMPLOYEES' PROVIDENT FUND SCHEME, 1952 (PARAGRAPH 36 (2) (a) AND (b))", style_subtitle))
        block.append(Paragraph("EMPLOYEES' PENSION SCHEME, 1995 (PARAGRAPH 20 (4))", style_subtitle))
        block.append(Spacer(1, 6))
        block.append(Paragraph(f"<i>Return of Members leaving service during the month of: {month_label}</i>", style_header))
        block.append(Spacer(1, 12))
        
        block.append(Paragraph(f"<b>Name & Address of the Factory/ Establishment :- </b> {project.name}, {project.address}", style_header))
        block.append(Spacer(1, 12))
        
        headers = [
            "S No", "Member ID", "UAN", "Name of the Member",
            "Father's Name or Husband's\nName in case of married",
            "Date of Leaving\nService", "Reason for\nLeaving Service", "Remarks"
        ]
        
        data = [[Paragraph(h.replace('\n', '<br/>'), style_cell_bold) for h in headers]]
        
        for i, m in enumerate(matches, start=1):
            data.append([
                Paragraph(str(i), style_cell),
                Paragraph(m.member_id or "", style_cell_left),
                Paragraph(m.uan or "", style_cell_left),
                Paragraph(m.name or "", style_cell_left),
                Paragraph(m.father_name or "", style_cell_left),
                Paragraph(m.doe or "", style_cell),
                Paragraph(m.reason_leaving or "", style_cell),
                Paragraph("", style_cell)
            ])
            
        aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
        weights = [0.05, 0.12, 0.12, 0.16, 0.2, 0.1, 0.15, 0.1]
        col_widths = [w * aw for w in weights]
        
        table = Table(data, colWidths=col_widths, repeatRows=1)
        tstyle = _default_table_style()
        tstyle.add('BACKGROUND', (0,0), (-1,0), colors.lightgrey)
        table.setStyle(tstyle)
        block.append(table)
        block.append(Spacer(1, 24))
        
        notes = [
            "Please state whether the member is (a) retiring according to para 69 (1) (a) or (b) of the scheme; (b) leaving India for permanent settlement abroad; (c) retrenched; (d) ordinarily dismissed for serious and willful misconduct; (e) discharged; (f) resigning from or leaving service; (g) taking up employment elsewhere (the name and address of the new employer should be stated); (h) dead.",
            "(1) A request for deduction from the account of a member dismissed for serious and willful misconduct should be reported by the following \\\"certified that the member mentioned at Sr. No. ___________ Shri ___________ was dismissed from the service for willful misconduct. I recommend that the employer's contribution for ___________ should be forfeited from his account in the fund. A copy of order of dismissal is enclosed.\\\"",
            "(2) In case of discharge from service, the following certificate should be filled. Certified that the member mentioned in Sr. No ___________ Shri ___________ was paid/ unpaid retrenchment compensation of Rs. ___________ under the Industrial Disputes Act, 1947"
        ]
        for note in notes:
            block.append(Paragraph(note, style_cell_left))
            block.append(Spacer(1, 4))
            
        story.append(KeepTogether(block))
        story.append(PageBreak())
        
    if forms_generated == 0:
        story.append(Paragraph("No employees left in this period.", style_title))

    doc.build(story)
    return filepath

# --------------------------------------------------------------------------
# Employee Wage History -- server-side PDF
#
# Uses BaseDocTemplate + a custom PageTemplate.onPage callback instead of
# SimpleDocTemplate, because the repeating header (establishment/employee
# identity + the MAR..FEB/Total column bar) has to be drawn fresh on every
# page at a fixed position -- Table.repeatRows only repeats header rows
# within a single continuous Table, which would fight the per-year
# KeepTogether blocks below (the actual fix for years splitting across a
# page break). Page numbers use the standard two-pass NumberedCanvas
# technique since ReportLab doesn't know the final page count until the
# whole story has been laid out once.
# --------------------------------------------------------------------------
WYH_MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
WYH_HEADER_HEIGHT = 1.15 * inch  # reserved top-of-page space: title + est/emp lines + month header bar


def _wyh_make_onpage(est_name, est_code, emp_name, uan, member_id, label_w, month_col_widths):
    """Returns an onPage(canvas, doc) callback bound to this employee's header info.
    Draws identically on every page, including page 1 -- there's no separate static
    header competing for that space, so no special-casing is needed."""
    def _on_page(canvas_obj, doc):
        canvas_obj.saveState()
        page_w, page_h = doc.pagesize
        top_y = page_h - doc.topMargin

        canvas_obj.setFont('Helvetica-Bold', 12)
        canvas_obj.drawCentredString(page_w / 2, top_y - 12, "EMPLOYEE WAGE & CONTRIBUTION HISTORY")

        canvas_obj.setFont('Helvetica-Bold', 9)
        canvas_obj.drawString(doc.leftMargin, top_y - 30, f"Establishment: {est_name}   (Code: {est_code})")
        canvas_obj.setFont('Helvetica', 9)
        canvas_obj.drawString(doc.leftMargin, top_y - 44, f"Employee: {emp_name}    UAN: {uan or '-'}    Member ID: {member_id or '-'}")

        # Fixed month-column header bar -- column widths match the per-year Tables
        # below exactly, so it reads as one continuous table across the page break.
        row_h = 16
        bar_top = top_y - 60
        bar_bottom = bar_top - row_h

        canvas_obj.setFillColor(colors.lightgrey)
        canvas_obj.rect(doc.leftMargin, bar_bottom, doc.width, row_h, stroke=0, fill=1)
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setStrokeColor(colors.black)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.rect(doc.leftMargin, bar_bottom, doc.width, row_h, stroke=1, fill=0)

        canvas_obj.setFont('Helvetica-Bold', 8)
        labels = WYH_MONTHS + ["Total"]
        x = doc.leftMargin + label_w
        canvas_obj.line(doc.leftMargin + label_w, bar_bottom, doc.leftMargin + label_w, bar_top)
        for i, lbl in enumerate(labels):
            cw = month_col_widths[i]
            canvas_obj.drawCentredString(x + cw / 2, bar_bottom + 5, lbl)
            x += cw
            if i < len(labels) - 1:
                canvas_obj.line(x, bar_bottom, x, bar_top)

        canvas_obj.restoreState()
    return _on_page


def _wyh_make_numbered_canvas(footer_text):
    """Standard two-pass NumberedCanvas: buffer each page's drawing instead of finalizing
    it immediately, so by the time save() runs we know the true total page count and can
    stamp 'Page X of Y' (bottom-right) and the generation timestamp (bottom-left) on every
    page. Built as a closure/factory (not a module-level class) so footer_text is captured
    without any shared mutable state -- safe for concurrent PDF generation requests."""
    class _NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            Canvas.__init__(self, *args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._wyh_draw_footer(total_pages)
                Canvas.showPage(self)
            Canvas.save(self)

        def _wyh_draw_footer(self, total_pages):
            self.saveState()
            self.setFont('Helvetica', 8)
            self.setFillColor(colors.grey)
            self.drawString(0.35 * inch, 0.28 * inch, footer_text)
            self.drawRightString(self._pagesize[0] - 0.35 * inch, 0.28 * inch, f"Page {self._pageNumber} of {total_pages}")
            self.restoreState()

    return _NumberedCanvas


def generate_employee_wage_history_pdf(data: dict, filepath: str):
    """Renders the Employee Wage History report (Wages/EE/ER/EPS/Total per year, grouped
    into 5-row KeepTogether blocks) using the same figures the JSON endpoint / on-screen
    HTML report already computed -- data is the dict returned by
    _build_employee_wage_history_data() in webapp/app.py, not recomputed here."""
    est = data.get("establishment") or {}
    profile = data.get("profile") or {}
    years = data.get("years") or []

    doc = BaseDocTemplate(
        filepath, pagesize=A4,
        rightMargin=0.35 * inch, leftMargin=0.35 * inch,
        topMargin=0.3 * inch, bottomMargin=0.45 * inch
    )

    label_w = 0.85 * inch
    month_col_w = (doc.width - label_w) / 13.0
    month_col_widths = [month_col_w] * 13

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height - WYH_HEADER_HEIGHT, id='wyh', showBoundary=0)
    on_page = _wyh_make_onpage(
        est.get("name") or "", est.get("code") or "",
        profile.get("name") or "", profile.get("uan") or "", profile.get("member_id") or "",
        label_w, month_col_widths
    )
    doc.addPageTemplates([PageTemplate(id='wyh_template', frames=[frame], onPage=on_page)])

    story = []
    if not years:
        story.append(Paragraph("No wage records found.", style_title))

    def _vals_row(label, monthly, year_total, label_style, val_style):
        row = [Paragraph(label, label_style)]
        for v in monthly:
            row.append(Paragraph(str(int(round(v))) if v else "0", val_style))
        row.append(Paragraph(str(int(round(year_total or 0))), val_style))
        return row

    for y in years:
        block = [Paragraph(f"FY {y.get('year', '')}", style_subtitle), Spacer(1, 3)]

        table_data = [
            _vals_row("Wages", y.get("wages") or [0] * 12, y.get("total"), style_wyh_label_wages, style_wyh_val_wages),
            _vals_row("EE", y.get("ee_epf") or [0] * 12, y.get("ee_epf_total"), style_wyh_label_contrib, style_wyh_val_contrib),
            _vals_row("ER", y.get("er_epf") or [0] * 12, y.get("er_epf_total"), style_wyh_label_contrib, style_wyh_val_contrib),
            _vals_row("EPS", y.get("er_eps") or [0] * 12, y.get("er_eps_total"), style_wyh_label_contrib, style_wyh_val_contrib),
            _vals_row("Total", y.get("month_total") or [0] * 12, y.get("month_total_total"), style_wyh_label_total, style_wyh_val_total),
        ]

        t = Table(table_data, colWidths=[label_w] + month_col_widths)
        tstyle = TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (0, -1), 4),
            ('LINEABOVE', (0, 1), (-1, 1), 0.5, WYH_DIVIDER_COLOR),  # divider: below Wages, above EE
            ('LINEABOVE', (0, 4), (-1, 4), 0.5, WYH_DIVIDER_COLOR),  # divider: below EPS, above Total (identical weight/color to the one above)
        ])
        t.setStyle(tstyle)
        block.append(t)

        flags = []
        if y.get('higher_epf_ee'):
            flags.append('(Higher EPF - EE)')
        if y.get('higher_epf_er'):
            flags.append('(Higher EPF - ER)')
        if y.get('pohw'):
            flags.append('(Pension on Higher Wages' + (' + 1.16% shift)' if y.get('pohw_additional_1_16') else ')'))
        if y.get('age_crosses_58'):
            flags.append('(Age 58+ applied)')
        if flags:
            block.append(Paragraph(' '.join(flags), style_wyh_footnote))

        block.append(Spacer(1, 12))
        story.append(KeepTogether(block))

    footer_text = f"Generated: {datetime.now().strftime('%d %b %Y, %H:%M')}"
    doc.build(story, canvasmaker=_wyh_make_numbered_canvas(footer_text))
    return filepath
