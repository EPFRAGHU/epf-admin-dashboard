import re

with open("epf_engine.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Replace the block from `def _get_excel_app()` to `def generate_forms_for_year(` (excluding the latter)
new_code = re.sub(
    r"def _get_excel_app\(\):.*?def generate_forms_for_year\(", 
    "def generate_forms_for_year(", 
    code, 
    flags=re.DOTALL
)

# 2. Modify generate_forms_for_year
new_code = re.sub(
    r"def generate_forms_for_year\(project: \"Project\", year_key: str, output_dir: str,\s*make_excel: bool = True, make_pdf: bool = True, excel_app=None\):",
    "def generate_forms_for_year(project: \"Project\", year_key: str, output_dir: str,\n                             make_excel: bool = True, make_pdf: bool = True):",
    new_code
)

# 3. Modify generate_forms_for_year inside
new_code = re.sub(
    r"        if excel_app is not None:\s*_export_pdf_with_app\(excel_app, xlsx_path, pdf_path\)\s*else:\s*convert_workbook_to_pdf\(xlsx_path, pdf_path\)",
    "        convert_excel_to_pdf(xlsx_path, pdf_path)",
    new_code
)

# 4. Modify generate_forms_for_year_range signature and internal
new_code = re.sub(
    r"    excel_app = _get_excel_app\(\) if make_pdf else None\n    results = \[\]",
    "    results = []",
    new_code
)

new_code = re.sub(
    r"                written = generate_forms_for_year\(project, key, output_dir, make_excel, make_pdf,\s*excel_app=excel_app\)",
    "                written = generate_forms_for_year(project, key, output_dir, make_excel, make_pdf)",
    new_code
)

new_code = re.sub(
    r"    finally:\n        if excel_app is not None:\n            excel_app\.Quit\(\)\n    return results",
    "    finally:\n        pass\n    return results",
    new_code
)

# 5. Replace convert_excel_to_pdf
pdf_func = """def convert_excel_to_pdf(excel_path: str, pdf_path: str):
    import subprocess
    import shutil
    import os

    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if not soffice:
        # Fallbacks for Windows if it's not in PATH
        possible_paths = [
            r"C:\\Program Files\\LibreOffice\\program\\soffice.exe",
            r"C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe"
        ]
        for p in possible_paths:
            if os.path.exists(p):
                soffice = p
                break

    if not soffice:
        raise RuntimeError(
            "LibreOffice not found — install it from libreoffice.org and ensure 'soffice' is on PATH. "
            "It is required to generate PDFs across platforms without Microsoft Excel."
        )

    excel_path = os.path.abspath(excel_path)
    outdir = os.path.dirname(os.path.abspath(pdf_path))
    
    # Run LibreOffice headless
    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, excel_path],
        capture_output=True, text=True
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice PDF conversion failed: {result.stderr or result.stdout}")
        
    # LibreOffice saves the file with the same basename as the input file, but with .pdf
    base_name = os.path.splitext(os.path.basename(excel_path))[0]
    generated_pdf = os.path.join(outdir, f"{base_name}.pdf")
    
    # If the requested pdf_path is different from what LibreOffice generated, rename it
    if os.path.abspath(generated_pdf) != os.path.abspath(pdf_path):
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError as e:
                raise RuntimeError(f"Could not overwrite existing PDF (is it open in another program?): {pdf_path}") from e
        os.rename(generated_pdf, pdf_path)
"""

new_code = re.sub(
    r"def convert_excel_to_pdf\(excel_path: str, pdf_path: str\):.*?(?=def generate_ecr_month)",
    lambda _: pdf_func + "\n",
    new_code,
    flags=re.DOTALL
)

with open("epf_engine_new.py", "w", encoding="utf-8") as f:
    f.write(new_code)
