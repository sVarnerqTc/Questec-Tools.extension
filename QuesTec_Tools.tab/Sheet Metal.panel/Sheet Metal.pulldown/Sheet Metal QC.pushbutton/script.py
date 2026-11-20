# -*- coding: utf-8 -*-
"""Sheet Metal QC: find duct items with a blank Material or Specification Name
(both instance parameters under Identity Data).

Categories checked: Ducts, Duct Fittings, Flex Ducts,
Fabrication Ductwork.

Scope: the current selection if there is one; otherwise everything visible in
the active view (honoring any temporary hide/isolate already applied).

Also checks duct fittings in the "Radius Bend" family: the Angle must be
between 44 and 46 or between 89 and 91 degrees.

Elements with a blank value or a bad bend angle are temporarily isolated and selected, and a
summary of the issues is shown. Items with the "Bead and Crimp" instance
parameter checked skip the Material / Specification Name checks, but still
get the Radius Bend angle check. Elements that don't have the Material or
Specification Name parameter at all
are counted in the summary but not isolated.
"""

import math

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

# Items with this Yes/No instance parameter checked skip the Material /
# Specification Name checks (the Radius Bend angle check still applies).
SKIP_YES_NO_PARAM = "Bead and Crimp"

# Radius Bend angle check: the Angle must fall in one of these ranges (degrees).
ANGLE_FAMILY = "Radius Bend"
ANGLE_PARAM = "Angle"
ANGLE_RANGES = [(44.0, 46.0), (89.0, 91.0)]

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


def is_skipped(element):
    """True if the Bead and Crimp instance parameter is checked."""
    param = element.LookupParameter(SKIP_YES_NO_PARAM)
    if param is None or not param.HasValue:
        return False
    try:
        if param.StorageType == StorageType.Integer:
            return param.AsInteger() == 1
        value = (param.AsString() or param.AsValueString() or "").strip().lower()
        return value in ("yes", "true", "1")
    except Exception:
        return False


def get_family_name(element):
    try:
        return element.Symbol.FamilyName
    except Exception:
        return ""


def bad_bend_angle(element):
    """For 'Radius Bend' fittings: return the angle in degrees if it is outside
    the allowed ranges, otherwise None."""
    if get_family_name(element) != ANGLE_FAMILY:
        return None
    param = element.LookupParameter(ANGLE_PARAM)
    if param is None or not param.HasValue or param.StorageType != StorageType.Double:
        return None
    degrees = math.degrees(param.AsDouble())
    for low, high in ANGLE_RANGES:
        if low <= degrees <= high:
            return None
    return degrees


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
    skipped = 0
    bad_angles = []  # (element, degrees)
    for elem in elements:
        cat_label = category_names.get(elem.Category.Id.IntegerValue, elem.Category.Name)
        is_flagged = False

        # Radius Bend angle check applies to every item, Bead and Crimp or not.
        angle = bad_bend_angle(elem)
        if angle is not None:
            bad_angles.append((elem, angle))
            is_flagged = True

        # Bead and Crimp items skip only the Material / Specification Name checks.
        if is_skipped(elem):
            skipped += 1
            if is_flagged:
                flagged.append(elem)
            continue

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
    lines = ["Checked {0} duct items in the {1}.".format(len(elements), scope_label)]
    if skipped:
        lines.append("Material / Specification Name not checked on {0} with \"{1}\" checked.".format(
            skipped, SKIP_YES_NO_PARAM))
    lines.append("")
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

    if bad_angles:
        any_blank = True
        lines.append("{0} angle outside 44-46 or 89-91 degrees: {1}".format(ANGLE_FAMILY, len(bad_angles)))
        by_angle = {}
        for _, deg in bad_angles:
            key = round(deg, 2)
            by_angle[key] = by_angle.get(key, 0) + 1
        for deg in sorted(by_angle):
            lines.append(u"    {0:.2f}\u00b0: {1}".format(deg, by_angle[deg]))
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
