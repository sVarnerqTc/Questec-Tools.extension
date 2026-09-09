# -*- coding: utf-8 -*-
"""Match pipe fitting Comments to a TIG Weld Number column in Excel and write weld data back.

Workflow:
1) User browses to an Excel workbook.
2) Script reads the header row to locate the required columns.
3) Script collects pipe fittings in the active view and reads their Comments.
4) For each fitting whose Comments matches a "TIG Weld Number" cell, write the
   corresponding Excel row values to the Date, Time, Welder ID, and Orbital S/N
   parameters on that fitting.
"""

import clr

clr.AddReference("RevitAPI")
clr.AddReference("Microsoft.Office.Interop.Excel")
clr.AddReference("System")

from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, FilteredElementCollector, Transaction
from Microsoft.Office.Interop import Excel
from System.Runtime.InteropServices import Marshal

from pyrevit import forms, revit, script

doc = revit.doc
active_view = doc.ActiveView
logger = script.get_logger()

REQUIRED_COLUMNS = ["TIG Weld Number", "Date", "Time", "Welders Signature", "Location of Weld"]

# Excel "Location of Weld" values mapped to the Revit "Orbital S/N" parameter value.
ORBITAL_SN_BY_LOCATION = {
    "clean room": "23100024",
    "field machine 2": "15080015",
    "field machine 3": "14080220",
}

# Excel column heading -> Revit parameter name.
COLUMN_TO_PARAMETER = {
    "Date": "Date",
    "Time": "Time",
    "Welders Signature": "Welder ID",
    "Location of Weld": "Orbital S/N",
}


def normalize(value):
    if value is None:
        return ""
    return str(value).strip()


def release_com(obj):
    if obj is None:
        return
    try:
        Marshal.ReleaseComObject(obj)
    except Exception:
        pass


def read_excel_rows(excel_path):
    """Return (rows, missing_columns). rows is a list of dicts keyed by REQUIRED_COLUMNS."""
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
        last_col = int(used.Column + used.Columns.Count - 1)

        header_col_by_name = {}
        for col in range(1, last_col + 1):
            header = normalize(sheet.Cells(1, col).Text)
            if header:
                header_col_by_name[header.lower()] = col

        missing_columns = [name for name in REQUIRED_COLUMNS if name.lower() not in header_col_by_name]
        if missing_columns:
            return [], missing_columns

        rows = []
        for row in range(2, last_row + 1):
            row_data = {}
            for name in REQUIRED_COLUMNS:
                col = header_col_by_name[name.lower()]
                row_data[name] = normalize(sheet.Cells(row, col).Text)
            if row_data["TIG Weld Number"]:
                rows.append(row_data)

        return rows, []
    finally:
        try:
            if workbook is not None:
                workbook.Close(False)
            if excel_app is not None:
                excel_app.Quit()
        except Exception:
            pass
        release_com(used)
        release_com(sheet)
        release_com(workbook)
        release_com(excel_app)


def get_comments(fitting):
    param = fitting.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if param is None:
        param = fitting.LookupParameter("Comments")
    if param is None:
        return ""
    return normalize(param.AsString())


def main():
    excel_path = forms.pick_file(
        file_ext="xlsx",
        files_filter="Excel Files (*.xlsx;*.xlsm;*.xls)|*.xlsx;*.xlsm;*.xls",
        multi_file=False,
    )
    if not excel_path:
        return

    rows, missing_columns = read_excel_rows(excel_path)
    if missing_columns:
        forms.alert(
            "The following columns were not found in the Excel file:\n{}".format(
                "\n".join(missing_columns)
            ),
            title="Missing Columns",
            exitscript=True,
        )

    rows_by_weld_number = {}
    for row_data in rows:
        rows_by_weld_number[row_data["TIG Weld Number"].lower()] = row_data

    fittings = (
        FilteredElementCollector(doc, active_view.Id)
        .OfCategory(BuiltInCategory.OST_PipeFitting)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    missing_parameters = set()
    unmapped_locations = set()
    matched_count = 0

    t = Transaction(doc, "Import TIG Weld Data")
    t.Start()
    try:
        for fitting in fittings:
            comments = get_comments(fitting)
            if not comments:
                continue

            row_data = rows_by_weld_number.get(comments.lower())
            if row_data is None:
                continue

            matched_count += 1

            for column_name, param_name in COLUMN_TO_PARAMETER.items():
                value = row_data[column_name]

                if column_name == "Location of Weld":
                    mapped_value = ORBITAL_SN_BY_LOCATION.get(value.lower())
                    if mapped_value is None:
                        unmapped_locations.add(value)
                        continue
                    value = mapped_value

                param = fitting.LookupParameter(param_name)
                if param is None or param.IsReadOnly:
                    missing_parameters.add(param_name)
                    continue

                try:
                    param.Set(value)
                except Exception as e:
                    logger.warning("Could not set '{}' on element {}: {}".format(param_name, fitting.Id, e))

        t.Commit()
    except Exception as e:
        t.RollBack()
        forms.alert("Error occurred: {}".format(e), title="Error")
        return

    warnings = []
    if missing_parameters:
        warnings.append(
            "The following Revit parameters were not found on one or more fittings:\n{}".format(
                "\n".join(sorted(missing_parameters))
            )
        )
    if unmapped_locations:
        warnings.append(
            "The following 'Location of Weld' values have no Orbital S/N mapping:\n{}".format(
                "\n".join(sorted(unmapped_locations))
            )
        )

    if warnings:
        forms.alert("\n\n".join(warnings), title="Import TIG Weld Data - Warnings")

    forms.alert("Matched and updated {} pipe fitting(s).".format(matched_count), title="Import TIG Weld Data")


main()
