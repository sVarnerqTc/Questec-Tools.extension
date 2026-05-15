# -*- coding: utf-8 -*-

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB.Plumbing import PipingSystemType
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


def _get_system_abbreviations(system_types):
    """Return a set of abbreviations for the given system type names."""
    abbreviations = set()
    system_type_collector = (
        DB.FilteredElementCollector(doc)
        .OfClass(PipingSystemType)
        .ToElements()
    )
    for st in system_type_collector:
        try:
            name_param = st.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
            st_name = (name_param.AsString() if (name_param and name_param.HasValue) else None) or st.Name
        except Exception:
            continue
        if st_name in system_types:
            abbrev_param = st.LookupParameter("Abbreviation")
            if abbrev_param and abbrev_param.HasValue:
                value = abbrev_param.AsString() or abbrev_param.AsValueString()
                if value and value.strip():
                    abbreviations.add(value.strip())
    return abbreviations


def _collect_hangers(system_abbreviations):
    """Collect pipe accessories that have a BOP parameter and whose
    Support Discipline parameter contains one of the system abbreviations."""
    element_ids = []
    seen = set()

    collector = (
        DB.FilteredElementCollector(doc, active_view.Id)
        .OfCategory(DB.BuiltInCategory.OST_PipeAccessory)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    for element in collector:
        bop_param = element.LookupParameter("BOP")
        if not bop_param:
            continue

        discipline_param = element.LookupParameter("Support Discipline")
        if not discipline_param or not discipline_param.HasValue:
            continue

        discipline_value = discipline_param.AsString() or discipline_param.AsValueString() or ""
        discipline_value = discipline_value.strip()

        for abbrev in system_abbreviations:
            if abbrev and discipline_value == abbrev:
                int_id = element.Id.IntegerValue
                if int_id not in seen:
                    seen.add(int_id)
                    element_ids.append(element.Id)
                break

    return element_ids


def _collect_matching_elements(system_types, include_mech_equipment, include_hangers):
    pipe_categories = [
        DB.BuiltInCategory.OST_PipeCurves,
        DB.BuiltInCategory.OST_PipeAccessory,
        DB.BuiltInCategory.OST_PipeFitting,
    ]

    element_ids = []
    seen = set()

    for category in pipe_categories:
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

    if include_mech_equipment:
        mech_collector = (
            DB.FilteredElementCollector(doc, active_view.Id)
            .OfCategory(DB.BuiltInCategory.OST_MechanicalEquipment)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        for element in mech_collector:
            int_id = element.Id.IntegerValue
            if int_id not in seen:
                seen.add(int_id)
                element_ids.append(element.Id)

    if include_hangers:
        system_abbreviations = _get_system_abbreviations(system_types)
        hanger_ids = _collect_hangers(system_abbreviations)
        for eid in hanger_ids:
            int_id = eid.IntegerValue
            if int_id not in seen:
                seen.add(int_id)
                element_ids.append(eid)

    # Always include section box elements so they are not hidden by isolation
    section_box_collector = (
        DB.FilteredElementCollector(doc, active_view.Id)
        .OfCategory(DB.BuiltInCategory.OST_SectionBox)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    for element in section_box_collector:
        int_id = element.Id.IntegerValue
        if int_id not in seen:
            seen.add(int_id)
            element_ids.append(element.Id)

    return element_ids


def main():
    config = script.get_config()
    include_mech_equipment = getattr(config, "include_mechanical_equipment", True)
    include_hangers = getattr(config, "include_hangers", True)

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
        include_mech_equipment,
        include_hangers
    )

    if not matching_ids:
        forms.alert(
            "No matching pipe elements were found in the active view.",
            title="By System",
            exitscript=True
        )

    with revit.Transaction("Temporary Isolate By System"):
        active_view.IsolateElementsTemporary(List[DB.ElementId](matching_ids))


if __name__ == "__main__":
    main()
