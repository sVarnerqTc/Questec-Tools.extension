# -*- coding: utf-8 -*-
"""Temporarily isolate elements in the active view that have no
'QTC BOM Description' and no 'Alternate Description II' (instance or type).

Categories checked: Pipes, Pipe Fittings, Pipe Accessories, Mechanical Equipment,
Plumbing Fixtures, Plumbing Equipment.
"""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    ElementMulticategoryFilter,
    FilteredElementCollector,
    StorageType,
    Transaction,
    TemporaryViewMode,
)
from System.Collections.Generic import List
from Autodesk.Revit.UI import TaskDialog


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TITLE = "Check BOM Descriptions"
PARAM_NAMES = ["QTC BOM Description", "Alternate Description II"]

CATEGORY_NAMES = [
    "OST_PipeCurves",
    "OST_PipeFitting",
    "OST_PipeAccessory",
    "OST_MechanicalEquipment",
    "OST_PlumbingFixtures",
    "OST_PlumbingEquipment",  # Revit 2024+; skipped automatically on older versions
]


def get_categories():
    cats = List[BuiltInCategory]()
    for name in CATEGORY_NAMES:
        bic = getattr(BuiltInCategory, name, None)
        if bic is not None:
            cats.Add(bic)
    return cats


def param_has_text(element, param_name):
    if element is None:
        return False
    param = element.LookupParameter(param_name)
    if param is None or not param.HasValue:
        return False
    try:
        if param.StorageType == StorageType.String:
            value = param.AsString()
        else:
            value = param.AsValueString()
    except Exception:
        value = None
    return bool(value and value.strip())


def has_description(element):
    elem_type = None
    try:
        type_id = element.GetTypeId()
        if type_id is not None and type_id != ElementId.InvalidElementId:
            elem_type = doc.GetElement(type_id)
    except Exception:
        elem_type = None

    for source in (element, elem_type):
        for name in PARAM_NAMES:
            if param_has_text(source, name):
                return True
    return False


def main():
    view = doc.ActiveView
    if view is None or view.IsTemplate:
        TaskDialog.Show(TITLE, "Open a model view before running this check.")
        return

    elements = list(
        FilteredElementCollector(doc, view.Id)
        .WherePasses(ElementMulticategoryFilter(get_categories()))
        .WhereElementIsNotElementType()
        .ToElements()
    )

    if not elements:
        TaskDialog.Show(TITLE, "No pipes, fittings, accessories, equipment or fixtures found in the active view.")
        return

    missing = [e for e in elements if not has_description(e)]

    if not missing:
        TaskDialog.Show(
            TITLE,
            "All {0} elements checked have a QTC BOM Description or Alternate Description II.".format(len(elements)),
        )
        return

    ids = List[ElementId]([e.Id for e in missing])

    tx = Transaction(doc, "Isolate Missing BOM Descriptions")
    tx.Start()
    try:
        if view.IsTemporaryHideIsolateActive():
            view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
        view.IsolateElementsTemporary(ids)
        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        TaskDialog.Show(TITLE, "Could not isolate elements: {0}".format(ex))
        return

    uidoc.Selection.SetElementIds(ids)

    TaskDialog.Show(
        TITLE,
        "{0} of {1} elements are missing both 'QTC BOM Description' and 'Alternate Description II'.\n\n"
        "They are temporarily isolated and selected in the active view.".format(len(missing), len(elements)),
    )


if __name__ == "__main__":
    main()
