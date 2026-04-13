# -*- coding: utf-8 -*-
"""Parse SysQue System XML and export referenced family files to Excel."""

import os
import re
import sys
import xml.etree.ElementTree as ET

from pyrevit import DB, forms


def get_pyrevit_site_packages():
    """Return the pyRevit site-packages path based on APPDATA."""
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


def strip_tag(tag_name):
    """Remove namespace from an XML tag name."""
    if "}" in tag_name:
        return tag_name.split("}", 1)[1]
    return tag_name


def split_palette_path(path_value):
    """Split SysQue path text into folder parts."""
    if not path_value:
        return []

    normalized = path_value.replace("/", "\\")
    parts = [p for p in normalized.split("\\") if p]
    return parts


def resolve_family_path(root_dir, palette_path, family_file):
    """Resolve absolute family path from root + palette path + family file."""
    if not root_dir:
        return ""

    parts = split_palette_path(palette_path)
    path_parts = [root_dir] + parts + [family_file]
    return os.path.normpath(os.path.join(*path_parts))


def get_revit_version(file_path):
    """Read Revit file format quickly without opening the family document."""
    if not file_path or not os.path.exists(file_path):
        return ""

    try:
        basic_file_info = DB.BasicFileInfo.Extract(file_path)
        if basic_file_info and basic_file_info.Format:
            return str(basic_file_info.Format)
    except Exception:
        return "Unknown"

    return "Unknown"


def sort_entries(entries):
    """Sort rows for predictable output."""
    def order_key(item):
        value = item.get("system_order", "")
        try:
            return (0, int(value))
        except Exception:
            return (1, str(value))

    def sort_key(item):
        return (
            order_key(item),
            item.get("system", ""),
            item.get("category", ""),
            "|".join(item.get("xml_path", [])),
            "|".join(item.get("palette_parts", [])),
            item.get("family_file", ""),
            item.get("item_name", ""),
        )

    return sorted(entries, key=sort_key)


