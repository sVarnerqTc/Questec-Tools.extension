# -*- coding: utf-8 -*-
"""Find equipment tags from Excel inside a submittal folder and write matches back.

Workflow:
1) User selects an Excel workbook with tags.
2) User selects a submittals folder.
3) Script scans files for each tag.
4) Script writes match file names and hyperlink to the first match.
"""

import os
import re
import zipfile

import clr
from pyrevit import forms

clr.AddReference("Microsoft.Office.Interop.Excel")
clr.AddReference("System")
from Microsoft.Office.Interop import Excel
from System.Runtime.InteropServices import Marshal


TEXT_EXTENSIONS = set([
    ".txt", ".csv", ".log", ".xml", ".json", ".yaml", ".yml", ".ini", ".rtf", ".md",
])

OOXML_EXTENSIONS = set([
    ".docx", ".xlsx", ".xlsm", ".pptx",
])

BINARY_FALLBACK_EXTENSIONS = set([
    ".pdf", ".doc", ".xls", ".dwg", ".nwc", ".ifc", ".rvt",
])

ALL_SEARCHABLE_EXTENSIONS = TEXT_EXTENSIONS | OOXML_EXTENSIONS | BINARY_FALLBACK_EXTENSIONS


def normalize_tag(raw_value):
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    return text.upper()


def normalize_blob(text):
    if not text:
        return ""
    return str(text).upper()


def safe_decode(data):
    try:
        return data.decode("utf-8", "ignore")
    except Exception:
        return data.decode("latin-1", "ignore")


def extract_text_blob(file_path):
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext in TEXT_EXTENSIONS:
        try:
            with open(file_path, "rb") as stream:
                return safe_decode(stream.read())
        except Exception:
            return ""

    if ext in OOXML_EXTENSIONS:
        try:
            chunks = []
            with zipfile.ZipFile(file_path, "r") as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".xml"):
                        continue
                    try:
                        chunks.append(safe_decode(zf.read(name)))
                    except Exception:
                        continue
            return "\n".join(chunks)
        except Exception:
            return ""

    if ext in BINARY_FALLBACK_EXTENSIONS:
        try:
            with open(file_path, "rb") as stream:
                return safe_decode(stream.read())
        except Exception:
            return ""

    return ""


def get_searchable_files(root_folder):
    file_paths = []
    for current_root, _, filenames in os.walk(root_folder):
        for filename in filenames:
            _, ext = os.path.splitext(filename)
            if ext.lower() in ALL_SEARCHABLE_EXTENSIONS:
                file_paths.append(os.path.join(current_root, filename))
    return file_paths


def build_tag_patterns(tags):
    patterns = {}
    for tag in tags:
        escaped = re.escape(tag)
        # Tag boundaries prevent partial hits such as XP-12 matching P-1.
        pattern = re.compile(r"(?<![A-Z0-9])" + escaped + r"(?![A-Z0-9])")
        patterns[tag] = pattern
    return patterns


def scan_folder_for_tags(folder_path, tags):
    matches = dict((tag, []) for tag in tags)

    file_paths = get_searchable_files(folder_path)
    if not file_paths:
        return matches, 0

    patterns = build_tag_patterns(tags)

    for file_path in file_paths:
        blob = normalize_blob(extract_text_blob(file_path))
        if not blob:
            continue

        for tag, pattern in patterns.items():
            if pattern.search(blob):
                matches[tag].append(file_path)

    return matches, len(file_paths)


def column_letter_to_index(column_letter):
    letters = str(column_letter).strip().upper()
    if not letters or not letters.isalpha():
        return None

    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def get_or_create_output_columns(sheet):
    used = sheet.UsedRange
    last_col = int(used.Column + used.Columns.Count - 1)

    results_col = last_col + 1
    link_col = last_col + 2

    sheet.Cells(1, results_col).Value2 = "Submittal Match Files"
    sheet.Cells(1, link_col).Value2 = "Open First Match"

    return results_col, link_col


def release_com(obj):
    if obj is None:
        return
    try:
        Marshal.ReleaseComObject(obj)
    except Exception:
        pass


def run():
    excel_path = forms.pick_file(
        file_ext="xlsx",
        files_filter="Excel Files (*.xlsx;*.xlsm;*.xls)|*.xlsx;*.xlsm;*.xls",
        multi_file=False,
    )
    if not excel_path:
        return

    submittals_folder = forms.pick_folder(title="Pick Submittals Folder")
    if not submittals_folder:
        return

    col_letter = forms.ask_for_string(
        prompt="Tag column letter (example: A)",
        default="A",
        title="Tag Column",
    )
    if not col_letter:
        return

    tag_col = column_letter_to_index(col_letter)
    if not tag_col:
        forms.alert("Invalid column letter. Example valid values: A, B, AA", exitscript=True)

    start_row_str = forms.ask_for_string(
        prompt="First row containing tags (example: 2)",
        default="2",
        title="Start Row",
    )
    if not start_row_str:
        return

    try:
        start_row = int(start_row_str)
    except Exception:
        forms.alert("Start row must be an integer.", exitscript=True)

    if start_row < 1:
        forms.alert("Start row must be 1 or greater.", exitscript=True)

    excel_app = None
    workbook = None
    sheet = None
    used = None

    try:
        excel_app = Excel.ApplicationClass()
        excel_app.Visible = False
        excel_app.DisplayAlerts = False

        workbook = excel_app.Workbooks.Open(excel_path)
        sheet = workbook.Worksheets[1]

        used = sheet.UsedRange
        last_row = int(used.Row + used.Rows.Count - 1)

        tag_rows = []
        tags = []
        seen = set()

        for row in range(start_row, last_row + 1):
            value = sheet.Cells(row, tag_col).Value2
            tag = normalize_tag(value)
            if not tag:
                continue
            tag_rows.append((row, tag))
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)

        if not tags:
            forms.alert("No tags were found in the selected column.", exitscript=True)

        matches_by_tag, files_scanned = scan_folder_for_tags(submittals_folder, tags)
        results_col, link_col = get_or_create_output_columns(sheet)

        rows_with_match = 0
        for row, tag in tag_rows:
            hits = matches_by_tag.get(tag, [])

            results_cell = sheet.Cells(row, results_col)
            link_cell = sheet.Cells(row, link_col)

            results_cell.Value2 = ""
            link_cell.Value2 = ""

            if not hits:
                continue

            rows_with_match += 1
            display_names = [os.path.basename(path) for path in hits]
            results_cell.Value2 = "; ".join(display_names)

            first_match = hits[0]
            try:
                sheet.Hyperlinks.Add(link_cell, first_match, "", "", "Open")
            except Exception:
                # Fallback: write plain path if hyperlink add fails.
                link_cell.Value2 = first_match

        workbook.Save()

        forms.alert(
            "Completed.\n\n"
            "Workbook: {}\n"
            "Files scanned: {}\n"
            "Unique tags checked: {}\n"
            "Rows with at least one match: {}".format(
                excel_path,
                files_scanned,
                len(tags),
                rows_with_match,
            ),
            title="Submittal Tag Finder",
        )

    except Exception as exc:
        forms.alert("Error: {}".format(str(exc)), title="Submittal Tag Finder")

    finally:
        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                pass

        if excel_app is not None:
            try:
                excel_app.Quit()
            except Exception:
                pass

        release_com(used)
        release_com(sheet)
        release_com(workbook)
        release_com(excel_app)


if __name__ == "__main__":
    run()
