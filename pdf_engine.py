import os
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
style_amount = ParagraphStyle(name='Amount', parent=styles['Normal'], fontName='Helvetica', fontSize=10, alignment=TA_RIGHT)
style_amount_bold = ParagraphStyle(name='AmountBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=TA_RIGHT)

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
        info_table = Table(info_data, colWidths=[20, 200, 10, 350], hAlign='LEFT')
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

# --------------------------------------------------------------------------
# Form 6A
# --------------------------------------------------------------------------
def generate_form_6a_pdf(project, year_key: str, filepath: str):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    est = project.build_establishment_for_year(year_key)
    employees = project.build_employees_for_year(year_key)
    
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
            
        row_vals = [wt, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot]
        for i, val in enumerate(row_vals):
            grand[i] += val
            
        data.append([
            Paragraph(str(sl), style_cell),
            Paragraph(member_id_display, style_cell_left),
            Paragraph(emp.name or "", style_cell_left),
            Paragraph(str(wt) if wt else "", style_cell_right),
            Paragraph(str(w_epf) if w_epf else "", style_cell_right),
            Paragraph(str(w_eps) if w_eps else "", style_cell_right),
            Paragraph(str(w_tot) if w_tot else "", style_cell_right),
            Paragraph(str(e_epf) if e_epf else "", style_cell_right),
            Paragraph(str(e_eps) if e_eps else "", style_cell_right),
            Paragraph(str(e_tot) if e_tot else "", style_cell_right),
            Paragraph("", style_cell)
        ])
        
    data.append([
        Paragraph("<b>GRAND TOTAL</b>", style_cell_bold), "", "",
        Paragraph(f"<b>{grand[0]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[1]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[2]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[3]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[4]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[5]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[6]}</b>", style_cell_right),
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
def generate_form_12a_pdf(project, year_key: str, filepath: str):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    est = project.build_establishment_for_year(year_key)
    employees = project.build_employees_for_year(year_key)
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
    
    from epf_engine import calendar_year_for_month, get_month_num, account2_rate_percent, account22_rate_percent, ACCOUNT_21_RATE, ACCOUNT_22_MIN, MONTHS
    
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
            
            a2_amt = round(wages_total * a2_rate / 100)
            a21_amt = round(wages_total * ACCOUNT_21_RATE / 100)
            a22_amt = (max(round(wages_total * a22_rate / 100), ACCOUNT_22_MIN) if (a22_rate > 0 and wages_total > 0) else 0)
            
            members = sum(1 for rows in all_month_rows if rows[i][0] > 0)
            acc_01 = ee_total + er_total
            
            month_remittances.append({
                "trrn": "-", "crrn": "-", "members": members, "acc_01": acc_01, "acc_02": a2_amt,
                "acc_10": a10_total, "acc_21": a21_amt, "acc_22": a22_amt, "credit_date": "-"
            })
            
        for idx, r in enumerate(month_remittances):
            trrn = r.get("trrn", "-")
            crrn = r.get("crrn", "-")
            members = int(r.get("members", 0))
            a1 = int(r.get("acc_01", 0))
            a2 = int(r.get("acc_02", 0))
            a10 = int(r.get("acc_10", 0))
            a21 = int(r.get("acc_21", 0))
            a22 = int(r.get("acc_22", 0))
            cdate = r.get("credit_date", "-")
            
            tot = a1 + a2 + a10 + a21 + a22
            
            grand[1] += a1; grand[2] += a2; grand[3] += a10; grand[4] += a21; grand[5] += a22; grand[6] += tot
            
            
            if idx == 0:
                parts = month_label.split(" Paid in ")
                if len(parts) == 2:
                    wage_month = parts[0]
                    paid_month = parts[1]
                    wage_yr = calendar_year_for_month(wage_month, est.year_from, est.year_to)
                    paid_yr = calendar_year_for_month(paid_month, est.year_from, est.year_to)
                    display_month = f"{wage_month} {wage_yr}<br/>Paid in<br/>{paid_month} {paid_yr}"
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
        Paragraph("<b>GRAND TOTAL</b>", style_cell_bold), "", "", "",
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
    tstyle.add('SPAN', (0,-1), (3,-1))
    tstyle.add('BACKGROUND', (0,0), (-1,0), colors.lightgrey)
    table.setStyle(tstyle)
    story.append(table)
    
    doc.build(story)
    return filepath

# --------------------------------------------------------------------------
# Form 5
# --------------------------------------------------------------------------
def generate_form_5_pdf(project, filepath: str):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    from epf_engine import employees_joined_in_month, calendar_year_for_month, get_month_num, MONTHS
    
    from datetime import datetime
    MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    
    forms_generated = 0
    for month_abbr in MONTHS:
        cal_year = calendar_year_for_month(month_abbr, project.est.year_from if project.est else 0, project.est.year_to if project.est else 0)
        cal_month = get_month_num(month_abbr)
        if cal_year is None: continue
        
        matches = employees_joined_in_month(project, cal_year, cal_month)
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
def generate_form_10_pdf(project, filepath: str):
    doc = _build_pdf_doc(filepath, orientation="landscape")
    story = []
    
    from epf_engine import employees_left_in_month, calendar_year_for_month, get_month_num, MONTHS
    
    from datetime import datetime
    MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    
    forms_generated = 0
    for month_abbr in MONTHS:
        cal_year = calendar_year_for_month(month_abbr, project.est.year_from if project.est else 0, project.est.year_to if project.est else 0)
        cal_month = get_month_num(month_abbr)
        if cal_year is None: continue
        
        matches = employees_left_in_month(project, cal_year, cal_month)
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
