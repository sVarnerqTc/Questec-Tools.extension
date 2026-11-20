# -*- coding: utf-8 -*-
"""Sheet Metal QC: find duct items with a blank Material or Specification Name
(both instance parameters under Identity Data).

Categories checked: Ducts, Duct Fittings, Flex Ducts,
Fabrication Ductwork.

Scope: the current selection if there is one; otherwise everything visible in
the active view (honoring any temporary hide/isolate already applied).

Elements with a blank value are temporarily isolated and selected, and a
summary of the issues is shown. Elements that don't have the parameter at all
are counted in the summary but not isolated.
"""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    ElementMulticategoryFilter,
    FilteredElementCollector,
    StorageType,
    TemporaryViewMode,
    Transaction,
)
from System.Collections.Generic import List
from pyrevit import forms, script


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TITLE = "Sheet Metal QC"

# (BuiltInCategory name, display name)
CATEGORIES = [
    ("OST_DuctCurves", "Ducts"),
    ("OST_DuctFitting", "Duct Fittings"),
    ("OST_FlexDuctCurves", "Flex Ducts"),
    ("OST_FabricationDuctwork", "Fabrication Ductwork"),
]

# Each QC check: (label shown to the user, instance parameter name).
CHECKS = [
    ("Material", "Material"),
    ("Specification Name", "Specification Name"),
]

BLANK = "blank"
MISSING = "missing"


# ---------------------------------------------------------------- helpers

def get_categories():
    cats = List[BuiltInCategory]()
    names = {}
    for bic_name, label in CATEGORIES:
        bic = getattr(BuiltInCategory, bic_name, None)
        if bic is not None:
            cats.Add(bic)
            names[int(bic)] = label
    return cats, names


def param_state(element, param_name):
    """Check an instance parameter. Return None if filled in, BLANK, or MISSING."""
    param = element.LookupParameter(param_name)
    if param is None:
        return MISSING
    try:
        if param.StorageType == StorageType.String:
            value = param.AsString()
        elif param.StorageType == StorageType.ElementId:
            value = None if param.AsElementId() == ElementId.InvalidElementId else param.AsValueString()
        else:
            value = param.AsValueString() if param.HasValue else None
    except Exception:
        value = None
    if value is None or not value.strip():
        return BLANK
    return None


def is_visible_in_temp_mode(view, element):
    try:
        return view.IsElementVisibleInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate, element.Id)
    except Exception:
        return True


def collect_elements(view, category_filter):
    selected_ids = uidoc.Selection.GetElementIds()
    if selected_ids.Count > 0:
        elements = (
            FilteredElementCollector(doc, selected_ids)
            .WherePasses(category_filter)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        return list(elements), "selection"

    elements = list(
        FilteredElementCollector(doc, view.Id)
        .WherePasses(category_filter)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    if view.IsTemporaryHideIsolateActive():
        elements = [e for e in elements if is_visible_in_temp_mode(view, e)]
    return elements, "active view"


# ---------------------------------------------------------------- main

def main():
    view = doc.ActiveView
    if view is None or view.IsTemplate:
        forms.alert("Open a model view before running this check.", title=TITLE)
        return

    categories, category_names = get_categories()
    elements, scope_label = collect_elements(view, ElementMulticategoryFilter(categories))
    if not elements:
        forms.alert("No duct items found in the {0}.".format(scope_label), title=TITLE)
        return

    # counts[(check label, category label, state)] = n
    counts = {}
    flagged = []
    for elem in elements:
        cat_label = category_names.get(elem.Category.Id.IntegerValue, elem.Category.Name)
        is_flagged = False
        for check_label, param_name in CHECKS:
            state = param_state(elem, param_name)
            if state is None:
                continue
            key = (check_label, cat_label, state)
            counts[key] = counts.get(key, 0) + 1
            if state == BLANK:
                is_flagged = True
        if is_flagged:
            flagged.append(elem)

    # ---- summary text
    lines = ["Checked {0} duct items in the {1}.".format(len(elements), scope_label), ""]
    any_blank = False
    for check_label, _ in CHECKS:
        rows = [(cat, n) for (chk, cat, state), n in sorted(counts.items())
                if chk == check_label and state == BLANK]
        if rows:
            any_blank = True
            lines.append("{0} is blank:".format(check_label))
            for cat, n in rows:
                lines.append("    {0}: {1}".format(cat, n))
            lines.append("")

    missing_rows = [(chk, cat, n) for (chk, cat, state), n in sorted(counts.items()) if state == MISSING]
    if missing_rows:
        lines.append("No parameter on these (not isolated):")
        for chk, cat, n in missing_rows:
            lines.append("    {0} - no {1} parameter: {2}".format(cat, chk, n))
        lines.append("")

    if not any_blank:
        lines.insert(0, "No QC issues found.\n")
        forms.alert("\n".join(lines).strip(), title=TITLE)
        return

    # ---- isolate + select flagged elements
    ids = List[ElementId]([e.Id for e in flagged])
    tx = Transaction(doc, "Sheet Metal QC - Isolate Issues")
    tx.Start()
    try:
        view.IsolateElementsTemporary(ids)
        tx.Commit()
        lines.append("{0} elements with issues are temporarily isolated and selected.".format(len(flagged)))
    except Exception as ex:
        tx.RollBack()
        lines.append("{0} elements with issues are selected (could not isolate: {1}).".format(len(flagged), ex))

    try:
        uidoc.Selection.SetElementIds(ids)
    except Exception:
        pass

    forms.alert("\n".join(lines).strip(), title=TITLE, warn_icon=True)


if __name__ == "__main__":
    main()
