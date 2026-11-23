# -*- coding: utf-8 -*-
"""Assign links (Revit, CAD, point cloud) to their own worksets.

Shows every link in the project in a window:
  [x] reassign  |  Link  |  Type  |  Instances  |  Current Workset  |  New Workset (editable)

The default new workset name is "Link-<EXT>-<Filename>", for example
Link-RVT-Architecture23. Rows already on that workset start unchecked.
Checked rows are moved (link instances and their link type) to the named
workset, which is created if it doesn't exist. Elements owned by another
user, or out of date with central, are skipped.
"""

import os

import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from System.Windows import (Window, Thickness, SizeToContent, WindowStartupLocation,
                            GridLength, GridUnitType, VerticalAlignment, HorizontalAlignment,
                            ResizeMode, FontWeights)
from System.Windows.Controls import (Grid, ColumnDefinition, RowDefinition, TextBox, TextBlock,
                                     Button, StackPanel, ScrollViewer, Orientation,
                                     ScrollBarVisibility, CheckBox)

from Autodesk.Revit.DB import (
    BuiltInParameter,
    CADLinkType,
    CheckoutStatus,
    ElementId,
    ExternalFileUtils,
    FilteredElementCollector,
    FilteredWorksetCollector,
    ImportInstance,
    ModelPathUtils,
    ModelUpdatesStatus,
    PointCloudInstance,
    RevitLinkInstance,
    Transaction,
    Workset,
    WorksetKind,
    WorksharingUtils,
)
from System.Collections.Generic import List
from pyrevit import forms


doc = __revit__.ActiveUIDocument.Document

TITLE = "Assign Links to Worksets"
INVALID_WORKSET_CHARS = '\\:{}[]|;<>?`~'


# ---------------------------------------------------------------- naming (same rules as before)

def safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def sanitize_workset_name(name):
    for ch in INVALID_WORKSET_CHARS:
        name = name.replace(ch, "_")
    return name.strip()


def get_link_file_name(type_elem):
    """Return the linked file's name with extension, e.g. 'Architecture23.rvt'."""
    try:
        if ExternalFileUtils.IsExternalFileReference(doc, type_elem.Id):
            ref = ExternalFileUtils.GetExternalFileReference(doc, type_elem.Id)
            path = ModelPathUtils.ConvertModelPathToUserVisiblePath(ref.GetAbsolutePath())
            name = os.path.basename(path)
            if name:
                return name
    except Exception:
        pass
    # Type Name holds the file name (e.g. "Architecture23.rvt"). Read it from the
    # parameter - .Name isn't readable on link types from IronPython.
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM, BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            param = type_elem.get_Parameter(bip)
            if param is not None and param.AsString():
                return param.AsString()
        except Exception:
            pass

    try:
        return safe_str(type_elem.Name)
    except Exception:
        return ""


def build_link_workset_name(file_name, fallback_ext):
    base, ext = os.path.splitext(file_name)
    ext = ext.lstrip(".").upper() or fallback_ext
    base = base or file_name or "Unknown"
    return sanitize_workset_name("Link-{0}-{1}".format(ext, base))


# ---------------------------------------------------------------- collect

class LinkRow(object):
    def __init__(self, link_type, kind, fallback_ext):
        self.link_type = link_type
        self.kind = kind
        self.instances = []
        self.file_name = get_link_file_name(link_type)
        self.default_workset = build_link_workset_name(self.file_name, fallback_ext)


def collect_links():
    """One row per link type (file), with all of its instances."""
    rows = {}

    def add(inst, link_type, kind, ext):
        if link_type is None:
            return
        key = link_type.Id.IntegerValue
        if key not in rows:
            rows[key] = LinkRow(link_type, kind, ext)
        rows[key].instances.append(inst)

    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
        add(inst, doc.GetElement(inst.GetTypeId()), "Revit", "RVT")

    for inst in FilteredElementCollector(doc).OfClass(ImportInstance).ToElements():
        if not inst.IsLinked:
            continue
        link_type = doc.GetElement(inst.GetTypeId())
        if isinstance(link_type, CADLinkType):
            add(inst, link_type, "CAD", "CAD")

    for inst in FilteredElementCollector(doc).OfClass(PointCloudInstance).ToElements():
        add(inst, doc.GetElement(inst.GetTypeId()), "Point Cloud", "PCD")

    return sorted(rows.values(), key=lambda r: (r.kind, r.file_name.lower()))


