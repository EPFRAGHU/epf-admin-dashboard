def append_pdf_engine():
    code = """
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
    
    story.append(Paragraph(f"<b>Name & Address of the Establishment :- </b> {est.name}, {est.address}", style_header))
    story.append(Paragraph(f"<b>Code No. of the Establishment :- </b> {est.code}", style_header))
    story.append(Spacer(1, 12))
    
    headers = [
        "Wages Month", "TRRN", "CRRN", "Members", "A/c No.1\\n(EE+ER) Rs.",
        "A/c No.2\\n(Admin Chgs.) Rs.", "A/c No.10\\n(Pension Fund) Rs.", "A/c No.21\\n(EDLI) Rs.",
        "A/c No.22\\n(EDLI Admin) Rs.", "Total\\nRs.", "Credit Date"
    ]
    
    data = [[Paragraph(h.replace('\\n', '<br/>'), style_cell_bold) for h in headers]]
    
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
            
            display_month = month_label if idx == 0 else ""
            
            data.append([
                Paragraph(display_month, style_cell),
                Paragraph(str(trrn), style_cell),
                Paragraph(str(crrn), style_cell),
                Paragraph(str(members), style_cell_right),
                Paragraph(str(a1), style_cell_right),
                Paragraph(str(a2), style_cell_right),
                Paragraph(str(a10), style_cell_right),
                Paragraph(str(a21), style_cell_right),
                Paragraph(str(a22), style_cell_right),
                Paragraph(str(tot), style_cell_right),
                Paragraph(str(cdate), style_cell)
            ])
            
    data.append([
        Paragraph("<b>GRAND TOTAL</b>", style_cell_bold), "", "", "",
        Paragraph(f"<b>{grand[1]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[2]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[3]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[4]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[5]}</b>", style_cell_right),
        Paragraph(f"<b>{grand[6]}</b>", style_cell_right),
        ""
    ])
    
    aw = doc.pagesize[0] - doc.rightMargin - doc.leftMargin
    weights = [0.08, 0.12, 0.12, 0.06, 0.1, 0.1, 0.1, 0.08, 0.08, 0.08, 0.08]
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
            "Father's Name or Husband's\\nName in case of married women",
            "Age/ Date of\\nBirth", "Sex", "Date of Eligibility\\nfor Service",
            "Total Period of Previous Service\\n(excluding period of breaks) as on\\nthe date of joining the fund", "Remarks"
        ]
        
        data = [[Paragraph(h.replace('\\n', '<br/>'), style_cell_bold) for h in headers]]
        
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
            "Father's Name or Husband's\\nName in case of married",
            "Date of Leaving\\nService", "Reason for\\nLeaving Service", "Remarks"
        ]
        
        data = [[Paragraph(h.replace('\\n', '<br/>'), style_cell_bold) for h in headers]]
        
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
            "(1) A request for deduction from the account of a member dismissed for serious and willful misconduct should be reported by the following \"certified that the member mentioned at Sr. No. ___________ Shri ___________ was dismissed from the service for willful misconduct. I recommend that the employer's contribution for ___________ should be forfeited from his account in the fund. A copy of order of dismissal is enclosed.",
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
"""
    with open("pdf_engine.py", "a", encoding="utf-8") as f:
        f.write(code)

append_pdf_engine()
