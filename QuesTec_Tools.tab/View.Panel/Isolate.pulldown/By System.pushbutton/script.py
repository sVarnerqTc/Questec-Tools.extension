# -*- coding: utf-8 -*-

from pyrevit import forms, revit, DB, script
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List


doc = revit.doc
uidoc = revit.uidoc
active_view = doc.ActiveView


def _get_system_type_value(element):
    """Return a readable system type value for comparison."""
    if element is None:
        return None

    # Preferred path requested by user: read the "System Type" parameter.
    param = element.LookupParameter("System Type")
    if param and param.HasValue:
        value = param.AsString() or param.AsValueString()
        if value and value.strip():
            return value.strip()

    # Fallback for categories where the display parameter can differ.
    bip_candidates = [
        DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM,
        DB.BuiltInParameter.RBS_DUCT_SYSTEM_TYPE_PARAM,
        DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM,
    ]

    for bip in bip_candidates:
        try:
            bip_param = element.get_Parameter(bip)
            if bip_param and bip_param.HasValue:
                value = bip_param.AsString() or bip_param.AsValueString()
                if value and value.strip():
                    return value.strip()
        except Exception:
            continue

    return None


def _get_selected_or_picked_elements():
    selected_ids = uidoc.Selection.GetElementIds()
    if selected_ids and selected_ids.Count > 0:
        return [doc.GetElement(eid) for eid in selected_ids]

    forms.alert(
        "No elements are currently selected. Select system elements and click Finish.",
        title="By System"
    )

    try:
        picked_refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Select elements to define system type(s), then click Finish"
        )
        return [doc.GetElement(r.ElementId) for r in picked_refs]
    except OperationCanceledException:
        return []


def _collect_matching_elements(system_types, include_mech_equipment):
    categories = [
        DB.BuiltInCategory.OST_PipeCurves,
        DB.BuiltInCategory.OST_PipeAccessory,
        DB.BuiltInCategory.OST_PipeFitting,
    ]

    if include_mech_equipment:
        categories.append(DB.BuiltInCategory.OST_MechanicalEquipment)

    element_ids = []
    seen = set()

    for category in categories:
        collector = (
            DB.FilteredElementCollector(doc, active_view.Id)
            .OfCategory(category)
            .WhereElementIsNotElementType()
            .ToElements()
        )

        for element in collector:
            system_type = _get_system_type_value(element)
            if system_type in system_types:
                int_id = element.Id.IntegerValue
                if int_id not in seen:
                    seen.add(int_id)
                    element_ids.append(element.Id)

    return element_ids


def main():
    config = script.get_config()
    include_mech_equipment = getattr(config, "include_mechanical_equipment", True)

    seed_elements = _get_selected_or_picked_elements()
    if not seed_elements:
        forms.alert("No elements were selected.", title="By System", exitscript=True)

    selected_system_types = set()
    for element in seed_elements:
        system_type_value = _get_system_type_value(element)
        if system_type_value:
            selected_system_types.add(system_type_value)

    if not selected_system_types:
        forms.alert(
            "None of the selected elements had a usable 'System Type' value.",
            title="By System",
            exitscript=True
        )

    matching_ids = _collect_matching_elements(
        selected_system_types,
        include_mech_equipment
    )

    if not matching_ids:
        forms.alert(
            "No matching pipe elements were found in the active view.",
            title="By System",
            exitscript=True
        )

    with revit.Transaction("Temporary Isolate By System"):
        active_view.IsolateElementsTemporary(List[DB.ElementId](matching_ids))

    action_text = "included" if include_mech_equipment else "hidden"
    print(
        "Isolated {0} element(s) in view '{1}' using system type(s): {2}. "
        "Mechanical equipment is {3} by Shift config.".format(
            len(matching_ids),
            active_view.Name,
            ", ".join(sorted(selected_system_types)),
            action_text
        )
    )


if __name__ == "__main__":
    main()
