def generate_pdf_engine():
    code = """import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

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
def generate_form_9_pdf(project, filepath: str):
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
        "Sr. No", "Member ID", "UAN", "Name of Employee\\n(in block capital)",
        "Father's Name (or Husband's\\nName in case of married women)",
        "Date of\\nBirth", "Sex", "Date of Eligibility\\nfor Membership",
        "Total Period of Previous Service\\n(excluding period of break) as on\\ndate of joining the fund",
        "Machine/ Folio No. of\\nLedger Card Opened", "Initials of S.S.",
        "Date and Reason of\\nLeaving Service",
        "D.C./S.S./A.A.O./A.C. Remarks\\nand Initial on Settlement"
    ]
    
    header_row = [Paragraph(h.replace('\\n', '<br/>'), style_cell_bold) for h in headers]
    data = [header_row]
    
    employees = project.master_list()
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
    weights = [0.04, 0.08, 0.08, 0.12, 0.12, 0.06, 0.04, 0.06, 0.08, 0.08, 0.06, 0.09, 0.09]
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
# Form 3A
# --------------------------------------------------------------------------
def generate_form_3a_pdf(project, year_key: str, filepath: str):
    doc = _build_pdf_doc(filepath, orientation="portrait")
    story = []
    
    est = project.build_establishment_for_year(year_key)
    employees = project.build_employees_for_year(year_key)
    
    MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    
    for emp_idx, emp in enumerate(employees):
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
        info_table = Table(info_data, colWidths=[20, 200, 10, 300])
        info_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
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
        for i, m in enumerate(MONTHS):
            wages, w_epf, w_eps, w_total, e_epf, e_eps, e_total = month_rows[i]
            table_data.append([
                Paragraph(m, style_cell),
                Paragraph(str(wages) if wages else "", style_cell_right),
                Paragraph(str(w_epf) if w_epf else "", style_cell_right),
                Paragraph(str(w_eps) if w_eps else "", style_cell_right),
                Paragraph(str(w_total) if w_total else "", style_cell_right),
                Paragraph(str(e_epf) if e_epf else "", style_cell_right),
                Paragraph(str(e_eps) if e_eps else "", style_cell_right),
                Paragraph(str(e_total) if e_total else "", style_cell_right),
                Paragraph("", style_cell), Paragraph("", style_cell), Paragraph("", style_cell)
            ])
            
        wt, w_epf_t, w_eps_t, w_tot_t, e_epf_t, e_eps_t, e_tot_t = emp.annual_totals(
            w_epf_rate, w_eps_rate, e_epf_rate, e_eps_rate)
            
        table_data.append([
            Paragraph("Total", style_cell_bold),
            Paragraph(str(wt) if wt else "", style_cell_right),
            Paragraph(str(w_epf_t) if w_epf_t else "", style_cell_right),
            Paragraph(str(w_eps_t) if w_eps_t else "", style_cell_right),
            Paragraph(str(w_tot_t) if w_tot_t else "", style_cell_right),
            Paragraph(str(e_epf_t) if e_epf_t else "", style_cell_right),
            Paragraph(str(e_eps_t) if e_eps_t else "", style_cell_right),
            Paragraph(str(e_tot_t) if e_tot_t else "", style_cell_right),
            Paragraph("", style_cell), Paragraph("", style_cell), Paragraph("", style_cell)
        ])
        
        aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
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
        
        story.append(KeepTogether(block))
        if emp_idx < len(employees) - 1:
            story.append(PageBreak())
            
    doc.build(story)
    return filepath
"""
    with open("pdf_engine.py", "w", encoding="utf-8") as f:
        f.write(code)

generate_pdf_engine()
