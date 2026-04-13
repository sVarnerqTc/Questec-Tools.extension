# -*- coding: utf-8 -*-
# pyrevit: enginever=385
"""Scan a directory tree for Revit family files (.rfa) and export a structured Excel list."""

import datetime
import os
import sys
from pyrevit import DB, forms


def get_pyrevit_site_packages():
    """Return the pyRevit site-packages path based on the current APPDATA folder."""
    appdata_dir = os.environ.get("APPDATA")
    if not appdata_dir:
        return None

    site_packages = os.path.join(appdata_dir, "pyRevit-Master", "site-packages")
    return site_packages if os.path.isdir(site_packages) else None


site_packages_path = get_pyrevit_site_packages()
if site_packages_path and site_packages_path not in sys.path:
    sys.path.append(site_packages_path)

try:
    import xlsxwriter
except ImportError:
    forms.alert(
        "Could not load xlsxwriter from pyRevit's bundled site-packages.\n\n"
        "Expected path:\n{}".format(site_packages_path or "<APPDATA not found>"),
        title="Missing Dependency"
    )
    sys.exit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_family_metadata(file_path):
    """Return lightweight metadata for a family file without opening it."""
    revit_version = "Unknown"
    last_modified = "Unknown"

    try:
        basic_file_info = DB.BasicFileInfo.Extract(file_path)
        if basic_file_info and basic_file_info.Format:
            revit_version = str(basic_file_info.Format)
    except Exception:
        pass

    try:
        modified_timestamp = os.path.getmtime(file_path)
        last_modified = datetime.datetime.fromtimestamp(modified_timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return revit_version, last_modified

def collect_rfa_files(root_dir):
    """Walk the directory tree under root_dir and return a list of
    family data dictionaries for every .rfa file found.

    folder_parts is a list of folder names relative to root_dir,
    e.g. ['Mechanical', 'Pipe Fittings'] for a file at
    root_dir/Mechanical/Pipe Fittings/Elbow.rfa.
    """
    root_dir = os.path.normpath(root_dir)
    results = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames.sort()  # ensure consistent alphabetical order
        rfa_files = sorted(f for f in filenames if f.lower().endswith('.rfa'))
        if not rfa_files:
            continue

        rel = os.path.relpath(dirpath, root_dir)
        parts = [] if rel == '.' else rel.split(os.sep)

        for fname in rfa_files:
            full_path = os.path.join(dirpath, fname)
            family_name = os.path.splitext(fname)[0]
            revit_version, last_modified = get_family_metadata(full_path)
            results.append({
                'folder_parts': parts,
                'family_name': family_name,
                'full_path': full_path,
                'revit_version': revit_version,
                'last_modified': last_modified,
            })

    return results


def write_workbook(output_path, rfa_files):
    """Write an Excel workbook from the collected file data."""

    max_depth = 0
    for family_data in rfa_files:
        parts = family_data['folder_parts']
        if len(parts) > max_depth:
            max_depth = len(parts)

    headers = ["Subfolder {}".format(i + 1) for i in range(max_depth)] + [
        "Family Name",
        "Revit Version",
        "Last Modified",
        "Full Path",
    ]

    workbook = xlsxwriter.Workbook(output_path)
    worksheet = workbook.add_worksheet("Family List")

    header_format = workbook.add_format({
        'bold': True,
        'font_name': 'Calibri',
        'font_size': 11,
        'font_color': '#FFFFFF',
        'bg_color': '#2F5496',
        'align': 'center',
        'valign': 'vcenter',
        'text_wrap': True,
        'border': 1,
    })
    default_format = workbook.add_format({
        'valign': 'vcenter',
        'border': 1,
    })
    alt_format = workbook.add_format({
        'valign': 'vcenter',
        'border': 1,
        'bg_color': '#DCE6F1',
    })

    column_widths = [len(header) for header in headers]

    for col_idx, header in enumerate(headers):
        worksheet.write(0, col_idx, header, header_format)

    worksheet.set_row(0, 30)

    for row_idx, family_data in enumerate(rfa_files, start=2):
        parts = family_data['folder_parts']
        row_data = parts + [''] * (max_depth - len(parts)) + [
            family_data['family_name'],
            family_data['revit_version'],
            family_data['last_modified'],
            family_data['full_path'],
        ]
        row_format = alt_format if row_idx % 2 == 0 else default_format

        for col_idx, value in enumerate(row_data):
            worksheet.write(row_idx - 1, col_idx, value, row_format)
            value_len = len(value) if value else 0
            if value_len > column_widths[col_idx]:
                column_widths[col_idx] = value_len

    for col_idx, max_len in enumerate(column_widths):
        worksheet.set_column(col_idx, col_idx, min(max(max_len + 4, 14), 60))

    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(rfa_files), len(headers) - 1)

    workbook.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root_dir = forms.pick_folder(title="Select Root Family Directory")
    if not root_dir:
        return

    rfa_files = collect_rfa_files(root_dir)

    if not rfa_files:
        forms.alert(
            "No .rfa files were found in the selected directory.",
            title="No Families Found"
        )
        return

    output_path = os.path.join(root_dir, "Family List.xlsx")

    # If a file already exists, ask before overwriting
    if os.path.exists(output_path):
        overwrite = forms.alert(
            "Family List.xlsx already exists in this folder.\nOverwrite it?",
            title="File Exists",
            yes=True,
            no=True
        )
        if not overwrite:
            return

    write_workbook(output_path, rfa_files)

    forms.alert(
        "{} families exported to:\n\n{}".format(len(rfa_files), output_path),
        title="Export Complete"
    )


main()