def get_user_worksets():
    worksets = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
    return dict((ws.Name.strip().lower(), ws) for ws in worksets)


def get_workset_id(element):
    param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    return param.AsInteger() if param is not None else None


def current_workset_text(row, names_by_id):
    names = sorted(set(names_by_id.get(get_workset_id(i), "?") for i in row.instances))
    return ", ".join(names)


def is_editable(element_id):
    try:
        if WorksharingUtils.GetCheckoutStatus(doc, element_id) == CheckoutStatus.OwnedByOtherUser:
            return False
        status = WorksharingUtils.GetModelUpdatesStatus(doc, element_id)
        if status in (ModelUpdatesStatus.UpdatedInCentral, ModelUpdatesStatus.DeletedInCentral):
            return False
    except Exception:
        pass
    return True


# ---------------------------------------------------------------- window

def text_cell(text, bold=False, margin_left=10):
    tb = TextBlock()
    tb.Text = text
    tb.Margin = Thickness(margin_left, 4, 0, 4)
    tb.VerticalAlignment = VerticalAlignment.Center
    if bold:
        tb.FontWeight = FontWeights.Bold
    return tb


def show_links_window(rows, names_by_id, existing):
    """Returns list of (row, new workset name) for checked rows, or None if cancelled."""
    window = Window()
    window.Title = TITLE
    window.SizeToContent = SizeToContent.WidthAndHeight
    window.WindowStartupLocation = WindowStartupLocation.CenterScreen
    window.ResizeMode = ResizeMode.NoResize

    root = StackPanel()
    root.Margin = Thickness(14)

    intro = TextBlock()
    intro.Text = ("Check the links to move. Edit the new workset name if needed; "
                  "missing worksets are created.\n"
                  "Default name: Link-<file type>-<file name>. Rows already on that workset start unchecked.")
    intro.Margin = Thickness(0, 0, 0, 10)
    root.Children.Add(intro)

    grid = Grid()
    widths = [GridLength(1, GridUnitType.Auto)] * 5 + [GridLength(260)]
    for w in widths:
        col = ColumnDefinition()
        col.Width = w
        grid.ColumnDefinitions.Add(col)

    def place(element, row_index, col_index):
        Grid.SetRow(element, row_index)
        Grid.SetColumn(element, col_index)
        grid.Children.Add(element)

    # header
    grid.RowDefinitions.Add(RowDefinition())
    select_all = CheckBox()
    select_all.VerticalAlignment = VerticalAlignment.Center
    select_all.ToolTip = "Check / uncheck all"
    place(select_all, 0, 0)
    for i, label in enumerate(["Link", "Type", "Instances", "Current Workset", "New Workset"]):
        place(text_cell(label, bold=True), 0, i + 1)

    entries = []
    for r_index, row in enumerate(rows):
        grid.RowDefinitions.Add(RowDefinition())
        current = current_workset_text(row, names_by_id)
        default_ws = existing.get(row.default_workset.lower())
        already_there = (default_ws is not None and
                         all(get_workset_id(i) == default_ws.Id.IntegerValue for i in row.instances))

        check = CheckBox()
        check.IsChecked = not already_there
        check.VerticalAlignment = VerticalAlignment.Center
        place(check, r_index + 1, 0)
        place(text_cell(row.file_name or "(unnamed)"), r_index + 1, 1)
        place(text_cell(row.kind), r_index + 1, 2)
        place(text_cell(str(len(row.instances))), r_index + 1, 3)
        place(text_cell(current), r_index + 1, 4)

        box = TextBox()
        box.Text = row.default_workset
        box.Margin = Thickness(10, 3, 0, 3)
        box.VerticalAlignment = VerticalAlignment.Center
        place(box, r_index + 1, 5)
        entries.append((row, check, box))

    def on_select_all(sender, args):
        for _, check, _ in entries:
            check.IsChecked = select_all.IsChecked

    select_all.Click += on_select_all
    select_all.IsChecked = all(c.IsChecked for _, c, _ in entries)

    scroller = ScrollViewer()
    scroller.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    scroller.MaxHeight = 560
    scroller.Content = grid
    root.Children.Add(scroller)

    buttons = StackPanel()
    buttons.Orientation = Orientation.Horizontal
    buttons.HorizontalAlignment = HorizontalAlignment.Right
    buttons.Margin = Thickness(0, 12, 0, 0)
    ok = Button(); ok.Content = "Assign Checked Links"; ok.Padding = Thickness(10, 2, 10, 2); ok.IsDefault = True
    cancel = Button(); cancel.Content = "Cancel"; cancel.Width = 80; cancel.IsCancel = True
    cancel.Margin = Thickness(8, 0, 0, 0)
    buttons.Children.Add(ok)
    buttons.Children.Add(cancel)
    root.Children.Add(buttons)

    result = {"ok": False}

    def on_ok(sender, args):
        result["ok"] = True
        window.Close()

    ok.Click += on_ok
    window.Content = root
    window.ShowDialog()

    if not result["ok"]:
        return None
    chosen = []
    for row, check, box in entries:
        if check.IsChecked:
            chosen.append((row, sanitize_workset_name(box.Text or "")))
    return chosen


