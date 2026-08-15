"""
One-off generator for the EPF Admin Dashboard User Manual PDF.
Run manually: python webapp/generate_user_manual.py
Produces webapp/static_docs/EPF_Dashboard_User_Manual.pdf, embedding real
screenshots captured from a live walkthrough of the app.
"""
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    KeepTogether, PageBreak, Image
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen.canvas import Canvas
from PIL import Image as PILImage

HERE = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS = r"C:\Users\Dell\AppData\Local\Temp\claude\E--Users-Dell-Downloads-epf-dashboard-keka-theme\7f436181-3dc2-4ee2-abeb-9d291e545a9d\scratchpad\manual_screenshots"
OUT_DIR = os.path.join(HERE, "static_docs")
OUT_FILE = os.path.join(OUT_DIR, "EPF_Dashboard_User_Manual.pdf")

styles = getSampleStyleSheet()
style_cover_title = ParagraphStyle(name='CoverTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=24, alignment=TA_CENTER, spaceAfter=10)
style_cover_sub = ParagraphStyle(name='CoverSub', parent=styles['Normal'], fontName='Helvetica', fontSize=12, alignment=TA_CENTER, textColor=colors.grey, spaceAfter=6)
style_section = ParagraphStyle(name='Section', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=15, textColor=colors.HexColor('#4C3FE0'), spaceBefore=6, spaceAfter=10)
style_step_head = ParagraphStyle(name='StepHead', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10.5, spaceBefore=10, spaceAfter=4)
style_body = ParagraphStyle(name='Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=14, alignment=TA_LEFT, spaceAfter=6)
style_step = ParagraphStyle(name='Step', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=14, leftIndent=14, spaceAfter=4)
style_caption = ParagraphStyle(name='Caption', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceBefore=3, spaceAfter=14)
style_toc_entry = ParagraphStyle(name='TocEntry', parent=styles['Normal'], fontName='Helvetica', fontSize=10.5, leading=20)
style_warn_head = ParagraphStyle(name='WarnHead', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, textColor=colors.HexColor('#C0392B'), spaceBefore=6, spaceAfter=10)
style_warn_item = ParagraphStyle(name='WarnItem', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=14, leftIndent=14, spaceAfter=6)

PAGE_W, PAGE_H = A4
CONTENT_W = PAGE_W - 1.0 * inch


def img_flowable(filename, max_w=CONTENT_W, max_h=3.4 * inch):
    path = os.path.join(SCREENSHOTS, filename)
    with PILImage.open(path) as im:
        w, h = im.size
    ratio = min(max_w / w, max_h / h)
    return Image(path, width=w * ratio, height=h * ratio)


def screenshot_block(filename, caption):
    return KeepTogether([img_flowable(filename), Paragraph(caption, style_caption)])


def _numbered_canvas_factory():
    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            Canvas.__init__(self, *args, **kwargs)
            self._saved_states = []

        def showPage(self):
            self._saved_states.append(dict(self.__dict__))
            Canvas.showPage(self)

        def save(self):
            total = len(self._saved_states)
            for state in self._saved_states:
                self.__dict__.update(state)
                self._draw_footer(total)
                Canvas.showPage(self)
            Canvas.save(self)

        def _draw_footer(self, total_pages):
            self.setFont('Helvetica', 7.5)
            self.setFillColor(colors.grey)
            self.drawString(0.5 * inch, 0.35 * inch, "EPF Admin Dashboard \u2014 User Manual")
            self.drawRightString(PAGE_W - 0.5 * inch, 0.35 * inch, f"Page {self._pageNumber} of {total_pages}")
    return NumberedCanvas


def build_story():
    story = []

    # ---- Cover page ----
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph("EPF Admin Dashboard", style_cover_title))
    story.append(Paragraph("User Manual & Operating Guide", style_cover_sub))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("A step-by-step guide for consultants and establishment administrators covering "
                            "establishment registration, employee data entry, wage entry, EPF challans "
                            "(TRRN/CRRN), statutory reports, and subscription payments.", style_cover_sub))
    story.append(PageBreak())

    # ---- Table of contents ----
    story.append(Paragraph("Contents", style_section))
    toc_items = [
        "1. Logging In",
        "2. Dashboard Overview",
        "3. Setting Up the Establishment Register",
        "4. Organization Structure (Branches, Divisions, Units)",
        "5. Employee Import & Data Entry",
        "6. Creating a Financial Year Entry",
        "7. Wage Entry",
        "8. Challans \u2014 TRRN & CRRN Entry",
        "9. Generating Statutory Reports",
        "10. Subscription Fees & Making Payments",
        "11. How Data Is Saved",
        "12. What You Should NOT Do",
    ]
    for item in toc_items:
        story.append(Paragraph(item, style_toc_entry))
    story.append(PageBreak())

    # ---- 1. Login ----
    story.append(Paragraph("1. Logging In", style_section))
    story.append(Paragraph(
        "Open the application URL in a browser and sign in with the email address and password issued to you "
        "by your administrator. Consultants and superadmins share the same login screen \u2014 the system "
        "automatically routes you to the correct view based on your account role.", style_body))
    story.append(screenshot_block("01_login.jpg", "The sign-in screen. Enter your email and password, then click Sign In."))
    story.append(Paragraph(
        "Each user account belongs to exactly one role \u2014 Consultant or Superadmin. Consultants only see "
        "the establishments assigned to them; superadmins can see and manage every establishment in the system.",
        style_body))
    story.append(PageBreak())

    # ---- 2. Dashboard ----
    story.append(Paragraph("2. Dashboard Overview", style_section))
    story.append(Paragraph(
        "After logging in you land on the Dashboard for your currently active establishment. It shows total "
        "employees, number of financial years on record, total wages, and total EPF contributions, along with "
        "charts of contributions and employee count over the years, and a month-wise contribution summary.",
        style_body))
    story.append(screenshot_block("02_dashboard.jpg", "Dashboard Overview for the active establishment."))
    story.append(Paragraph(
        "If you manage more than one establishment, use \u201cSwitch Establishment\u201d in the left sidebar, "
        "or the \u201c\u21c4 Switch\u201d link next to the establishment name in the top-right corner, to change "
        "which establishment's data you are viewing and editing.", style_body))
    story.append(PageBreak())

    # ---- 3. Establishment register ----
    story.append(Paragraph("3. Setting Up the Establishment Register", style_section))
    story.append(Paragraph(
        "Every establishment must be registered before any employee, wage, or report data can be entered "
        "against it. There are two places to do this:", style_body))
    story.append(Paragraph(
        "<b>A) Registering a brand-new establishment.</b> Go to <b>My Establishments</b> in the sidebar, then "
        "click <b>+ Add Establishment</b>. Fill in the 15-character EPFO Establishment Code, the establishment "
        "name, postal address, and EPF coverage date (the date from which the establishment became liable "
        "under the EPF Act), then click <b>Create Establishment</b>.", style_step))
    story.append(screenshot_block("04_my_establishments.jpg", "My Establishments \u2014 lists every establishment you have access to, with quick actions."))
    story.append(screenshot_block("05_register_new_establishment.jpg", "The Register New Establishment form, reached via + Add Establishment."))
    story.append(Paragraph(
        "<b>B) Editing an existing establishment's profile.</b> Go to <b>Establishment</b> in the sidebar to "
        "view or update the code, name, address, and coverage date of the currently active establishment. Click "
        "<b>Save Details</b> after making changes.", style_step))
    story.append(screenshot_block("03_establishment_profile.jpg", "Establishment Profile page \u2014 also lists all covered establishments with Edit / Load actions."))
    story.append(Paragraph(
        "The Establishment Code is used to name every exported file (Excel, PDF, ECR text files) and is printed "
        "on official Form 3A, 6A, and ECR returns \u2014 double-check it is entered exactly as issued by EPFO "
        "before generating any statutory documents.", style_body))
    story.append(PageBreak())

    # ---- 4. Org structure ----
    story.append(Paragraph("4. Organization Structure (Branches, Divisions, Units)", style_section))
    story.append(Paragraph(
        "This is an optional step. If your establishment has multiple physical locations, departments, or "
        "sub-units, define them under <b>Org Structure</b> in the sidebar so employees can be grouped and "
        "ECR files can be generated branch-wise. Type a name in the relevant box (Branches/Locations, "
        "Divisions/Departments, or Units/Blocks) and click <b>+ Add</b>.", style_body))
    story.append(screenshot_block("06_org_structure.jpg", "Org Structure page \u2014 defines Branches, Divisions, and Units for the establishment."))
    story.append(PageBreak())

    # ---- 5. Employees ----
    story.append(Paragraph("5. Employee Import & Data Entry", style_section))
    story.append(Paragraph(
        "Go to <b>Employees</b> in the sidebar. This is the Employee Master \u2014 every employee who has ever "
        "been a member of the EPF scheme at this establishment.", style_body))
    story.append(screenshot_block("07_employees_list.jpg", "Employee Master list, showing Member ID, UAN, name, father's name, DOB, sex, DOJ, DOE and reason."))
    story.append(Paragraph(
        "<b>A) Adding employees one at a time.</b> Click <b>+ Add Employee</b> and fill in the Member ID (required), "
        "UAN, Name (required), branch/division/unit, father's/husband's name, date of birth, sex, date of joining "
        "(EPF), date of exit and reason for leaving (if applicable), and other identity fields. Tick "
        "<b>Allow Higher EPF (EE)</b> or <b>(ER)</b> only for employees who have formally opted for contribution "
        "on actual wages above the statutory ceiling.", style_step))
    story.append(screenshot_block("08_add_employee.jpg", "Add New Employee form."))
    story.append(Paragraph(
        "<b>B) Bulk importing employees.</b> For a new establishment or a large batch of employees, click "
        "<b>Bulk Import Master</b> and upload an Excel (.xlsx) file. The file must contain columns for Member ID, "
        "Name, Father's Name, Date of Birth, Sex, Date of Joining, Date of Exit, Reason of Leaving, UAN No., and "
        "SL. Re-uploading a file with the same Member IDs updates those existing records rather than duplicating "
        "them.", style_step))
    story.append(screenshot_block("09_bulk_import_employees.jpg", "Import Employee Master \u2014 bulk Excel upload dialog."))
    story.append(PageBreak())

    # ---- 6. Financial years ----
    story.append(Paragraph("6. Creating a Financial Year Entry", style_section))
    story.append(Paragraph(
        "Wages and contributions are always entered against a specific financial year. Go to "
        "<b>Financial Years</b> in the sidebar to see existing years and their contribution schemes and rates.",
        style_body))
    story.append(screenshot_block("10_financial_years.jpg", "Financial Years & Rates \u2014 one card per year, showing scheme and rates."))
    story.append(Paragraph(
        "Click <b>+ Add Year</b>, enter the Year From / Year To range, and choose the applicable scheme: "
        "<b>Pre-1997 (EPF + FPF)</b> for years before the Employees' Pension Scheme replaced the Family Pension "
        "Fund, or <b>Post-1997</b> for later years. The Worker EPF %, Employer EPF %, and Family Pension/Pension "
        "Fund % fields pre-fill with the statutory defaults for the scheme \u2014 only change them if your "
        "establishment has a documented exception. Click <b>Create Year</b> when done. Use <b>Bulk Generate</b> "
        "to create several consecutive years at once with the same scheme.", style_step))
    story.append(screenshot_block("11_add_financial_year.jpg", "Add Financial Year form, with scheme selector and rate fields."))
    story.append(Paragraph(
        "The wage-ceiling amount and Account 22 (EDLI Admin) rate that apply to each month are derived "
        "automatically from the month's actual calendar date, not just the financial year \u2014 you do not need "
        "to adjust these manually for statutory rate changes.", style_body))
    story.append(PageBreak())

    # ---- 7. Wage entry ----
    story.append(Paragraph("7. Wage Entry", style_section))
    story.append(Paragraph(
        "Go to <b>Wage Entry</b> in the sidebar and pick the financial year from the dropdown at the top. Each "
        "employee has a month-by-month table showing Gross Wages, EPF Wages, NCP (Non-Contributing Period) Days, "
        "and the resulting Worker/Employer EPF and Pension Fund contributions \u2014 these are calculated "
        "automatically from the wage figures and the year's rates the moment you enter a value.", style_body))
    story.append(screenshot_block("12_wage_entry_grid.jpg", "Per-employee monthly wage table on the Wage Entry page, with Form 3A/6A/12A quick-download buttons above it."))
    story.append(Paragraph(
        "For faster data entry across many employees at once, click <b>+ Monthly Wage Entry</b>, choose the "
        "month from the dropdown, and enter Gross Wages and NCP Days for each employee in the grid. Tick "
        "<b>Higher EPF (EE)</b> / <b>(ER)</b> or <b>Age &gt; 58</b> per employee where applicable \u2014 these "
        "checkboxes change how the Pension Fund (EPS) share is computed for that employee that month. "
        "<b>Bulk Import</b> and <b>Import Excel</b> at the top of the Wage Entry page let you upload monthly wage "
        "data for many employees from a spreadsheet instead of typing it in by hand.", style_step))
    story.append(screenshot_block("13_monthly_wage_entry_modal.jpg", "Monthly Wage Entry grid \u2014 enter Gross Wages and NCP Days per employee for the selected month."))
    story.append(PageBreak())

    # ---- 8. Challans ----
    story.append(Paragraph("8. Challans \u2014 TRRN & CRRN Entry", style_section))
    story.append(Paragraph(
        "Go to <b>Challans</b> in the sidebar and select the financial year. Every month with wage data shows "
        "its computed remittance breakdown \u2014 Gross Wages, EPF Wages, EPS Wages, EDLI Wages, and the exact "
        "amount due under Account 1 (EPF), Account 2 (EPF Admin), Account 10 (Pension Fund), Account 21 (EDLI), "
        "and Account 22 (EDLI Admin) \u2014 computed automatically from that month's wage entries. You cannot "
        "edit these amounts directly; correct the underlying wage entries on the Wage Entry page if a total "
        "looks wrong.", style_body))
    story.append(screenshot_block("14_challans_trrn_crrn.jpg", "Challans / Remittances page, with the TRRN and CRRN entry fields for each month."))
    story.append(Paragraph(
        "After you remit the month's contribution through the EPFO unified portal, come back here and enter the "
        "<b>TRRN</b> (Temporary Return Reference Number) and <b>CRRN</b> (Challan Receipt Reference Number) "
        "issued by EPFO for that month in the corresponding fields, plus the credit date. These numbers are "
        "printed on the statutory annual returns, so they should be entered accurately before generating Form "
        "3A / 6A / 12A for year-end filing.", style_step))
    story.append(screenshot_block("15_challans_trrn_crrn_filled.jpg", "Entering a TRRN and CRRN for a month. Click Save All Changes to persist the entries for the year."))
    story.append(Paragraph(
        "Remember to click <b>Save All Changes</b> at the top of the table after entering TRRN/CRRN/credit-date "
        "values \u2014 navigating away without saving discards unsaved entries on this page.", style_body))
    story.append(PageBreak())

    # ---- 9. Reports ----
    story.append(Paragraph("9. Generating Statutory Reports", style_section))
    story.append(Paragraph(
        "Go to <b>Reports</b> in the sidebar. Four sections are available:", style_body))
    story.append(screenshot_block("16_reports_page.jpg", "Reports & Export page: Employee Master (Form 9), Annual Returns, ECR Text File Generator, and Employee Wage History."))
    story.append(Paragraph(
        "<b>Employee Master (Form 9):</b> exports the full Employee Master as PDF or Excel.<br/>"
        "<b>Annual Returns (Forms 3A, 6A, 12A, 5, 10):</b> pick the financial year, tick the specific forms you "
        "need (all five start unticked by default \u2014 select only what you actually need to generate), then "
        "click <b>Download Selected as PDF</b> or <b>...as Excel</b>.<br/>"
        "<b>ECR Text File Generator:</b> generates the EPFO v3.0 Electronic Challan cum Return text file for a "
        "specific month, ready for direct upload to the EPFO unified portal.<br/>"
        "<b>Employee Wage History:</b> search for a single employee to view and download their complete "
        "year-by-year wage and contribution history as a PDF.", style_step))
    story.append(screenshot_block("17_reports_downloading.jpg", "A report download in progress, shown via the confirmation toast in the bottom-right corner."))
    story.append(PageBreak())

    # ---- 10. Payments ----
    story.append(Paragraph("10. Subscription Fees & Making Payments", style_section))
    story.append(Paragraph(
        "Using this platform carries a small monthly subscription fee per establishment, based on the number of "
        "employees with wage data that month. If a month's fee becomes overdue (one day past month end) and "
        "remains unpaid, report and ECR downloads for that establishment are blocked until payment is made \u2014 "
        "superadmin accounts are exempt from this restriction. When you attempt an affected download, a payment "
        "modal opens letting you pay that month's fee via Cashfree before the file downloads.", style_body))
    story.append(Paragraph(
        "<b>Subscription History.</b> From <b>My Establishments</b>, click <b>Subscription History</b> on any "
        "establishment card to see every month's fee, whether it was paid via Cashfree or from advance credit, "
        "the payment date, and reference number, plus your running Advance Credit balance.", style_step))
    story.append(screenshot_block("18_subscription_history.jpg", "Subscription History page \u2014 Advance Credit balance, top-up history, and per-month fee payments."))
    story.append(Paragraph(
        "<b>Advance Credit.</b> To prepay a lump sum that automatically covers future months as wage data is "
        "entered (so you are not interrupted by a payment prompt mid-task), click <b>Add Advance Credit</b> on "
        "the establishment card or on its Subscription History page, enter the amount, and click "
        "<b>Pay via Cashfree</b>. You will be taken to the Cashfree checkout page to complete the payment; the "
        "app automatically brings you back and updates your balance once payment is confirmed.", style_step))
    story.append(screenshot_block("19_add_advance_credit_modal.jpg", "Add Advance Credit modal \u2014 prepay a lump sum against future monthly fees."))
    story.append(PageBreak())

    # ---- 11. Saving ----
    story.append(Paragraph("11. How Data Is Saved", style_section))
    story.append(Paragraph(
        "This application has no separate \u201cSave File\u201d step \u2014 it is a web app, and every screen "
        "saves directly to the server as soon as you submit a form or click a save/update button:", style_body))
    story.append(Paragraph(
        "\u2022 Establishment Profile: click <b>Save Details</b>.<br/>"
        "\u2022 Employees, Financial Years: saved immediately when you click Create/Update in the form.<br/>"
        "\u2022 Wage Entry: each value is saved as you enter it in the per-employee table, or when you submit the "
        "Monthly Wage Entry grid.<br/>"
        "\u2022 Challans (TRRN/CRRN/credit date): you must explicitly click <b>Save All Changes</b> \u2014 this is "
        "the one screen where edits are not saved automatically as you type.", style_step))
    story.append(Paragraph(
        "Because everything is saved to the server immediately, closing the browser tab does not \u201close "
        "without saving\u201d the way a desktop application would \u2014 any change you have already submitted is "
        "already stored. Reports and ECR files, once downloaded, are separate files on your own computer and are "
        "not stored or re-downloadable from the app \u2014 keep your own copies for filing records.", style_body))
    story.append(PageBreak())

    # ---- 12. What not to do ----
    story.append(Paragraph("12. What You Should NOT Do", style_warn_head))
    warnings = [
        "<b>Do not share login credentials</b> between staff members. Each consultant account is tied to a "
        "specific set of establishments; sharing a login removes any ability to know who made a given change.",
        "<b>Do not manually edit a downloaded ECR text file.</b> It is generated in the exact fixed format EPFO's "
        "portal expects; hand-editing it risks a malformed upload that the portal will reject or misprocess. "
        "If a figure in it is wrong, correct the wage entry in the app and re-generate the file.",
        "<b>Do not enter or change TRRN/CRRN/credit-date values from memory.</b> Enter them only from the actual "
        "challan receipt issued by EPFO after remittance \u2014 these numbers are printed on statutory annual "
        "returns (Form 3A/6A) and must match EPFO's own records.",
        "<b>Do not override the Higher EPF (EE)/(ER) or Age &gt; 58 checkboxes</b> on the Wage Entry page unless "
        "the employee has formally opted for it, or has genuinely crossed the relevant age \u2014 these directly "
        "change how the Pension Fund (EPS) share is calculated for that employee and can misstate statutory "
        "liability if set incorrectly.",
        "<b>Do not ignore the subscription-fee payment prompt.</b> Report and ECR downloads for a month are "
        "blocked once that month's fee is overdue and unpaid; the modal that appears is the fastest way to clear "
        "it and resume the download, rather than assuming it is an error.",
        "<b>Do not leave Challans edits unsaved.</b> Unlike other pages, TRRN/CRRN/credit-date entries on the "
        "Challans page are only persisted when you click <b>Save All Changes</b> \u2014 navigating away first "
        "discards them.",
        "<b>Do not delete a Financial Year or an Employee record</b> that already has wage history or has been "
        "used to generate filed statutory returns, without being certain it is safe to do so \u2014 this removes "
        "the underlying data those returns were built from and cannot be undone from within the app.",
        "<b>Do not assume a report download always \u201cjust works.\u201d</b> If a download fails or behaves "
        "unexpectedly, check the subscription-fee banner at the top of the Challans/Reports pages first, and "
        "verify the financial year and month selected are the ones you intend.",
    ]
    for w in warnings:
        story.append(Paragraph(f"\u2022 {w}", style_warn_item))

    return story


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = SimpleDocTemplate(
        OUT_FILE,
        pagesize=A4,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.55 * inch,
        title="EPF Admin Dashboard - User Manual",
    )
    story = build_story()
    doc.build(story, canvasmaker=_numbered_canvas_factory())
    print(f"Wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