def parse_sysque_xml(xml_path, families_root):
    """Extract family entries from SysQue XML file."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    entries = []
    def walk(node, system_name, system_type, system_order, system_visible, category_name, xml_path_parts):
        node_tag = strip_tag(node.tag)

        current_system_name = system_name
        current_system_type = system_type
        current_system_order = system_order
        current_system_visible = system_visible
        current_category_name = category_name
        if node_tag == "SystemDef":
            current_system_name = node.attrib.get("name", "")
            current_system_type = node.attrib.get("type", "")
            current_system_order = node.attrib.get("Id", "")
            in_visibility = node.attrib.get("InVisibility", "")
            current_system_visible = "No" if in_visibility and in_visibility.strip() else "Yes"
            current_category_name = ""
            xml_path_parts = []

        node_name = node.attrib.get("name", "")
        if node_tag == "Fittings" and node_name:
            current_category_name = node_name

        next_xml_path = list(xml_path_parts)
        if node_tag != "SystemDef":
            label = node_tag if not node_name else "{}: {}".format(node_tag, node_name)
            next_xml_path.append(label)

        icon_value = node.attrib.get("icon", "")
        if icon_value and icon_value.lower().endswith(".rfa"):
            palette_path = node.attrib.get("path", "")
            palette_parts = split_palette_path(palette_path)

            family_file = os.path.basename(icon_value)
            family_name = os.path.splitext(family_file)[0]
            resolved_path = resolve_family_path(families_root, palette_path, family_file)
            file_exists = os.path.exists(resolved_path) if resolved_path else False
            revit_version = get_revit_version(resolved_path) if file_exists else ""

            entries.append({
                "system_order": current_system_order,
                "system_visible": current_system_visible,
                "system": current_system_name,
                "category": current_category_name,
                "xml_path": next_xml_path,
                "item_name": node_name,
                "palette_parts": palette_parts,
                "family_name": family_name,
                "family_file": family_file,
                "palette_path": palette_path,
                "resolved_path": resolved_path,
                "file_exists": "Yes" if file_exists else "No" if resolved_path else "",
                "revit_version": revit_version,
            })

        for child in list(node):
            walk(
                child,
                current_system_name,
                current_system_type,
                current_system_order,
                current_system_visible,
                current_category_name,
                next_xml_path,
            )

    walk(root, "", "", 0, "Yes", "", [])
    return sort_entries(entries)


def write_workbook(output_path, entries, palette_filter):
    """Write SysQue family entries into a styled Excel workbook."""
    max_palette_depth = 0
    for item in entries:
        depth = len(item.get("palette_parts", []))
        if depth > max_palette_depth:
            max_palette_depth = depth

    headers = [
        "System Order",
        "System Visible",
        "System",
        "Category",
        "XML Item Name",
        "XML Category Path",
    ]
    palette_folder_1_col_idx = -1
    for i in range(max_palette_depth):
        header_name = "Palette Folder {}".format(i + 1)
        headers.append(header_name)
        if i == 0:
            palette_folder_1_col_idx = len(headers) - 1

    headers.extend([
        "Family Name",
        "Family File",
        "Palette Path",
        "Resolved Path",
        "File Exists",
        "Revit Version",
    ])

    workbook = xlsxwriter.Workbook(output_path)
    worksheet = workbook.add_worksheet("SysQue Families")

    header_format = workbook.add_format({
        "bold": True,
        "font_name": "Calibri",
        "font_size": 11,
        "font_color": "#FFFFFF",
        "bg_color": "#2F5496",
        "align": "center",
        "valign": "vcenter",
        "text_wrap": True,
        "border": 1,
    })
    default_format = workbook.add_format({
        "valign": "vcenter",
        "border": 1,
    })
    alt_format = workbook.add_format({
        "valign": "vcenter",
        "border": 1,
        "bg_color": "#DCE6F1",
    })

    column_widths = [len(h) for h in headers]

    col_idx = 0
    for header in headers:
        worksheet.write(0, col_idx, header, header_format)
        col_idx += 1

    worksheet.set_row(0, 30)

    row_number = 1
    for item in entries:
        palette_parts = item.get("palette_parts", [])
        padded_palette_parts = list(palette_parts)
        while len(padded_palette_parts) < max_palette_depth:
            padded_palette_parts.append("")

        row_data = [
            item.get("system_order", ""),
            item.get("system_visible", ""),
            item.get("system", ""),
            item.get("category", ""),
            item.get("item_name", ""),
            " > ".join(item.get("xml_path", [])),
        ] + padded_palette_parts + [
            item.get("family_name", ""),
            item.get("family_file", ""),
            item.get("palette_path", ""),
            item.get("resolved_path", ""),
            item.get("file_exists", ""),
            item.get("revit_version", ""),
        ]

        row_format = alt_format if row_number % 2 == 0 else default_format

        col_idx = 0
        for value in row_data:
            worksheet.write(row_number, col_idx, value, row_format)
            value_len = len(str(value)) if value is not None and value != "" else 0
            if value_len > column_widths[col_idx]:
                column_widths[col_idx] = value_len
            col_idx += 1

        palette_folder_1 = padded_palette_parts[0] if padded_palette_parts else ""
        is_visible_system = (item.get("system_visible", "") == "Yes")
        selected_palette = (palette_filter or "all").strip().lower()
        if selected_palette == "all":
            matches_palette_filter = True
        elif palette_folder_1_col_idx >= 0:
            matches_palette_filter = (palette_folder_1.strip().lower() == selected_palette)
        else:
            matches_palette_filter = True

        if (not is_visible_system) or (not matches_palette_filter):
            worksheet.set_row(row_number, None, None, {'hidden': True})

        row_number += 1

    for idx, max_len in enumerate(column_widths):
        worksheet.set_column(idx, idx, min(max(max_len + 4, 14), 90))

    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(entries), len(headers) - 1)
    worksheet.filter_column(1, 'x == Yes')
    if palette_folder_1_col_idx >= 0 and (palette_filter or "all").strip().lower() != "all":
        worksheet.filter_column(palette_folder_1_col_idx, 'x == {}'.format((palette_filter or "").strip().lower()))

    workbook.close()


def main():
    xml_path = forms.pick_file(file_ext="xml")
    if not xml_path:
        return

    palette_filter_choice = forms.SelectFromList.show(
        ["Imperial", "Metric", "All"],
        title="Palette Folder 1 Filter",
        multiselect=False,
        button_name="Continue",
    )
    if not palette_filter_choice:
        return

    palette_filter = palette_filter_choice.strip().lower()

    pick_root = forms.alert(
        "Do you want to select a SysQue family root folder for path validation and Revit version lookup?",
        yes=True,
        no=True,
        title="Optional Root Folder"
    )

    families_root = ""
    if pick_root:
        selected_root = forms.pick_folder(title="Select SysQue Family Root Folder")
        if selected_root:
            families_root = selected_root

    try:
        entries = parse_sysque_xml(xml_path, families_root)
    except Exception as ex:
        forms.alert("Failed to parse XML:\n{}".format(str(ex)), title="Parse Error")
        return

    if not entries:
        forms.alert("No family references with .rfa icons were found in this XML.", title="No Families Found")
        return

    xml_dir = os.path.dirname(xml_path)
    xml_name = os.path.splitext(os.path.basename(xml_path))[0]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", xml_name).strip("_") or "SysQue"
    output_path = os.path.join(xml_dir, "{}_Family_List.xlsx".format(safe_name))

    if os.path.exists(output_path):
        overwrite = forms.alert(
            "Output file already exists:\n{}\n\nOverwrite it?".format(output_path),
            title="File Exists",
            yes=True,
            no=True,
        )
        if not overwrite:
            return

    try:
        write_workbook(output_path, entries, palette_filter)
    except Exception as ex:
        forms.alert("Failed to write Excel file:\n{}".format(str(ex)), title="Export Error")
        return

    forms.alert(
        "Exported {} family references to:\n\n{}".format(len(entries), output_path),
        title="Export Complete"
    )


main()
