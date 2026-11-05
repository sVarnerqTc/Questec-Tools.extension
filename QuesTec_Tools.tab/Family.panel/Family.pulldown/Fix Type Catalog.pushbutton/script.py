# -*- coding: utf-8 -*-
"""Remove columns from a Revit type catalog (.txt) that this Revit version
can't read.

1. Pick a type catalog.
2. Every parameter column is listed. Columns whose header contains one of the
   problem keywords (default: POUNDS, GALLONS) are pre-checked.
3. The checked columns are removed. The original is kept as
   <name>_original.txt and the fixed catalog is written back to <name>.txt.

Shift+Click to edit the keyword list.
"""

import codecs
import io
import os
import shutil
import time

from pyrevit import forms, script

import catalog_config


TITLE = "Fix Type Catalog"
DEFAULT_DIR = r"Q:\BIM Department\Revit\Families"


# ---------------------------------------------------------------- file io

def detect_encoding(path):
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    with open(path, "rb") as f:
        raw = f.read()
    try:
        raw.decode("utf-8")
        return "utf-8"
    except Exception:
        return "cp1252"


def split_raw_fields(line):
    """Split one catalog line into cells, keeping each cell exactly as written
    (quotes included) so cells that aren't removed are written back unchanged.

    A quote only starts a quoted cell when it is the cell's first character, so
    inch marks in unquoted cells (e.g. 1-1/4") don't break the split. Inside a
    quoted cell, "" is an escaped quote.
    """
    fields = []
    i = 0
    n = len(line)
    while True:
        start = i
        if i < n and line[i] == '"':
            i += 1
            while i < n:
                if line[i] == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            # Anything after the closing quote up to the next comma stays with this cell.
            while i < n and line[i] != ',':
                i += 1
        else:
            while i < n and line[i] != ',':
                i += 1
        fields.append(line[start:i])
        if i >= n:
            break
        i += 1  # skip the comma
    return fields


def header_text(raw_field):
    value = raw_field.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1].replace('""', '"')
    return value


def read_catalog(path):
    encoding = detect_encoding(path)
    with io.open(path, "r", encoding=encoding, newline="") as f:
        text = f.read()
    newline = u"\r\n" if u"\r\n" in text else u"\n"
    lines = text.splitlines()
    return lines, encoding, newline


def write_catalog(path, lines, encoding, newline):
    with io.open(path, "w", encoding=encoding, newline="") as f:
        f.write(newline.join(lines) + newline)


def backup_path_for(path):
    base, ext = os.path.splitext(path)
    candidate = "{0}_original{1}".format(base, ext)
    if not os.path.exists(candidate):
        return candidate
    # Never overwrite an earlier backup - it may be the true original.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return "{0}_original_{1}{2}".format(base, stamp, ext)


# ---------------------------------------------------------------- columns

class ColumnOption(forms.TemplateListItem):
    @property
    def name(self):
        index, header, reason = self.item
        label = u"{0}".format(header)
        if reason:
            label += u"    <-- contains {0}".format(reason)
        return label


def find_keyword(header, keywords):
    upper = header.upper()
    for kw in keywords:
        if kw and kw.upper() in upper:
            return kw.upper()
    return None


# ---------------------------------------------------------------- main

def main():
    init_dir = DEFAULT_DIR if os.path.isdir(DEFAULT_DIR) else None
    path = forms.pick_file(file_ext="txt", init_dir=init_dir, title="Pick a Type Catalog (.txt)")
    if not path:
        return

    try:
        lines, encoding, newline = read_catalog(path)
    except Exception as ex:
        forms.alert("Could not read the file:\n\n{0}".format(ex), title=TITLE)
        return

    header = split_raw_fields(lines[0]) if lines else []
    if len(header) < 2:
        forms.alert("This doesn't look like a type catalog (no parameter columns in the first line).", title=TITLE)
        return

    keywords = catalog_config.get_keywords()

    # Column 0 holds the type names and is never offered for removal.
    options = []
    for index in range(1, len(header)):
        col_header = header_text(header[index])
        reason = find_keyword(col_header, keywords)
        options.append(ColumnOption((index, col_header or u"(blank header)", reason), checked=bool(reason)))

    flagged_count = sum(1 for o in options if o.checked)
    selected = forms.SelectFromList.show(
        options,
        title="{0} - {1} column(s) flagged. Check the columns to REMOVE".format(
            os.path.basename(path), flagged_count),
        button_name="Remove Checked Columns",
        multiselect=True,
        width=800,
        height=600,
    )
    if selected is None:
        return
    if not selected:
        forms.alert("No columns were checked. The catalog was not changed.", title=TITLE)
        return

    remove_indexes = set(item[0] for item in selected)
    removed_headers = [header_text(header[i]) for i in sorted(remove_indexes)]

    fixed_lines = []
    short_rows = 0
    for line in lines:
        if not line.strip():
            fixed_lines.append(line)
            continue
        fields = split_raw_fields(line)
        if len(fields) != len(header):
            short_rows += 1
        fixed_lines.append(u",".join(f for i, f in enumerate(fields) if i not in remove_indexes))

    backup = backup_path_for(path)
    try:
        shutil.copy2(path, backup)
        write_catalog(path, fixed_lines, encoding, newline)
    except Exception as ex:
        forms.alert(
            "Could not save the fixed catalog:\n\n{0}\n\n"
            "If a backup was made it is at:\n{1}".format(ex, backup),
            title=TITLE,
        )
        return

    summary = [
        u"Removed {0} column(s) from {1}:".format(len(removed_headers), os.path.basename(path)),
        u"",
    ]
    summary.extend(u"  " + h for h in removed_headers)
    summary.extend([
        u"",
        u"{0} type(s) kept, {1} column(s) remaining.".format(
            sum(1 for l in fixed_lines[1:] if l.strip()), len(header) - 1 - len(remove_indexes)),
        u"",
        u"Original saved as:",
        u"  " + os.path.basename(backup),
    ])
    if short_rows:
        summary.extend([
            u"",
            u"Warning: {0} row(s) had a different number of cells than the header. "
            u"Check those rows in the catalog.".format(short_rows),
        ])
    forms.alert(u"\n".join(summary), title=TITLE)


if __name__ == "__main__":
    main()