# ---------------------------------------------------------------- main

def main():
    if doc.IsFamilyDocument or not doc.IsWorkshared:
        forms.alert("This model is not workshared. Enable worksharing first.", title=TITLE)
        return

    rows = collect_links()
    if not rows:
        forms.alert("No Revit, CAD or point cloud links were found in this project.", title=TITLE)
        return

    existing = get_user_worksets()
    names_by_id = dict((ws.Id.IntegerValue, ws.Name) for ws in existing.values())

    while True:
        chosen = show_links_window(rows, names_by_id, existing)
        if chosen is None:
            return
        if not chosen:
            forms.alert("No links were checked. Nothing was changed.", title=TITLE)
            return
        blank = [row.file_name for row, name in chosen if not name]
        if blank:
            forms.alert("Enter a workset name for:\n\n{0}".format("\n".join(blank)), title=TITLE)
            continue
        break

    # Elements to move: every instance plus the link type itself.
    to_move = []      # (element, workset name, row)
    already = 0
    for row, ws_name in chosen:
        ws = existing.get(ws_name.lower())
        for elem in row.instances + [row.link_type]:
            if ws is not None and get_workset_id(elem) == ws.Id.IntegerValue:
                already += 1
            else:
                to_move.append((elem, ws_name, row))

    editable = [t for t in to_move if is_editable(t[0].Id)]
    skipped_owned = len(to_move) - len(editable)
    if editable:
        ids = List[ElementId]([e.Id for e, _, _ in editable])
        try:
            borrowed = set(i.IntegerValue for i in WorksharingUtils.CheckoutElements(doc, ids))
            before = len(editable)
            editable = [t for t in editable if t[0].Id.IntegerValue in borrowed]
            skipped_owned += before - len(editable)
        except Exception:
            pass

    created = []
    moved_links = {}
    failed = []
    tx = Transaction(doc, TITLE)
    tx.Start()
    try:
        for elem, ws_name, row in editable:
            ws = existing.get(ws_name.lower())
            if ws is None:
                ws = Workset.Create(doc, ws_name)
                existing[ws_name.lower()] = ws
                created.append(ws_name)
            param = elem.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
            if param is None or param.IsReadOnly:
                failed.append(row.file_name)
                continue
            try:
                param.Set(ws.Id.IntegerValue)
                moved_links[row.file_name] = ws_name
            except Exception:
                failed.append(row.file_name)
        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        forms.alert("Command failed, nothing was changed:\n\n{0}".format(ex), title=TITLE)
        return

    lines = []
    if moved_links:
        lines.append("Moved {0} link(s):".format(len(moved_links)))
        for name in sorted(moved_links):
            lines.append("    {0}  ->  {1}".format(name, moved_links[name]))
    else:
        lines.append("No links needed to move.")
    if already:
        lines.append("")
        lines.append("Already on the chosen workset: {0} element(s)".format(already))
    if skipped_owned:
        lines.append("Skipped (owned by another user or not synced): {0} element(s)".format(skipped_owned))
    if failed:
        lines.append("Could not move (workset is read-only): {0}".format(", ".join(sorted(set(failed)))))
    if created:
        lines.append("")
        lines.append("Created worksets:")
        lines.extend("    " + n for n in sorted(set(created)))
    forms.alert("\n".join(lines), title=TITLE)


if __name__ == "__main__":
    main()
