#!/usr/bin/env python3
"""
EPF Form 3A / 6A Manager
=========================
A desktop data-entry program for EPFO Form 3A (per-employee contribution
card) and Form 6A (annual establishment summary).

Enter the Establishment details ONCE and the Employee Master (account
number + name) ONCE per employee. Then, for each financial year, add
that year's monthly wages for each employee -- the account number
auto-fills the employee's name from the master -- and generate a
separate, fully formatted Excel workbook for that year containing:

    * a "3A_<yy-yy>" sheet -- every employee's Form 3A contribution card
    * a "6A_<yy-yy>" sheet -- the Form 6A annual summary for that year

Each year's data is kept completely separate. Generating the Excel file
only ever produces the single year currently selected.

Run with:   python epf_form_manager.py
Requires:   openpyxl   (pip install openpyxl)
            tkinter is bundled with standard Python on Windows / macOS.
            On Linux, install it via your package manager if missing,
            e.g. "sudo apt install python3-tk".
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

from epf_engine import (MONTHS, ExcelGenerator, Project, import_wages_from_excel,
                         SCHEME_PRE_1997, SCHEME_POST_1997,
                         REASONS_FOR_LEAVING, SUPERANNUATION_AGE, calc_age_years,
                         natural_sort_key, generate_forms_for_year_range,
                         generate_form5_for_month, generate_form10_for_month, generate_form9, MONTH_NAMES)

APP_TITLE = "EPF Form 3A / 6A Manager"

# ---------------------------------------------------------------------------
# Colour palette / fonts -- kept in one place so the whole app stays coherent
# ---------------------------------------------------------------------------
COLOR_BG = "#F4F6F9"
COLOR_HEADER = "#1F4E78"
COLOR_HEADER_TEXT = "#FFFFFF"
COLOR_ACCENT = "#2E75B6"
COLOR_CARD = "#FFFFFF"
COLOR_ROW_ALT = "#EEF3FA"
COLOR_TABLE_HEAD = "#D9E1F2"
FONT_TITLE = ("Segoe UI", 18, "bold")
FONT_SECTION = ("Segoe UI", 12, "bold")
FONT_LABEL = ("Segoe UI", 10)
FONT_ENTRY = ("Segoe UI", 10)
FONT_MONO = ("Consolas", 10)


def currency(v):
    try:
        return f"{v:,.0f}"
    except Exception:
        return str(v)


def to_float(text):
    text = (text or "").strip().replace(",", "")
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


class LabeledEntry(ttk.Frame):
    """A small helper widget: a label above an entry box."""

    def __init__(self, master, label, width=20, style_bg="Card.TFrame", **kw):
        super().__init__(master, style=style_bg)
        self.var = tk.StringVar()
        lbl_style = "Card.TLabel" if style_bg == "Card.TFrame" else "TLabel"
        ttk.Label(self, text=label, font=FONT_LABEL, style=lbl_style).pack(anchor="w")
        ent = ttk.Entry(self, textvariable=self.var, width=width, font=FONT_ENTRY)
        ent.pack(fill="x", pady=(2, 6))
        self.entry = ent

    def get(self):
        return self.var.get().strip()

    def set(self, value):
        self.var.set("" if value is None else str(value))


# ---------------------------------------------------------------------------
# Employee Master dialog (Member ID / Name / Father's Name / DOB / Sex /
# Date of Joining -- shared globally). This form STAYS OPEN after Save, just
# like the Wage Entry form, and includes First/Previous/Next/Last record
# navigation with the record number shown in the middle.
# ---------------------------------------------------------------------------
class MasterEmployeeDialog(tk.Toplevel):
    def __init__(self, app, project: Project, start_index=None):
        """
        app         -- the main EPFApp window (used to refresh its lists live
                        as each record is saved, and as the Tk parent)
        start_index -- which record (0-based, into project.master_list()) to
                        open on. None (default) opens a brand-new blank
                        record ready for the next employee to be typed in.
        """
        super().__init__(app)
        self.title("Employee Master Entry (Form 9)")
        self.configure(bg=COLOR_BG)
        self.resizable(True, True)
        self.geometry("1050x720")
        self.app = app
        self.project = project
        self.grab_set()

        outer = ttk.Frame(self, padding=16, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        # ---- identity row: Member ID / UAN / Name / Father's Name ----
        row1 = ttk.Frame(outer, style="Card.TFrame")
        row1.pack(fill="x")
        self.sl = LabeledEntry(row1, "SL No.", width=8)
        self.sl.pack(side="left", padx=(0, 12))
        self.acc = LabeledEntry(row1, "Member ID", width=20)
        self.acc.pack(side="left", padx=(0, 12))
        self.uan = LabeledEntry(row1, "UAN No.", width=18)
        self.uan.pack(side="left", padx=(0, 12))
        self.name = LabeledEntry(row1, "Employee Name", width=26)
        self.name.pack(side="left", padx=(0, 12))
        self.father = LabeledEntry(row1, "Father's Name (optional)", width=24)
        self.father.pack(side="left")

        self.acc.entry.bind("<KeyRelease>", lambda e: self._on_account_typing())
        self.acc.entry.bind("<FocusOut>", lambda e: self._on_account_tab())
        self.acc.entry.bind("<Return>", lambda e: self._on_account_tab())

        # ---- DOB / Sex / Date of Joining row ----
        row2 = ttk.Frame(outer, style="Card.TFrame")
        row2.pack(fill="x", pady=(8, 0))
        self.dob = LabeledEntry(row2, "Date of Birth (DD/MM/YYYY)", width=20)
        self.dob.pack(side="left", padx=(0, 12))
        self.doj = LabeledEntry(row2, "Date of Joining (DD/MM/YYYY)", width=20)
        self.doj.pack(side="left", padx=(0, 16))

        sex_box = ttk.Frame(row2, style="Card.TFrame")
        sex_box.pack(side="left")
        ttk.Label(sex_box, text="Sex", font=FONT_LABEL, style="Card.TLabel").pack(anchor="w")
        sex_btns = ttk.Frame(sex_box, style="Card.TFrame")
        sex_btns.pack(anchor="w", pady=(2, 6))
        self.sex_var = tk.StringVar(value="")
        self.male_btn = tk.Button(sex_btns, text="Male", width=9, relief="raised",
                                   font=FONT_ENTRY, command=lambda: self._select_sex("Male"))
        self.male_btn.pack(side="left", padx=(0, 4))
        self.female_btn = tk.Button(sex_btns, text="Female", width=9, relief="raised",
                                     font=FONT_ENTRY, command=lambda: self._select_sex("Female"))
        self.female_btn.pack(side="left")

        # ---- Date of Exit / Reason of Leaving row ----
        row3 = ttk.Frame(outer, style="Card.TFrame")
        row3.pack(fill="x", pady=(8, 0))
        self.doe = LabeledEntry(row3, "Date of Exit (DD/MM/YYYY)", width=20)
        self.doe.pack(side="left", padx=(0, 12))

        reason_box = ttk.Frame(row3, style="Card.TFrame")
        reason_box.pack(side="left")
        ttk.Label(reason_box, text="Reason of Leaving", font=FONT_LABEL,
                  style="Card.TLabel").pack(anchor="w")
        self.reason_var = tk.StringVar(value="")
        self.reason_combo = ttk.Combobox(reason_box, textvariable=self.reason_var,
                                          values=REASONS_FOR_LEAVING, state="readonly",
                                          width=22, font=FONT_ENTRY)
        self.reason_combo.pack(anchor="w", pady=(2, 6))

        # ---- Higher EPF Checkboxes row ----
        row4 = ttk.Frame(outer, style="Card.TFrame")
        row4.pack(fill="x", pady=(8, 0))
        
        self.higher_ee_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4, text="Allow Higher EPF (EE) - Employee 12% on actual wages", 
                        variable=self.higher_ee_var, style="Card.TCheckbutton").pack(side="left", padx=(0, 20))
                        
        self.higher_er_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4, text="Allow Higher EPF (ER) - Employer PF on actual wages", 
                        variable=self.higher_er_var, style="Card.TCheckbutton").pack(side="left")

        # ---- age / superannuation warning ----
        self.age_var = tk.StringVar(value="")
        self.age_label = ttk.Label(outer, textvariable=self.age_var, font=("Segoe UI", 9, "bold"),
                                    style="Card.TLabel", foreground="#b00020")
        self.age_label.pack(anchor="w", pady=(8, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.status_var, font=("Segoe UI", 9, "italic"),
                  style="Card.TLabel", foreground=COLOR_ACCENT).pack(anchor="w", pady=(4, 0))

        # ---- Save / Delete / Close buttons ----
        btns = ttk.Frame(outer, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Close", command=self._close).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(btns, text="Delete This Record", command=self._delete_current).pack(side="left")

        # ---- navigation bar: First / Prev / SL no. / Next / Last ----
        nav = ttk.Frame(outer, style="Card.TFrame")
        nav.pack(fill="x", pady=(10, 0))
        ttk.Button(nav, text="<< First", command=self._go_first).pack(side="left")
        ttk.Button(nav, text="< Previous", command=self._go_prev).pack(side="left", padx=(6, 0))
        self.nav_label_var = tk.StringVar(value="")
        ttk.Label(nav, textvariable=self.nav_label_var, font=("Segoe UI", 10, "bold"),
                  style="Card.TLabel", anchor="center").pack(side="left", expand=True, fill="x")
        ttk.Button(nav, text="Next >", command=self._go_next).pack(side="right", padx=(0, 6))
        ttk.Button(nav, text="Last >>", command=self._go_last).pack(side="right")

        # ---- embedded employee list (shows all entered employees) ----
        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(12, 6))
        ttk.Label(outer, text="Employee Master Records (click a row to edit)",
                  font=FONT_SECTION, style="Card.TLabel").pack(anchor="w", pady=(0, 4))

        list_frame = ttk.Frame(outer, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True)

        emb_cols = ("sl", "acc", "uan", "name", "father", "dob", "sex", "doj")
        self.emb_tree = ttk.Treeview(list_frame, columns=emb_cols, show="headings", height=8)
        emb_headings = ["SL", "Member ID", "UAN", "Name", "Father's Name", "DOB", "Sex", "DOJ"]
        emb_widths = [35, 130, 100, 180, 160, 90, 50, 90]
        for c, h, w in zip(emb_cols, emb_headings, emb_widths):
            self.emb_tree.heading(c, text=h)
            self.emb_tree.column(c, width=w, anchor="w" if c in ("name", "father") else "center")

        emb_vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.emb_tree.yview)
        self.emb_tree.configure(yscrollcommand=emb_vsb.set)
        self.emb_tree.pack(side="left", fill="both", expand=True)
        emb_vsb.pack(side="right", fill="y")

        self.emb_tree.bind("<<TreeviewSelect>>", lambda e: self._on_embedded_list_click())
        self.emb_tree.tag_configure("current", background="#D9E1F2")

        self.dob.entry.bind("<KeyRelease>", lambda e: self._update_age_warning())

        self.index = start_index if start_index is not None else len(self.project.master_list())
        self._refresh_embedded_list()
        self._load_index(self.index)

    # ---- record navigation ---------------------------------------------
    def _records(self):
        return self.project.master_list()

    def _go_first(self):
        if self._records():
            self._load_index(0)

    def _go_prev(self):
        if self.index > 0:
            self._load_index(self.index - 1)

    def _go_next(self):
        records = self._records()
        if self.index < len(records):
            self._load_index(self.index + 1)

    def _go_last(self):
        records = self._records()
        if records:
            self._load_index(len(records) - 1)

    def _load_index(self, idx):
        records = self._records()
        self.index = idx
        if 0 <= idx < len(records):
            m = records[idx]
            self.sl.set(m.serial_no or "")
            self.acc.set(m.member_id)
            self.uan.set(m.uan)
            self.name.set(m.name)
            self.father.set(m.father_name)
            self.dob.set(m.dob)
            self.doj.set(m.doj)
            self.doe.set(m.doe)
            self.reason_var.set(m.reason_leaving)
            self._select_sex(m.sex)
            self.higher_ee_var.set(getattr(m, 'higher_epf_ee', False))
            self.higher_er_var.set(getattr(m, 'higher_epf_er', False))
            self.status_var.set("Existing employee. Type a different Member ID and press Tab "
                                 "or Enter to jump to that employee.")
        else:
            # a fresh, blank record ready for a new employee
            self.sl.set(self.project.next_serial_no())
            self.acc.set("")
            self.uan.set("")
            self.name.set("")
            self.father.set("")
            self.dob.set("")
            self.doj.set("")
            self.doe.set("")
            self.reason_var.set("")
            self._select_sex("")
            self.higher_ee_var.set(False)
            self.higher_er_var.set(False)
            self.status_var.set("New employee record.")
        self._loaded_member_id = self.acc.get()  # tracks what was last loaded/searched
        self._original_member_id = self.acc.get() if 0 <= idx < len(records) else None
        self._update_nav_label()
        self._update_age_warning()
        # Highlight the current record in the embedded list
        if hasattr(self, 'emb_tree'):
            self.emb_tree.selection_set(())
            if 0 <= idx < len(records):
                acc_no = records[idx].member_id
                if self.emb_tree.exists(acc_no):
                    self._loading = True
                    self.emb_tree.selection_set(acc_no)
                    self.emb_tree.see(acc_no)
                    self._loading = False
        self.acc.entry.focus_set()

    def _update_age_warning(self):
        age = calc_age_years(self.dob.get())
        if age is None:
            self.age_var.set("")
            self.age_label.configure(foreground="#555")
        elif age >= SUPERANNUATION_AGE:
            self.age_var.set(f"\u26a0 This employee is {age} years old - at or past the "
                              f"superannuation age of {SUPERANNUATION_AGE}.")
            self.age_label.configure(foreground="#b00020")
        else:
            self.age_var.set(f"Age: {age} years")
            self.age_label.configure(foreground="#555")

    def _update_nav_label(self):
        total = len(self._records())
        if self.index < total:
            self.nav_label_var.set(f"Record {self.index + 1} of {total}")
        else:
            self.nav_label_var.set(f"New Record (will be {total + 1} of {total + 1})")

    def _refresh_embedded_list(self):
        """Refresh the embedded employee list table below the form."""
        for row in self.emb_tree.get_children():
            self.emb_tree.delete(row)
        for m in self.project.master_list():
            self.emb_tree.insert("", "end", iid=m.member_id,
                                 values=(m.serial_no or "", m.member_id, m.uan, m.name,
                                         m.father_name, m.dob, m.sex, m.doj))

    def _on_embedded_list_click(self):
        """Load the selected employee from the embedded list into the form."""
        if getattr(self, '_loading', False):
            return
        sel = self.emb_tree.selection()
        if not sel:
            return
        acc = sel[0]
        records = self._records()
        match_idx = next((i for i, m in enumerate(records) if m.member_id == acc), None)
        if match_idx is not None:
            self._load_index(match_idx)

    # ---- sex toggle buttons -------------------------------------------
    def _select_sex(self, value):
        self.sex_var.set(value)
        self.male_btn.configure(bg=COLOR_ACCENT if value == "Male" else "SystemButtonFace",
                                 fg="white" if value == "Male" else "black",
                                 relief="sunken" if value == "Male" else "raised")
        self.female_btn.configure(bg=COLOR_ACCENT if value == "Female" else "SystemButtonFace",
                                   fg="white" if value == "Female" else "black",
                                   relief="sunken" if value == "Female" else "raised")

    # ---- account-number lookup, same pattern as the Wage Entry form ----
    def _on_account_typing(self):
        acc = self.acc.get()
        if not acc:
            self.status_var.set("")
            return
        if acc == self._loaded_member_id:
            return
        if self.project.get_master(acc):
            self.status_var.set("Press Tab or Enter to load this employee's record.")
        else:
            self.status_var.set("New account number - press Tab or Enter, then fill in the details.")

    def _on_account_tab(self):
        acc = self.acc.get().strip()
        if not acc or acc == self._loaded_member_id:
            return
        records = self._records()
        match_idx = next((i for i, m in enumerate(records) if m.member_id == acc), None)
        if match_idx is not None:
            self._load_index(match_idx)
            return
        # not found -- switch to a fresh record for this account number
        self.index = len(records)
        self.sl.set(self.project.next_serial_no())
        self.uan.set("")
        self.name.set("")
        self.father.set("")
        self.dob.set("")
        self.doj.set("")
        self.doe.set("")
        self.reason_var.set("")
        self._select_sex("")
        self.higher_ee_var.set(False)
        self.higher_er_var.set(False)
        self.status_var.set("New account number - enter the details and click Save.")
        self._loaded_member_id = acc
        self._update_nav_label()
        self._update_age_warning()

    # ---- date validation -------------------------------------------------
    @staticmethod
    def _valid_date(text):
        text = (text or "").strip()
        if not text:
            return True  # optional field
        try:
            datetime.strptime(text, "%d/%m/%Y")
            return True
        except ValueError:
            return False

    # ---- save / delete / close --------------------------------------------
    def _save(self):
        acc = self.acc.get()
        name = self.name.get()
        if not acc or not name:
            messagebox.showerror("Missing Information", "Member ID and Employee Name are required.",
                                  parent=self)
            return
        if not self._valid_date(self.dob.get()):
            messagebox.showerror("Invalid Date", "Date of Birth must be in DD/MM/YYYY format.", parent=self)
            return
        if not self._valid_date(self.doj.get()):
            messagebox.showerror("Invalid Date", "Date of Joining must be in DD/MM/YYYY format.", parent=self)
            return
        if not self._valid_date(self.doe.get()):
            messagebox.showerror("Invalid Date", "Date of Exit must be in DD/MM/YYYY format.", parent=self)
            return
        sl_text = self.sl.get().strip()
        try:
            sl_value = int(sl_text) if sl_text else self.project.next_serial_no()
        except ValueError:
            messagebox.showerror("Invalid SL No.", "SL No. must be a whole number.", parent=self)
            return

        was_new_record = self.index >= len(self._records())
        if was_new_record and self.project.get_master(acc):
            messagebox.showerror("Duplicate Member ID",
                                  f"Member ID {acc} already exists in the Employee Master. "
                                  f"Use Previous/Next to find and edit it instead.", parent=self)
            return

        # Protect wage data: if the account number was changed (e.g. a UAN
        # was moved into the Member ID field), migrate all linked wage
        # entries across every year to the new account number.
        if (not was_new_record and self._original_member_id
                and self._original_member_id != acc):
            if self.project.get_master(acc):
                messagebox.showerror("Member ID Conflict",
                    f"Member ID '{acc}' already exists in the Employee Master.\n"
                    f"Cannot rename '{self._original_member_id}' to an existing account number.",
                    parent=self)
                return
            self.project.rename_account(self._original_member_id, acc)

        self.project.upsert_master(acc, name, father_name=self.father.get(), uan=self.uan.get().strip(),
                                    dob=self.dob.get().strip(), sex=self.sex_var.get(),
                                    doj=self.doj.get().strip(), doe=self.doe.get().strip(),
                                    reason_leaving=self.reason_var.get(), serial_no=sl_value,
                                    higher_epf_ee=self.higher_ee_var.get(),
                                    higher_epf_er=self.higher_er_var.get())

        # keep the main window's lists in sync live, without closing this form
        self.app._refresh_master_list()
        self.app._refresh_entries_list()
        self.app._set_status(f"Saved Employee Master record for {acc}.")
        self._refresh_embedded_list()

        # Always move forward after saving -- never leave the just-saved
        # record sitting on screen. Go to the next record in the (naturally
        # sorted) list if there is one, otherwise open a fresh blank record.
        records_after = self._records()
        saved_idx = next((i for i, m in enumerate(records_after) if m.member_id == acc), None)
        if saved_idx is not None and saved_idx + 1 < len(records_after):
            self._load_index(saved_idx + 1)
        else:
            self._load_index(len(records_after))

    def _delete_current(self):
        records = self._records()
        if not (0 <= self.index < len(records)):
            messagebox.showinfo("Nothing to Delete", "This is a new, unsaved record.", parent=self)
            return
        m = records[self.index]
        if not messagebox.askyesno("Confirm Delete",
                                    f"Delete '{m.name}' ({m.member_id}) from the Employee Master?\n\n"
                                    f"Note: this does not remove any wage entries already saved "
                                    f"for this account number in individual years.", parent=self):
            return
        self.project.remove_master(m.member_id)
        self.app._refresh_master_list()
        self.app._set_status(f"Deleted from Employee Master: {m.name}")
        new_total = len(self._records())
        self._load_index(min(self.index, new_total))
        self._refresh_embedded_list()

    def _close(self):
        self.app._refresh_master_list()
        self.destroy()


# ---------------------------------------------------------------------------
# Year dialog (Year From / To + rates -- one YearRecord)
# ---------------------------------------------------------------------------
class YearDialog(tk.Toplevel):
    """
    Add/Edit Year dialog. Presents TWO SEPARATE data-entry forms, switched by
    a scheme toggle at the top:

      - "Up to 1996-97"       -- the original EPF + FPF form (same rate
                                  applies to worker and employer).
      - "1997-98 onwards"     -- the post-1997 form: worker's EPF rate
                                  (all 12% goes to EPF), and employer's EPF
                                  portion (3.67%) + Pension Fund/EPS portion
                                  (8.33%) entered separately.
    """

    def __init__(self, master, year_from="", year_to="",
                 scheme=SCHEME_PRE_1997, epf_rate=6.84, fpf_rate=1.16,
                 emp_epf_rate=12.0, er_epf_rate=3.67, er_eps_rate=8.33,
                 editing=False):
        super().__init__(master)
        self.title("Edit Year" if editing else "Add New Year")
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.result = None
        self.grab_set()

        outer = ttk.Frame(self, padding=16, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        row = ttk.Frame(outer, style="Card.TFrame")
        row.pack(fill="x")
        self.f_from = LabeledEntry(row, "Year From (e.g. 1988)", width=16)
        self.f_from.pack(side="left", padx=(0, 10))
        self.f_from.set(year_from)
        self._year_to_user_edited = False
        if editing:
            self.f_from.entry.configure(state="disabled")
        else:
            self.f_from.entry.bind("<FocusOut>", lambda e: self._on_year_from_changed())
            self.f_from.entry.bind("<Return>", lambda e: self._on_year_from_changed())
        self.f_to = LabeledEntry(row, "Year To (e.g. 1989)", width=16)
        self.f_to.pack(side="left")
        self.f_to.set(year_to)
        if editing:
            self.f_to.entry.configure(state="disabled")
        else:
            # If the person types directly into Year To themselves, stop
            # auto-filling it so we never clobber a deliberate override.
            self.f_to.entry.bind("<KeyRelease>", lambda e: setattr(self, "_year_to_user_edited", True))

        # ---- scheme toggle ----
        ttk.Label(outer, text="Contribution Scheme", font=FONT_SECTION,
                  style="Card.TLabel").pack(anchor="w", pady=(14, 4))
        self.scheme_var = tk.StringVar(value=scheme)
        scheme_row = ttk.Frame(outer, style="Card.TFrame")
        scheme_row.pack(fill="x")
        ttk.Radiobutton(scheme_row, text="Up to 1996-97  (EPF + FPF, same rate both sides)",
                        variable=self.scheme_var, value=SCHEME_PRE_1997,
                        command=self._on_scheme_change).pack(anchor="w")
        ttk.Radiobutton(scheme_row, text="1997-98 onwards  (Worker EPF 12%  |  Employer EPF 3.67% + Pension Fund 8.33%)",
                        variable=self.scheme_var, value=SCHEME_POST_1997,
                        command=self._on_scheme_change).pack(anchor="w")

        # ---- form 1: pre-1997 rates ----
        self.pre_frame = ttk.Frame(outer, style="Card.TFrame")
        self.f_epf = LabeledEntry(self.pre_frame, "EPF Rate % (Worker & Employer)", width=20)
        self.f_epf.pack(side="left", padx=(0, 10))
        self.f_epf.set(epf_rate)
        self.f_fpf = LabeledEntry(self.pre_frame, "FPF Rate % (Worker & Employer)", width=20)
        self.f_fpf.pack(side="left")
        self.f_fpf.set(fpf_rate)

        # ---- form 2: post-1997 rates ----
        self.post_frame = ttk.Frame(outer, style="Card.TFrame")
        self.f_emp_epf = LabeledEntry(self.post_frame, "Worker's EPF Rate % (all to EPF)", width=20)
        self.f_emp_epf.pack(side="left", padx=(0, 10))
        self.f_emp_epf.set(emp_epf_rate)
        self.f_er_epf = LabeledEntry(self.post_frame, "Employer's EPF Rate %", width=18)
        self.f_er_epf.pack(side="left", padx=(0, 10))
        self.f_er_epf.set(er_epf_rate)
        self.f_er_eps = LabeledEntry(self.post_frame, "Employer's Pension Fund (EPS) Rate %", width=24)
        self.f_er_eps.pack(side="left")
        self.f_er_eps.set(er_eps_rate)

        self._on_scheme_change()  # show the correct form right away

        btns = ttk.Frame(outer, style="Card.TFrame")
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save).pack(side="right")

    def _on_year_from_changed(self):
        """If adding a brand-new year: (1) default the scheme toggle based on
        the Year From value (1997 onwards -> post-1997), and (2) auto-fill
        Year To as Year From + 1 (e.g. 2010 -> 2011) to save re-typing it --
        unless the person has already typed something into Year To themselves.
        Works the same way for both pre-1997 and post-1997 years."""
        yf = self.f_from.get().strip()
        if not yf:
            return
        try:
            yf_int = int(yf[:4])
        except ValueError:
            return
        self.scheme_var.set(SCHEME_POST_1997 if yf_int >= 1997 else SCHEME_PRE_1997)
        self._on_scheme_change()
        if not self._year_to_user_edited:
            self.f_to.set(str(yf_int + 1))

    def _on_scheme_change(self):
        if self.scheme_var.get() == SCHEME_POST_1997:
            self.pre_frame.pack_forget()
            self.post_frame.pack(fill="x", pady=(10, 0))
        else:
            self.post_frame.pack_forget()
            self.pre_frame.pack(fill="x", pady=(10, 0))

    def _save(self):
        yf, yt = self.f_from.get(), self.f_to.get()
        if not yf or not yt:
            messagebox.showerror("Missing Information", "Year From and Year To are required.", parent=self)
            return
        scheme = self.scheme_var.get()
        try:
            epf_rate = float(self.f_epf.get() or 6.84)
            fpf_rate = float(self.f_fpf.get() or 1.16)
            emp_epf_rate = float(self.f_emp_epf.get() or 12.0)
            er_epf_rate = float(self.f_er_epf.get() or 3.67)
            er_eps_rate = float(self.f_er_eps.get() or 8.33)
        except ValueError:
            messagebox.showerror("Invalid Rate", "All rate fields must be numbers.", parent=self)
            return
        self.result = (yf, yt, scheme, epf_rate, fpf_rate, emp_epf_rate, er_epf_rate, er_eps_rate)
        self.destroy()


# ---------------------------------------------------------------------------
# Wage entry dialog -- styled like the real Form 3A monthly table.
# This form STAYS OPEN after Save, so many employees can be entered one
# after another, and includes First/Previous/Next/Last record navigation
# (with the record number shown in the middle) so already-saved entries
# can be reviewed or corrected without reopening the dialog.
# ---------------------------------------------------------------------------
class WageEntryDialog(tk.Toplevel):
    COL_WIDTHS = [8, 12, 13, 12, 13, 13, 12, 13]

    def __init__(self, app, project: Project, year_key, start_index=None):
        """
        app         -- the main EPFApp window (used to refresh its lists live
                        as each record is saved, and as the Tk parent)
        start_index -- which record (0-based, into yr.entries) to open on.
                        None (default) opens a brand-new blank record ready
                        for the next employee to be typed in.
        """
        super().__init__(app)
        self.title("Employee Wage Entry (Form 3A style)")
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.app = app
        self.project = project
        self.year_key = year_key
        self.grab_set()

        yr = project.years[year_key]
        self.COLS = ["Month", "Wages", "EPF (Worker)", f"{yr.eps_label} (Worker)", "Total (Worker)",
                     "EPF (Employer)", f"{yr.eps_label} (Employer)", "Total (Employer)"]

        outer = ttk.Frame(self, padding=16, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=f"Year: {yr.long_label}   |   {yr.statutory_rate_text}",
                  font=("Segoe UI", 9, "italic"), style="Card.TLabel",
                  foreground="#555").pack(anchor="w", pady=(0, 10))

        # ---- identity row: Member ID (auto-lookup) + Name + Father's Name ----
        idf = ttk.Frame(outer, style="Card.TFrame")
        idf.pack(fill="x", pady=(0, 6))

        self.acc_entry = LabeledEntry(idf, "Member ID", width=22)
        self.acc_entry.pack(side="left", padx=(0, 12))
        self.name_entry = LabeledEntry(idf, "Employee Name", width=28)
        self.name_entry.pack(side="left", padx=(0, 12))
        self.father_entry = LabeledEntry(idf, "Father's Name (optional)", width=24)
        self.father_entry.pack(side="left")

        self.status_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.status_var, font=("Segoe UI", 9, "italic"),
                  style="Card.TLabel", foreground=COLOR_ACCENT).pack(anchor="w", pady=(0, 10))

        self.acc_entry.entry.bind("<KeyRelease>", lambda e: self._on_account_typing())
        self.acc_entry.entry.bind("<FocusOut>", lambda e: self._on_account_tab())
        self.acc_entry.entry.bind("<Return>", lambda e: self._on_account_tab())

        # ---- wages table, styled like the Form 3A card ----
        ttk.Label(outer, text="Monthly Wages & Contributions", font=FONT_SECTION,
                  style="Card.TLabel").pack(anchor="w", pady=(4, 6))

        table = tk.Frame(outer, bg="#B7C6DA")  # thin grid-line colour showing through the gaps
        table.pack(fill="x")

        for c, (h, w) in enumerate(zip(self.COLS, self.COL_WIDTHS)):
            cell = tk.Label(table, text=h, font=("Segoe UI", 9, "bold"), bg=COLOR_TABLE_HEAD,
                             width=w, anchor="center", padx=2, pady=4)
            cell.grid(row=0, column=c, sticky="nsew", padx=1, pady=1)

        self.wage_vars = []
        self.calc_labels = []
        for i, m in enumerate(MONTHS):
            r = i + 1
            tk.Label(table, text=m, font=FONT_LABEL, bg="white", width=self.COL_WIDTHS[0],
                     anchor="center", padx=2, pady=3).grid(row=r, column=0, sticky="nsew", padx=1, pady=1)

            var = tk.StringVar(value="0")
            ent = tk.Entry(table, textvariable=var, width=self.COL_WIDTHS[1], font=FONT_ENTRY,
                           justify="right", relief="flat", highlightthickness=1,
                           highlightbackground="#B7C6DA")
            ent.grid(row=r, column=1, sticky="nsew", padx=1, pady=1)
            ent.bind("<KeyRelease>", lambda e: self._recalculate())
            self.wage_vars.append(var)

            row_labels = {}
            for c, key in enumerate(["epf_w", "fpf_w", "tot_w", "epf_e", "fpf_e", "tot_e"], start=2):
                lbl = tk.Label(table, text="0", font=FONT_LABEL, bg="white", width=self.COL_WIDTHS[c],
                               anchor="e", padx=4, pady=3)
                lbl.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
                row_labels[key] = lbl
            self.calc_labels.append(row_labels)

        total_row = len(MONTHS) + 1
        tk.Label(table, text="TOTAL", font=("Segoe UI", 9, "bold"), bg=COLOR_TABLE_HEAD,
                 width=self.COL_WIDTHS[0], anchor="center", padx=2, pady=4).grid(
            row=total_row, column=0, sticky="nsew", padx=1, pady=1)
        self.total_labels = {}
        for c, key in enumerate(["wages", "epf_w", "fpf_w", "tot_w", "epf_e", "fpf_e", "tot_e"], start=1):
            lbl = tk.Label(table, text="0", font=("Segoe UI", 9, "bold"), bg=COLOR_TABLE_HEAD,
                           width=self.COL_WIDTHS[c], anchor="e", padx=4, pady=4)
            lbl.grid(row=total_row, column=c, sticky="nsew", padx=1, pady=1)
            self.total_labels[key] = lbl

        # ---- Save / Delete / Close buttons ----
        btns = ttk.Frame(outer, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Close", command=self._close).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(btns, text="Delete This Record", command=self._delete_current
                   ).pack(side="left")

        # ---- navigation bar: First / Prev / SL no. / Next / Last ----
        nav = ttk.Frame(outer, style="Card.TFrame")
        nav.pack(fill="x", pady=(10, 0))
        ttk.Button(nav, text="<< First", command=self._go_first).pack(side="left")
        ttk.Button(nav, text="< Previous", command=self._go_prev).pack(side="left", padx=(6, 0))
        self.nav_label_var = tk.StringVar(value="")
        ttk.Label(nav, textvariable=self.nav_label_var, font=("Segoe UI", 10, "bold"),
                  style="Card.TLabel", anchor="center").pack(side="left", expand=True, fill="x")
        ttk.Button(nav, text="Next >", command=self._go_next).pack(side="right", padx=(0, 6))
        ttk.Button(nav, text="Last >>", command=self._go_last).pack(side="right")

        self.index = start_index if start_index is not None else len(yr.entries)
        self._load_index(self.index)

    # ---- record navigation ---------------------------------------------
    def _entries(self):
        return self.project.years[self.year_key].entries

    def _go_first(self):
        if self._entries():
            self._load_index(0)

    def _go_prev(self):
        if self.index > 0:
            self._load_index(self.index - 1)

    def _go_next(self):
        entries = self._entries()
        if self.index < len(entries):
            self._load_index(self.index + 1)

    def _go_last(self):
        entries = self._entries()
        if entries:
            self._load_index(len(entries) - 1)

    def _load_index(self, idx):
        entries = self._entries()
        self.index = idx
        if 0 <= idx < len(entries):
            e = entries[idx]
            m = self.project.get_master(e.member_id)
            self.acc_entry.set(e.member_id)
            self.name_entry.set(m.name if m else "")
            self.father_entry.set(m.father_name if m else "")
            self.status_var.set("Existing employee (from Employee Master). Type a different "
                                 "Member ID and press Tab to jump to that employee.")
            self._set_wages(e.wages)
        else:
            # a fresh, blank record ready for a new employee
            self.acc_entry.set("")
            self.name_entry.set("")
            self.father_entry.set("")
            self.status_var.set("")
            self._set_wages([0] * 12)
        self._loaded_member_id = self.acc_entry.get()  # tracks what was last loaded/searched
        self._update_nav_label()
        self._recalculate()
        self.acc_entry.entry.focus_set()

    def _update_nav_label(self):
        total = len(self._entries())
        if self.index < total:
            self.nav_label_var.set(f"Record {self.index + 1} of {total}")
        else:
            self.nav_label_var.set(f"New Record (will be {total + 1} of {total + 1})")

    # ---- wages helpers ----------------------------------------------------
    def _set_wages(self, wages):
        for v, w in zip(self.wage_vars, wages):
            v.set(str(w) if w else "0")

    def _get_wages(self):
        return [to_float(v.get()) for v in self.wage_vars]

    def _on_account_typing(self):
        # Light-touch live hint only -- does NOT jump records or touch wages,
        # so it's safe to fire on every keystroke. The real search/jump
        # happens on Tab / Enter, in _on_account_tab().
        acc = self.acc_entry.get()
        if not acc:
            self.status_var.set("")
            return
        if acc == self._loaded_member_id:
            return  # unchanged from what's already loaded -- nothing new to hint
        if self.project.get_master(acc):
            self.status_var.set("Press Tab or Enter to load this employee's record.")
        else:
            self.status_var.set("New account number - press Tab or Enter, then enter the name "
                                 "and wages.")

    def _on_account_tab(self):
        acc = self.acc_entry.get().strip()
        if not acc or acc == self._loaded_member_id:
            return  # nothing changed -- don't disturb the currently loaded record
        entries = self._entries()
        match_idx = next((i for i, e in enumerate(entries) if e.member_id == acc), None)
        if match_idx is not None:
            # Found this account's wage entry for this year -- jump straight to it.
            self._load_index(match_idx)
            return
        # Not found in this year yet -- switch to a fresh record for this account
        # number (never silently overwrite/rename whatever record was showing).
        self.index = len(entries)
        m = self.project.get_master(acc)
        if m:
            self.name_entry.set(m.name)
            self.father_entry.set(m.father_name)
            self.status_var.set("Employee found in Employee Master but has no wages yet for "
                                 "this year - enter wages below and Save to add them.")
        else:
            self.name_entry.set("")
            self.father_entry.set("")
            self.status_var.set("New account number - enter the name; it will be added to the "
                                 "Employee Master.")
        self._set_wages([0] * 12)
        self._loaded_member_id = acc
        self._update_nav_label()
        self._recalculate()

    def _recalculate(self):
        yr = self.project.years[self.year_key]
        w_epf_rate, w_eps_rate = yr.worker_epf_rate, yr.worker_eps_rate
        e_epf_rate, e_eps_rate = yr.employer_epf_rate, yr.employer_eps_rate
        wages = self._get_wages()
        totals = {"wages": 0, "epf_w": 0, "fpf_w": 0, "tot_w": 0, "epf_e": 0, "fpf_e": 0, "tot_e": 0}
        for i, w in enumerate(wages):
            epf_w = round(w * w_epf_rate / 100)
            eps_w = round(w * w_eps_rate / 100)
            tot_w = epf_w + eps_w
            epf_e = round(w * e_epf_rate / 100)
            eps_e = round(w * e_eps_rate / 100)
            tot_e = epf_e + eps_e
            labels = self.calc_labels[i]
            labels["epf_w"].configure(text=currency(epf_w))
            labels["fpf_w"].configure(text=currency(eps_w))
            labels["tot_w"].configure(text=currency(tot_w))
            labels["epf_e"].configure(text=currency(epf_e))
            labels["fpf_e"].configure(text=currency(eps_e))
            labels["tot_e"].configure(text=currency(tot_e))
            totals["wages"] += w
            totals["epf_w"] += epf_w
            totals["fpf_w"] += eps_w
            totals["tot_w"] += tot_w
            totals["epf_e"] += epf_e
            totals["fpf_e"] += eps_e
            totals["tot_e"] += tot_e
        for key, lbl in self.total_labels.items():
            lbl.configure(text=currency(totals[key]))

    # ---- save / delete / close --------------------------------------------
    def _save(self):
        acc = self.acc_entry.get()
        name = self.name_entry.get()
        if not acc or not name:
            messagebox.showerror("Missing Information", "Member ID and Employee Name are required.",
                                  parent=self)
            return
        was_new_record = self.index >= len(self._entries())
        self.project.upsert_master(acc, name, self.father_entry.get())
        self.project.upsert_entry(self.year_key, acc, self._get_wages())

        # keep the main window's lists in sync live, without closing this form
        self.app._refresh_master_list()
        self.app._refresh_entries_list()
        self.app._update_year_info()
        self.app._set_status(f"Saved wage entry for {acc}.")

        if was_new_record:
            # move straight on to the next blank record so many employees
            # can be entered back-to-back without reopening this form
            self._load_index(len(self._entries()))
        else:
            # stay on the same (now-updated) record
            self._load_index(self.index)

    def _delete_current(self):
        entries = self._entries()
        if not (0 <= self.index < len(entries)):
            messagebox.showinfo("Nothing to Delete", "This is a new, unsaved record.", parent=self)
            return
        acc = entries[self.index].member_id
        if not messagebox.askyesno("Confirm Delete", f"Delete this year's wage entry for {acc}?",
                                    parent=self):
            return
        self.project.remove_entry(self.year_key, self.index)
        self.app._refresh_entries_list()
        self.app._update_year_info()
        self.app._set_status(f"Deleted wage entry for {acc}.")
        new_total = len(self._entries())
        self._load_index(min(self.index, new_total))

    def _close(self):
        self.app._refresh_entries_list()
        self.destroy()


# ---------------------------------------------------------------------------
# Year-range batch export dialog (Form 3A + Form 6A, Excel and/or PDF, for
# every year between two chosen years -- e.g. 1997-98 through 2014-15)
# ---------------------------------------------------------------------------
class YearRangeExportDialog(tk.Toplevel):
    def __init__(self, app, project: Project):
        super().__init__(app)
        self.title("Generate Reports for a Range of Years")
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.app = app
        self.project = project
        self.grab_set()

        outer = ttk.Frame(self, padding=16, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        self.year_keys = sorted(project.years.keys(),
                                 key=lambda k: natural_sort_key(project.years[k].year_from))

        if not self.year_keys:
            ttk.Label(outer, text="No years have been added to this project yet.\n"
                                   "Use '+ New Year' first.", style="Card.TLabel",
                      justify="center").pack(pady=10)
            ttk.Button(outer, text="Close", command=self.destroy).pack()
            return

        self.label_to_key = {project.years[k].long_label: k for k in self.year_keys}
        labels = [project.years[k].long_label for k in self.year_keys]

        ttk.Label(outer, text="Generates one Excel file (and, if selected, one matching PDF) "
                               "per year -- each containing that year's Form 3A + Form 6A.",
                  style="Card.TLabel", wraplength=420, justify="left").pack(anchor="w")

        range_row = ttk.Frame(outer, style="Card.TFrame")
        range_row.pack(fill="x", pady=(14, 0))
        from_box = ttk.Frame(range_row, style="Card.TFrame")
        from_box.pack(side="left", padx=(0, 16))
        ttk.Label(from_box, text="From Year", font=FONT_LABEL, style="Card.TLabel").pack(anchor="w")
        self.from_var = tk.StringVar(value=labels[0])
        ttk.Combobox(from_box, textvariable=self.from_var, values=labels, state="readonly",
                     width=14, font=FONT_ENTRY).pack(anchor="w", pady=(2, 0))

        to_box = ttk.Frame(range_row, style="Card.TFrame")
        to_box.pack(side="left")
        ttk.Label(to_box, text="To Year", font=FONT_LABEL, style="Card.TLabel").pack(anchor="w")
        self.to_var = tk.StringVar(value=labels[-1])
        ttk.Combobox(to_box, textvariable=self.to_var, values=labels, state="readonly",
                     width=14, font=FONT_ENTRY).pack(anchor="w", pady=(2, 0))

        opts_row = ttk.Frame(outer, style="Card.TFrame")
        opts_row.pack(fill="x", pady=(16, 0))
        self.excel_var = tk.BooleanVar(value=True)
        self.pdf_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts_row, text="Excel (.xlsx)", variable=self.excel_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(opts_row, text="PDF (.pdf)", variable=self.pdf_var).pack(side="left")
        ttk.Label(outer, text="PDF export needs Microsoft Excel installed on this PC (via the "
                               "'pywin32' package).", font=("Segoe UI", 8, "italic"),
                  style="Card.TLabel", foreground="#777").pack(anchor="w", pady=(2, 0))

        folder_box = ttk.Frame(outer, style="Card.TFrame")
        folder_box.pack(fill="x", pady=(14, 0))
        ttk.Label(folder_box, text="Output Folder", font=FONT_LABEL, style="Card.TLabel").pack(anchor="w")
        pick_row = ttk.Frame(folder_box, style="Card.TFrame")
        pick_row.pack(fill="x", pady=(2, 0))
        self.folder_var = tk.StringVar(value="")
        ttk.Entry(pick_row, textvariable=self.folder_var, width=44, font=FONT_ENTRY).pack(
            side="left", fill="x", expand=True)
        ttk.Button(pick_row, text="Browse...", command=self._pick_folder).pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.status_var, font=("Segoe UI", 9, "italic"),
                  style="Card.TLabel", foreground=COLOR_ACCENT, wraplength=420,
                  justify="left").pack(anchor="w", pady=(12, 0))

        btns = ttk.Frame(outer, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        self.close_btn = ttk.Button(btns, text="Close", command=self.destroy)
        self.close_btn.pack(side="right", padx=(6, 0))
        self.generate_btn = ttk.Button(btns, text="Generate", style="Accent.TButton",
                                        command=self._generate)
        self.generate_btn.pack(side="right")

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Choose Output Folder")
        if folder:
            self.folder_var.set(folder)

    def _progress(self, i, total, year_key):
        yr = self.project.years[year_key]
        self.status_var.set(f"Generating {i + 1} of {total}:  Year {yr.long_label} ...")
        self.update_idletasks()

    def _generate(self):
        make_excel = self.excel_var.get()
        make_pdf = self.pdf_var.get()
        if not make_excel and not make_pdf:
            messagebox.showerror("Nothing to Generate", "Please select Excel and/or PDF output.",
                                  parent=self)
            return
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Output Folder Needed", "Please choose an output folder.",
                                  parent=self)
            return
        from_key = self.label_to_key[self.from_var.get()]
        to_key = self.label_to_key[self.to_var.get()]

        self.generate_btn.configure(state="disabled")
        self.close_btn.configure(state="disabled")
        try:
            results = generate_forms_for_year_range(self.project, from_key, to_key, folder,
                                                      make_excel=make_excel, make_pdf=make_pdf,
                                                      progress_callback=self._progress)
        except Exception as e:
            done = getattr(e, "results", [])
            messagebox.showerror(
                "Generation Stopped",
                f"Generated {len(done)} year(s) before running into a problem:\n\n{e}\n\n"
                f"Files already written are still in:\n{folder}", parent=self)
            self.status_var.set(f"Stopped after {len(done)} year(s). See error above.")
            return
        finally:
            self.generate_btn.configure(state="normal")
            self.close_btn.configure(state="normal")

        self.status_var.set(f"Done -- generated {len(results)} year(s) into {folder}")
        self.app._set_status(f"Generated reports for {len(results)} year(s) into {folder}")
        if messagebox.askyesno("Generation Complete",
                                f"Generated {len(results)} year(s) of Form 3A + Form 6A into:\n{folder}\n\n"
                                f"Open the folder now?", parent=self):
            self.app._open_folder(folder)


# ---------------------------------------------------------------------------
# Form 5 (new joiners) / Form 10 (leavers) -- pick a month, generate the
# return for exactly that month, built from the Employee Master's Date of
# Joining / Date of Exit fields.
# ---------------------------------------------------------------------------
class MonthYearFormDialog(tk.Toplevel):
    def __init__(self, app, project: Project, form_kind: str):
        """form_kind: 'form5' or 'form10'."""
        super().__init__(app)
        self.app = app
        self.project = project
        self.form_kind = form_kind
        title = "Generate Form 5 (New Joiners)" if form_kind == "form5" else "Generate Form 10 (Leavers)"
        self.title(title)
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.grab_set()

        outer = ttk.Frame(self, padding=16, style="Card.TFrame")
        outer.pack(fill="both", expand=True)

        blurb = ("Lists every employee whose Date of Joining falls in the chosen month."
                 if form_kind == "form5" else
                 "Lists every employee whose Date of Exit falls in the chosen month.")
        ttk.Label(outer, text=blurb, style="Card.TLabel", wraplength=360,
                  justify="left").pack(anchor="w")

        row = ttk.Frame(outer, style="Card.TFrame")
        row.pack(fill="x", pady=(14, 0))
        month_box = ttk.Frame(row, style="Card.TFrame")
        month_box.pack(side="left", padx=(0, 16))
        ttk.Label(month_box, text="Month", font=FONT_LABEL, style="Card.TLabel").pack(anchor="w")
        today = datetime.now()
        self.month_var = tk.StringVar(value=MONTH_NAMES[today.month - 1])
        ttk.Combobox(month_box, textvariable=self.month_var, values=MONTH_NAMES, state="readonly",
                     width=14, font=FONT_ENTRY).pack(anchor="w", pady=(2, 0))

        year_box = ttk.Frame(row, style="Card.TFrame")
        year_box.pack(side="left")
        ttk.Label(year_box, text="Year", font=FONT_LABEL, style="Card.TLabel").pack(anchor="w")
        self.year_var = tk.StringVar(value=str(today.year))
        ttk.Entry(year_box, textvariable=self.year_var, width=10, font=FONT_ENTRY).pack(anchor="w", pady=(2, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.status_var, font=("Segoe UI", 9, "italic"),
                  style="Card.TLabel", foreground=COLOR_ACCENT, wraplength=360,
                  justify="left").pack(anchor="w", pady=(14, 0))

        btns = ttk.Frame(outer, style="Card.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Generate", style="Accent.TButton", command=self._generate).pack(side="right")

    def _generate(self):
        try:
            cal_year = int(self.year_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Year", "Please enter a valid year, e.g. 1997.", parent=self)
            return
        cal_month = MONTH_NAMES.index(self.month_var.get()) + 1

        path = filedialog.asksaveasfilename(
            title="Save As", defaultextension=".xlsx",
            initialfile=f"{'Form5' if self.form_kind == 'form5' else 'Form10'}_"
                        f"{self.month_var.get()}_{cal_year}.xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")])
        if not path:
            return

        if self.form_kind == "form5":
            _, matches = generate_form5_for_month(self.project, cal_year, cal_month, path)
        else:
            _, matches = generate_form10_for_month(self.project, cal_year, cal_month, path)

        if not matches:
            self.status_var.set(f"No matching employees found for {self.month_var.get()} {cal_year} -- "
                                 f"an empty form was still saved.")
        else:
            self.status_var.set(f"Found {len(matches)} employee(s). Saved to {os.path.basename(path)}.")
        self.app._set_status(f"Generated {'Form 5' if self.form_kind == 'form5' else 'Form 10'} "
                              f"for {self.month_var.get()} {cal_year}: {len(matches)} employee(s).")
        if messagebox.askyesno("Generation Complete", f"Saved to:\n{path}\n\nOpen it now?", parent=self):
            try:
                os.startfile(path)
            except Exception:
                pass




# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class EPFApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x820")
        self.configure(bg=COLOR_BG)
        self.minsize(1040, 680)

        self.project = Project()
        self.current_filepath = None

        self._setup_styles()
        self._build_menu()
        self._build_header()
        self._build_body()
        self._build_statusbar()

        self._refresh_establishment_fields()
        self._refresh_master_list()
        self._refresh_year_selector()
        self._refresh_entries_list()
        self._auto_load_project()

    # ------------------------------------------------------------ styling --
    def _setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_CARD)
        style.configure("Card.TLabel", background=COLOR_CARD, font=FONT_LABEL)
        style.configure("Header.TFrame", background=COLOR_HEADER)
        style.configure("Header.TLabel", background=COLOR_HEADER, foreground=COLOR_HEADER_TEXT,
                         font=FONT_TITLE)
        style.configure("SubHeader.TLabel", background=COLOR_HEADER, foreground="#CFE2F3",
                         font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=COLOR_BG, foreground=COLOR_HEADER,
                         font=FONT_SECTION)
        style.configure("TButton", font=FONT_LABEL, padding=6)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Accent.TButton",
                  background=[("!disabled", COLOR_ACCENT)],
                  foreground=[("!disabled", "white")])
        style.configure("Treeview", font=FONT_MONO, rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Status.TLabel", background="#DCE6F1", foreground="#1F4E78",
                         font=("Segoe UI", 9))
        style.configure("TCombobox", font=FONT_ENTRY)

    # ------------------------------------------------------------- header --
    def _build_header(self):
        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(fill="x")
        inner = ttk.Frame(header, style="Header.TFrame", padding=(20, 14))
        inner.pack(fill="x")
        ttk.Label(inner, text="EPF Form 3A / 6A Manager", style="Header.TLabel").pack(anchor="w")
        ttk.Label(inner, text="Establishment & Employee Master are entered once. Each year is kept "
                              "separate. Generate produces one Excel file for the year selected.",
                  style="SubHeader.TLabel").pack(anchor="w", pady=(2, 0))

    # --------------------------------------------------------------- menu --
    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project", command=self.new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Open Project...", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="Save Project", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="Save Project As...", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Generate Excel for Selected Year...", command=self.generate_excel,
                               accelerator="Ctrl+G")
        file_menu.add_command(label="Generate for a Range of Years (Excel + PDF)...",
                               command=self.generate_year_range)
        file_menu.add_separator()
        file_menu.add_command(label="Generate Form 9 (Employee Master Return)...",
                               command=self.generate_form9)
        file_menu.add_command(label="Generate Form 5 (New Joiners for a Month)...",
                               command=lambda: self.generate_month_form("form5"))
        file_menu.add_command(label="Generate Form 10 (Leavers for a Month)...",
                               command=lambda: self.generate_month_form("form10"))
        file_menu.add_separator()
        file_menu.add_command(label="Export All Data to Excel...", command=self.export_data_workbook)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)
        self.bind("<Control-n>", lambda e: self.new_project())
        self.bind("<Control-o>", lambda e: self.open_project())
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Control-g>", lambda e: self.generate_excel())

    # --------------------------------------------------------------- body --
    def _build_body(self):
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        # ============ (1) Establishment (entered once) ============
        ttk.Label(body, text="1. Establishment (entered once)", style="Section.TLabel"
                  ).pack(anchor="w", pady=(0, 6))
        est_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        est_card.pack(fill="x", pady=(0, 14))

        row1 = ttk.Frame(est_card, style="Card.TFrame")
        row1.pack(fill="x")
        self.f_code = LabeledEntry(row1, "Establishment Code", width=22)
        self.f_code.pack(side="left", padx=(0, 14))
        self.f_name = LabeledEntry(row1, "Establishment Name", width=30)
        self.f_name.pack(side="left", padx=(0, 14))
        self.f_address = LabeledEntry(row1, "Establishment Address", width=34)
        self.f_address.pack(side="left", padx=(0, 14))
        self.f_coverage_date = LabeledEntry(row1, "Coverage Date (DD/MM/YYYY)", width=20)
        self.f_coverage_date.pack(side="left", padx=(0, 14))
        ttk.Button(row1, text="Save Establishment Info", style="Accent.TButton",
                   command=self.save_establishment).pack(side="left", pady=(14, 0))

        # ============ (2) Employee Master (entered once per employee) ============
        ttk.Label(body, text="2. Employee Master / Form 9 (member id. + name -- entered once per employee)",
                  style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        master_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        master_card.pack(fill="x", pady=(0, 14))

        mtoolbar = ttk.Frame(master_card, style="Card.TFrame")
        mtoolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(mtoolbar, text="+ Add Employee to Master", style="Accent.TButton",
                   command=self.add_master_employee).pack(side="left")
        ttk.Button(mtoolbar, text="Edit Selected", command=self.edit_master_employee
                   ).pack(side="left", padx=6)
        ttk.Button(mtoolbar, text="Delete Selected", command=self.delete_master_employee
                   ).pack(side="left")

        mcols = ("sl", "acc", "uan", "name", "father", "dob", "age", "sex", "doj", "doe", "reason")
        self.master_tree = ttk.Treeview(master_card, columns=mcols, show="headings", height=5)
        mheadings = ["SL", "Member ID", "UAN No.", "Name", "Father's Name", "Date of Birth", "Age", "Sex",
                     "Date of Joining", "Date of Exit", "Reason of Leaving"]
        mwidths = [40, 120, 120, 200, 180, 100, 50, 60, 100, 100, 150]
        for c, h, w in zip(mcols, mheadings, mwidths):
            self.master_tree.heading(c, text=h)
            self.master_tree.column(c, width=w, anchor="w" if c in ("name", "father", "reason") else "center")
        self.master_tree.pack(fill="x")
        self.master_tree.bind("<Double-1>", lambda e: self.edit_master_employee())
        # Rows for employees at/past superannuation age (58) are highlighted
        self.master_tree.tag_configure("due_superannuation", background="#ffd9d9")

        # ============ (3) Year selector ============
        ttk.Label(body, text="3. Financial Year", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        year_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        year_card.pack(fill="x", pady=(0, 14))

        yrow = ttk.Frame(year_card, style="Card.TFrame")
        yrow.pack(fill="x")
        ttk.Label(yrow, text="Selected Year:", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.year_var = tk.StringVar()
        self.year_combo = ttk.Combobox(yrow, textvariable=self.year_var, state="readonly", width=14,
                                        font=FONT_ENTRY)
        self.year_combo.pack(side="left", padx=(0, 10))
        self.year_combo.bind("<<ComboboxSelected>>", lambda e: self._on_year_selected())
        ttk.Button(yrow, text="+ New Year", style="Accent.TButton",
                   command=self.add_year).pack(side="left", padx=(0, 6))
        ttk.Button(yrow, text="Edit Rates", command=self.edit_year_rates).pack(side="left", padx=(0, 6))
        ttk.Button(yrow, text="Delete Year", command=self.delete_year).pack(side="left")
        self.year_info_var = tk.StringVar(value="No year selected.")
        ttk.Label(yrow, textvariable=self.year_info_var, style="Card.TLabel",
                  foreground="#555").pack(side="left", padx=(16, 0))

        # ============ (4) Bulk Import Employee Wages from Excel ============
        ttk.Label(body, text="4. Bulk Import Employee Wages from Excel (optional, for large "
                              "establishments)", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        import_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        import_card.pack(fill="x", pady=(0, 14))

        irow = ttk.Frame(import_card, style="Card.TFrame")
        irow.pack(fill="x")
        ttk.Label(irow, text="Import into Year:", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.import_year_var = tk.StringVar()
        self.import_year_combo = ttk.Combobox(irow, textvariable=self.import_year_var, state="readonly",
                                               width=14, font=FONT_ENTRY)
        self.import_year_combo.pack(side="left", padx=(0, 14))

        self.import_file_path = None
        self.import_file_var = tk.StringVar(value="No file selected.")
        ttk.Button(irow, text="Browse Excel File...", command=self.browse_import_file
                   ).pack(side="left", padx=(0, 10))
        ttk.Label(irow, textvariable=self.import_file_var, style="Card.TLabel",
                  foreground="#555").pack(side="left", padx=(0, 14))
        ttk.Button(irow, text="Submit / Import", style="Accent.TButton",
                   command=self.do_bulk_import).pack(side="right")

        ttk.Label(import_card, text="Expected columns: SL, Member ID, Name, APR ... MAR (monthly "
                                     "wages), Total Wages. Column order/exact wording can vary a "
                                     "little; the file just needs a 'Member ID' and a 'Name' "
                                     "column, plus one column per month.",
                  style="Card.TLabel", foreground="#666", wraplength=1120, justify="left"
                  ).pack(anchor="w", pady=(8, 0))

        # ============ (5) Employee wage entries for selected year ============
        ttk.Label(body, text="5. Employee Wages for Selected Year", style="Section.TLabel"
                  ).pack(anchor="w", pady=(0, 6))
        emp_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        emp_card.pack(fill="both", expand=True)

        toolbar = ttk.Frame(emp_card, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="+ Add Employee Wages", style="Accent.TButton",
                   command=self.add_entry).pack(side="left")
        ttk.Button(toolbar, text="Edit Selected", command=self.edit_entry).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Delete Selected", command=self.delete_entry).pack(side="left")
        ttk.Label(toolbar, text="Tip: double-click a row to edit it.", style="Card.TLabel",
                  foreground="#666").pack(side="right")

        columns = ("sl", "acc", "uan", "name", "wages", "epf_e", "fpf_e", "tot_e", "epf_r", "fpf_r", "tot_r")
        headings = ["SL", "Member ID", "UAN No.", "Name", "Wages", "EPF (Worker)", "FPF (Worker)",
                    "Total (Worker)", "EPF (Employer)", "FPF (Employer)", "Total (Employer)"]
        widths = [40, 130, 120, 200, 90, 90, 90, 100, 90, 90, 100]

        tree_frame = ttk.Frame(emp_card, style="Card.TFrame")
        tree_frame.pack(fill="both", expand=True)
        self.emp_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=11)
        for c, h, w in zip(columns, headings, widths):
            self.emp_tree.heading(c, text=h)
            self.emp_tree.column(c, width=w, anchor="center" if c != "name" else "w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.emp_tree.yview)
        self.emp_tree.configure(yscrollcommand=vsb.set)
        self.emp_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.emp_tree.bind("<Double-1>", lambda e: self.edit_entry())
        self.emp_tree.tag_configure("odd", background=COLOR_ROW_ALT)
        self.emp_tree.tag_configure("total", background="#D9E1F2", font=("Consolas", 10, "bold"))

        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(14, 0))
        ttk.Button(bottom, text="Generate Form 3A + Form 6A Excel for Selected Year",
                   style="Accent.TButton", command=self.generate_excel).pack(side="right")
        ttk.Button(bottom, text="Generate for a Range of Years (Excel + PDF)...",
                   command=self.generate_year_range).pack(side="right", padx=(0, 8))

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Ready.")
        bar = ttk.Label(self, textvariable=self.status_var, style="Status.TLabel",
                         anchor="w", padding=(10, 4))
        bar.pack(fill="x", side="bottom")

    def _set_status(self, text):
        self.status_var.set(text)

    def _auto_load_project(self):
        """Auto-load a .epfproj.json project file if one exists in the same
        directory as this script, so the user sees their data immediately on
        startup without needing to File > Open first."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            candidates = sorted(f for f in os.listdir(script_dir)
                                if f.lower().endswith('.epfproj.json'))
        except OSError:
            return
        for fname in candidates:
            path = os.path.join(script_dir, fname)
            try:
                self.project.load(path)
                self.current_filepath = path
                self._refresh_establishment_fields()
                self._refresh_master_list()
                self._refresh_year_selector()
                self._refresh_entries_list()
                self._set_status(f"Auto-loaded project: {os.path.basename(path)}")
            except Exception:
                pass
            break

    # ---------------------------------------------------------- refreshes --
    def _refresh_establishment_fields(self):
        p = self.project
        self.f_code.set(p.code)
        self.f_name.set(p.name)
        self.f_address.set(p.address)
        self.f_coverage_date.set(p.coverage_date)

    def _refresh_master_list(self):
        for row in self.master_tree.get_children():
            self.master_tree.delete(row)
        for m in self.project.master_list():
            age = calc_age_years(m.dob)
            tags = ("due_superannuation",) if (age is not None and age >= SUPERANNUATION_AGE) else ()
            self.master_tree.insert("", "end", iid=m.member_id,
                                     values=(m.serial_no or "", m.member_id, m.uan, m.name, m.father_name,
                                             m.dob, age if age is not None else "", m.sex, m.doj,
                                             m.doe, m.reason_leaving),
                                     tags=tags)

    def _refresh_year_selector(self):
        keys = self.project.year_keys_sorted()
        self.year_combo["values"] = keys
        self.import_year_combo["values"] = keys
        if keys:
            if self.project.current_year_key not in keys:
                self.project.current_year_key = keys[0]
            self.year_var.set(self.project.current_year_key)
            if not self.import_year_var.get() or self.import_year_var.get() not in keys:
                self.import_year_var.set(self.project.current_year_key)
        else:
            self.year_var.set("")
            self.import_year_var.set("")
        self._update_year_info()

    def _update_year_info(self):
        yr = self.project.current_year()
        if yr:
            scheme_label = "Post-1997" if yr.is_post_1997 else "Pre-1997"
            self.year_info_var.set(f"[{scheme_label}]  {yr.statutory_rate_text}   "
                                    f"({len(yr.entries)} employee(s) entered)")
        else:
            self.year_info_var.set("No year selected. Click '+ New Year' to add one.")

    def _on_year_selected(self):
        self.project.current_year_key = self.year_var.get()
        self._update_year_info()
        self._refresh_entries_list()

    def _refresh_entries_list(self):
        for row in self.emp_tree.get_children():
            self.emp_tree.delete(row)
        yr = self.project.current_year()
        if not yr:
            self._set_status("No year selected.")
            return

        # Column headings reflect this year's scheme (FPF pre-1997, Pension Fund/EPS post-1997)
        heading_map = {"epf_e": "EPF (Worker)", "fpf_e": f"{yr.eps_label} (Worker)", "tot_e": "Total (Worker)",
                       "epf_r": "EPF (Employer)", "fpf_r": f"{yr.eps_label} (Employer)", "tot_r": "Total (Employer)"}
        for col, text in heading_map.items():
            self.emp_tree.heading(col, text=text)

        employees = self.project.build_employees_for_year(self.project.current_year_key)
        grand = [0, 0, 0, 0, 0, 0, 0]
        for i, emp in enumerate(employees, start=1):
            wt, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot = emp.annual_totals(
                yr.worker_epf_rate, yr.worker_eps_rate, yr.employer_epf_rate, yr.employer_eps_rate)
            tag = "odd" if i % 2 == 0 else ""
            self.emp_tree.insert("", "end", iid=emp.member_id,
                                  values=(i, emp.member_id, emp.uan, emp.name, currency(wt),
                                          currency(w_epf), currency(w_eps), currency(w_tot),
                                          currency(e_epf), currency(e_eps), currency(e_tot)),
                                  tags=(tag,))
            grand[0] += wt; grand[1] += w_epf; grand[2] += w_eps; grand[3] += w_tot
            grand[4] += e_epf; grand[5] += e_eps; grand[6] += e_tot
        if employees:
            self.emp_tree.insert("", "end", values=("", "", "", "GRAND TOTAL", currency(grand[0]),
                                                      currency(grand[1]), currency(grand[2]),
                                                      currency(grand[3]), currency(grand[4]),
                                                      currency(grand[5]), currency(grand[6])),
                                  tags=("total",))
        self._set_status(f"{len(employees)} employee(s) for year {yr.long_label}.")

    # ------------------------------------------------------- establishment --
    def save_establishment(self):
        code, name, address = self.f_code.get(), self.f_name.get(), self.f_address.get()
        coverage_date = self.f_coverage_date.get().strip()
        if not code or not name:
            messagebox.showerror("Missing Information", "Establishment Code and Name are required.")
            return
        if coverage_date:
            try:
                datetime.strptime(coverage_date, "%d/%m/%Y")
            except ValueError:
                messagebox.showerror("Invalid Date", "Coverage Date must be in DD/MM/YYYY format.")
                return
        self.project.set_establishment(code, name, address, coverage_date)
        self._set_status("Establishment info saved.")
        messagebox.showinfo("Saved", "Establishment details saved.")

    # ------------------------------------------------------- employee master
    def add_master_employee(self):
        dlg = MasterEmployeeDialog(self, self.project)  # opens on a blank record
        self.wait_window(dlg)
        self._refresh_master_list()  # safety-net refresh once the form is closed

    def edit_master_employee(self):
        sel = self.master_tree.selection()
        if not sel:
            messagebox.showinfo("Select an Employee", "Please select an employee row first.")
            return
        acc = sel[0]
        records = self.project.master_list()
        idx = next((i for i, m in enumerate(records) if m.member_id == acc), None)
        if idx is None:
            return
        dlg = MasterEmployeeDialog(self, self.project, start_index=idx)
        self.wait_window(dlg)
        self._refresh_master_list()

    def delete_master_employee(self):
        sel = self.master_tree.selection()
        if not sel:
            messagebox.showinfo("Select an Employee", "Please select an employee row first.")
            return
        acc = sel[0]
        m = self.project.get_master(acc)
        if messagebox.askyesno("Confirm Delete",
                                f"Delete '{m.name}' ({acc}) from the Employee Master?\n\n"
                                f"Note: this does not remove any wage entries already saved "
                                f"for this account number in individual years."):
            self.project.remove_master(acc)
            self._refresh_master_list()
            self._set_status(f"Deleted from Employee Master: {m.name}")

    # --------------------------------------------------------------- years --
    def add_year(self):
        dlg = YearDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            yf, yt, scheme, epf_rate, fpf_rate, emp_epf_rate, er_epf_rate, er_eps_rate = dlg.result
            key = f"{yf}-{yt[-2:]}"
            if key in self.project.years:
                messagebox.showerror("Year Already Exists",
                                      f"Year {key} has already been added. Select it from the "
                                      f"dropdown, or use 'Edit Rates' to change its rates.")
                return
            self.project.add_year(yf, yt, scheme, epf_rate, fpf_rate,
                                   emp_epf_rate, er_epf_rate, er_eps_rate)
            self._refresh_year_selector()
            self._refresh_entries_list()
            self._set_status(f"Added year {key}.")

    def edit_year_rates(self):
        yr = self.project.current_year()
        if not yr:
            messagebox.showinfo("No Year Selected", "Please add or select a year first.")
            return
        dlg = YearDialog(self, year_from=yr.year_from, year_to=yr.year_to,
                          scheme=yr.scheme, epf_rate=yr.epf_rate, fpf_rate=yr.fpf_rate,
                          emp_epf_rate=yr.emp_epf_rate, er_epf_rate=yr.er_epf_rate,
                          er_eps_rate=yr.er_eps_rate, editing=True)
        self.wait_window(dlg)
        if dlg.result:
            _, _, scheme, epf_rate, fpf_rate, emp_epf_rate, er_epf_rate, er_eps_rate = dlg.result
            self.project.update_year_rates(self.project.current_year_key, scheme, epf_rate, fpf_rate,
                                            emp_epf_rate, er_epf_rate, er_eps_rate)
            self._update_year_info()
            self._refresh_entries_list()
            self._set_status(f"Updated rates for {yr.long_label}.")

    def delete_year(self):
        yr = self.project.current_year()
        if not yr:
            messagebox.showinfo("No Year Selected", "Please select a year first.")
            return
        if messagebox.askyesno("Confirm Delete",
                                f"Delete year {yr.long_label} and all its wage entries?\n"
                                f"This cannot be undone."):
            self.project.remove_year(self.project.current_year_key)
            self._refresh_year_selector()
            self._refresh_entries_list()
            self._set_status(f"Deleted year {yr.long_label}.")

    # ------------------------------------------------------- bulk import ---
    def browse_import_file(self):
        path = filedialog.askopenfilename(title="Select Excel File to Import",
                                           filetypes=[("Excel files", "*.xlsx *.xls"),
                                                      ("All files", "*.*")])
        if path:
            self.import_file_path = path
            self.import_file_var.set(os.path.basename(path))

    def do_bulk_import(self):
        year_key = self.import_year_var.get()
        if not year_key:
            messagebox.showwarning("No Year Selected", "Please add a year (see section 3) and "
                                                         "select it here before importing.")
            return
        if not self.import_file_path:
            messagebox.showwarning("No File Selected", "Please browse to and select an Excel "
                                                         "file to import first.")
            return
        try:
            records, warnings = import_wages_from_excel(self.import_file_path)
        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not read the Excel file:\n{e}")
            return
        if not records:
            messagebox.showwarning("No Data Found", "No employee rows were found in the file. "
                                                      "Please check the column headings.")
            return

        for rec in records:
            self.project.upsert_master(rec["member_id"], rec["name"])
            self.project.upsert_entry(year_key, rec["member_id"], rec["wages"])

        self._refresh_master_list()
        if year_key == self.project.current_year_key:
            self._refresh_entries_list()
        self._update_year_info()

        msg = f"Imported {len(records)} employee record(s) into year {year_key}."
        if warnings:
            shown = warnings[:10]
            msg += f"\n\n{len(warnings)} note(s):\n" + "\n".join(shown)
            if len(warnings) > 10:
                msg += f"\n... and {len(warnings) - 10} more."
        messagebox.showinfo("Import Complete", msg)
        self._set_status(f"Imported {len(records)} record(s) into {year_key} from "
                          f"{os.path.basename(self.import_file_path)}.")

    # ------------------------------------------------------------ entries --
    def _ensure_year_ready(self):
        if not self.project.current_year():
            messagebox.showwarning("No Year Selected", "Please add and select a year first "
                                                         "(see section 3).")
            return False
        return True

    def add_entry(self):
        if not self._ensure_year_ready():
            return
        dlg = WageEntryDialog(self, self.project, self.project.current_year_key)  # opens on a blank record
        self.wait_window(dlg)
        self._refresh_entries_list()  # safety-net refresh once the form is closed

    def _selected_entry_account(self):
        sel = self.emp_tree.selection()
        if not sel:
            return None
        return sel[0]

    def edit_entry(self):
        if not self._ensure_year_ready():
            return
        acc = self._selected_entry_account()
        if not acc:
            messagebox.showinfo("Select an Employee", "Please select an employee row first.")
            return
        yr = self.project.current_year()
        idx = next((i for i, e in enumerate(yr.entries) if e.member_id == acc), None)
        if idx is None:
            return
        dlg = WageEntryDialog(self, self.project, self.project.current_year_key, start_index=idx)
        self.wait_window(dlg)
        self._refresh_entries_list()

    def delete_entry(self):
        if not self._ensure_year_ready():
            return
        acc = self._selected_entry_account()
        if not acc:
            messagebox.showinfo("Select an Employee", "Please select an employee row first.")
            return
        yr = self.project.current_year()
        idx = next((i for i, e in enumerate(yr.entries) if e.member_id == acc), None)
        if idx is None:
            return
        if messagebox.askyesno("Confirm Delete", f"Delete this year's wage entry for {acc}?"):
            self.project.remove_entry(self.project.current_year_key, idx)
            self._refresh_entries_list()
            self._update_year_info()
            self._set_status(f"Deleted wage entry for {acc}.")

    # --------------------------------------------------------- file / save --
    def new_project(self):
        if messagebox.askyesno("New Project", "Start a new project? Unsaved changes will be lost."):
            self.project.new()
            self.current_filepath = None
            self._refresh_establishment_fields()
            self._refresh_master_list()
            self._refresh_year_selector()
            self._refresh_entries_list()
            self._set_status("New project started.")

    def open_project(self):
        path = filedialog.askopenfilename(title="Open Project",
                                           filetypes=[("EPF Project", "*.epfproj.json"),
                                                      ("JSON files", "*.json"),
                                                      ("All files", "*.*")])
        if not path:
            return
        try:
            self.project.load(path)
        except Exception as e:
            messagebox.showerror("Open Failed", f"Could not open project:\n{e}")
            return
        self.current_filepath = path
        self._refresh_establishment_fields()
        self._refresh_master_list()
        self._refresh_year_selector()
        self._refresh_entries_list()
        self._set_status(f"Opened: {os.path.basename(path)}")

    def save_project(self):
        if not self.current_filepath:
            self.save_project_as()
            return
        self.project.save(self.current_filepath)
        companion = self._auto_export_data_workbook(self.current_filepath)
        if companion:
            self._set_status(f"Saved: {os.path.basename(self.current_filepath)}   |   "
                              f"Data copy updated: {os.path.basename(companion)}")
        else:
            self._set_status(f"Saved: {os.path.basename(self.current_filepath)}")

    def save_project_as(self):
        default_name = f"{self.project.name or 'EPF'}_project.epfproj.json"
        path = filedialog.asksaveasfilename(title="Save Project As", defaultextension=".json",
                                             initialfile=default_name,
                                             filetypes=[("EPF Project", "*.epfproj.json"),
                                                        ("JSON files", "*.json")])
        if not path:
            return
        self.project.save(path)
        self.current_filepath = path
        companion = self._auto_export_data_workbook(path)
        if companion:
            self._set_status(f"Saved: {os.path.basename(path)}   |   "
                              f"Data copy updated: {os.path.basename(companion)}")
        else:
            self._set_status(f"Saved: {os.path.basename(path)}")

    def _companion_data_workbook_path(self, project_filepath):
        """Same folder/base name as the project file, but '<name>_data.xlsx'
        instead of '<name>.epfproj.json'."""
        base = project_filepath
        for suffix in (".epfproj.json", ".json"):
            if base.lower().endswith(suffix):
                base = base[:-len(suffix)]
                break
        else:
            base = os.path.splitext(base)[0]
        return base + "_data.xlsx"

    def _auto_export_data_workbook(self, project_filepath):
        """
        Keeps a plain, always-current Excel copy of the whole project (Employee
        Master + every year's wages) sitting right next to the .epfproj.json
        file, so there's always something you can open directly in Excel to
        view or copy from for official purposes -- no separate export step
        needed. This is a convenience mirror; the .epfproj.json remains the
        real source of truth the app reads from.
        """
        try:
            companion = self._companion_data_workbook_path(project_filepath)
            self.project.export_data_workbook(companion)
            return companion
        except Exception as e:
            # Non-fatal -- e.g. the workbook is open in Excel and locked.
            # The project JSON has already been saved successfully above.
            self._set_status(f"Project saved, but could not refresh the Excel data copy "
                              f"(is it open in Excel?): {e}")
            return None

    def export_data_workbook(self):
        """File menu: on-demand export of all data to a chosen Excel file."""
        default_name = f"{self.project.name or 'EPF'}_data.xlsx"
        path = filedialog.asksaveasfilename(title="Export All Data to Excel", defaultextension=".xlsx",
                                             initialfile=default_name,
                                             filetypes=[("Excel Workbook", "*.xlsx")])
        if not path:
            return
        try:
            self.project.export_data_workbook(path)
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export data:\n{e}\n\n"
                                                    f"(If the file is already open in Excel, close it and try again.)")
            return
        self._set_status(f"Exported all data to: {os.path.basename(path)}")
        if messagebox.askyesno("Export Complete", f"Data exported to:\n{path}\n\nOpen it now?"):
            try:
                os.startfile(path)
            except Exception:
                pass

    # -------------------------------------------------------------- export --
    def generate_excel(self):
        if not self._ensure_year_ready():
            return
        if not self.project.code or not self.project.name:
            messagebox.showwarning("Establishment Info Needed",
                                    "Please fill in and save the Establishment details first "
                                    "(see section 1).")
            return
        yr = self.project.current_year()
        if not yr.entries:
            messagebox.showwarning("No Employees", "Please add at least one employee's wages for "
                                                     "this year before generating the Excel file.")
            return
        key = self.project.current_year_key
        est = self.project.build_establishment_for_year(key)
        employees = self.project.build_employees_for_year(key)

        default_name = f"{self.project.name.replace(' ', '_')}_{est.long_year_label}.xlsx"
        path = filedialog.asksaveasfilename(title="Save Excel File", defaultextension=".xlsx",
                                             initialfile=default_name,
                                             filetypes=[("Excel Workbook", "*.xlsx")])
        if not path:
            return
        try:
            gen = ExcelGenerator(est, employees, project=self.project)
            gen.build(path)
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not generate the Excel file:\n{e}")
            return
        self._set_status(f"Excel file generated: {os.path.basename(path)}")
        if messagebox.askyesno("Success", f"Excel file generated for {est.long_year_label} only:\n"
                                           f"{path}\n\n"
                                           f"Sheets created:\n"
                                           f"  3A_{est.short_year_label}  (Form 3A cards)\n"
                                           f"  6A_{est.short_year_label}  (Form 6A summary)\n"
                                           f"  12A_{est.short_year_label}  (Form 12A monthly statement)\n"
                                           f"  Form 9  (Employee Master return)\n"
                                           f"  F5_APR .. F5_MAR  (Form 5, one sheet per month)\n"
                                           f"  F10_APR .. F10_MAR  (Form 10, one sheet per month)\n\n"
                                           f"Open the containing folder now?"):
            self._open_folder(os.path.dirname(os.path.abspath(path)))

    def generate_year_range(self):
        if not self.project.code or not self.project.name:
            messagebox.showwarning("Establishment Info Needed",
                                    "Please fill in and save the Establishment details first "
                                    "(see section 1).")
            return
        if not self.project.years:
            messagebox.showinfo("No Years Yet", "Please add at least one year first "
                                                  "(see '+ New Year').")
            return
        YearRangeExportDialog(self, self.project)

    def generate_form9(self):
        if not self.project.code or not self.project.name:
            messagebox.showwarning("Establishment Info Needed",
                                    "Please fill in and save the Establishment details first "
                                    "(see section 1).")
            return
        if not self.project.master:
            messagebox.showinfo("No Employees Yet", "Please add employees to the Employee Master "
                                                       "(Form 9) first.")
            return
        default_name = f"{self.project.name or 'EPF'}_Form9.xlsx"
        path = filedialog.asksaveasfilename(title="Generate Form 9", defaultextension=".xlsx",
                                             initialfile=default_name,
                                             filetypes=[("Excel Workbook", "*.xlsx")])
        if not path:
            return
        try:
            generate_form9(self.project, path)
        except Exception as e:
            messagebox.showerror("Generation Failed", f"Could not generate Form 9:\n{e}\n\n"
                                                        f"(If the file is already open in Excel, close it "
                                                        f"and try again.)")
            return
        self._set_status(f"Generated Form 9: {os.path.basename(path)}")
        if messagebox.askyesno("Form 9 Generated", f"Form 9 saved to:\n{path}\n\nOpen it now?"):
            try:
                os.startfile(path)
            except Exception:
                pass

    def generate_month_form(self, form_kind):
        if not self.project.code or not self.project.name:
            messagebox.showwarning("Establishment Info Needed",
                                    "Please fill in and save the Establishment details first "
                                    "(see section 1).")
            return
        if not self.project.master:
            messagebox.showinfo("No Employees Yet", "Please add employees to the Employee Master "
                                                       "(Form 9) first.")
            return
        MonthYearFormDialog(self, self.project, form_kind)

    def _open_folder(self, folder):
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception:
            pass

    def show_about(self):
        messagebox.showinfo("About", f"{APP_TITLE}\n\n"
                                      "Establishment and Employee Master are entered once. "
                                      "Each financial year is kept completely separate: switch "
                                      "years using the dropdown, and Generate always produces a "
                                      "single Excel file for the year currently selected.\n\n"
                                      "Built for EPFO enforcement/compliance data entry.")


def main():
    app = EPFApp()
    app.mainloop()


if __name__ == "__main__":
    main()
