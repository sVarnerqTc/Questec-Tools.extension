# -*- coding: utf-8 -*-

from pyrevit import forms, revit, DB, script
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List


doc = revit.doc
uidoc = revit.uidoc
active_view = doc.ActiveView


def _get_selected_or_picked_elements():
    selected_ids = uidoc.Selection.GetElementIds()
    if selected_ids and selected_ids.Count > 0:
        return [doc.GetElement(eid) for eid in selected_ids]

    forms.alert(
        "No elements are currently selected. Select elements and click Finish.",
        title="By Upper Attachment"
    )

    try:
        picked_refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Select elements to read Upper Attachment, then click Finish"
        )
        return [doc.GetElement(r.ElementId) for r in picked_refs]
    except OperationCanceledException:
        return []


def _read_param_value(element, param_name):
    if element is None:
        return None

    param = element.LookupParameter(param_name)
    if not param or not param.HasValue:
        return None

    storage_type = param.StorageType

    if storage_type == DB.StorageType.String:
        value = param.AsString()
        if value and value.strip():
            return value.strip()

    if storage_type == DB.StorageType.ElementId:
        elem_id = param.AsElementId()
        if elem_id and elem_id != DB.ElementId.InvalidElementId:
            # Compare ElementId-backed values by integer id for consistency.
            return "id:{}".format(elem_id.IntegerValue)

    value_string = param.AsValueString()
    if value_string and value_string.strip():
        return value_string.strip()

    # Fallback for uncommon cases where AsString still returns data.
    raw_string = param.AsString()
    if raw_string and raw_string.strip():
        return raw_string.strip()

    return None


def _collect_matching_pipe_accessories(upper_attachment_values):
    matching_ids = []

    collector = (
        DB.FilteredElementCollector(doc, active_view.Id)
        .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    for element in collector:
        value = _read_param_value(element, "Upper Attachment")
        if value and value in upper_attachment_values:
            matching_ids.append(element.Id)

    return matching_ids


def main():
    seed_elements = _get_selected_or_picked_elements()
    if not seed_elements:
        forms.alert("No elements were selected.", title="By Upper Attachment", exitscript=True)

    upper_attachment_values = set()
    for element in seed_elements:
        value = _read_param_value(element, "Upper Attachment")
        if value:
            upper_attachment_values.add(value)

    if not upper_attachment_values:
        forms.alert(
            "None of the selected elements had a usable 'Upper Attachment' value.",
            title="By Upper Attachment",
            exitscript=True
        )

    matching_ids = _collect_matching_pipe_accessories(upper_attachment_values)
    if not matching_ids:
        forms.alert(
            "No pipe accessories with matching 'Upper Attachment' values were found in the active view.",
            title="By Upper Attachment",
            exitscript=True
        )

    with revit.Transaction("Temporary Isolate By Upper Attachment"):
        active_view.IsolateElementsTemporary(List[DB.ElementId](matching_ids))


if __name__ == "__main__":
    main()
