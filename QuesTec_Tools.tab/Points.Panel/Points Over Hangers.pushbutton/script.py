# -*- coding: utf-8 -*-
"""Place points over hanger pipe accessories filtered by BOP."""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Element,
    ElementId,
    ElementTransformUtils,
    FamilyInstance,
    FamilySymbol,
    FilteredElementCollector,
    StorageType,
    Transaction,
    XYZ,
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import TaskDialog
from pyrevit import forms


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TARGET_FAMILY_NAME = "SSW Layout Point"
TARGET_CATEGORY = BuiltInCategory.OST_PipeAccessory


def safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def get_type_name(symbol):
    try:
        name = symbol.Name
        if name:
            return safe_str(name)
    except Exception:
        pass

    try:
        param = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param and param.HasValue:
            name = param.AsString()
            if name:
                return safe_str(name)
    except Exception:
        pass

    lookup = symbol.LookupParameter("Type Name")
    if lookup and lookup.HasValue:
        name = lookup.AsString()
        if name:
            return safe_str(name)

    return ""


def get_family_name(symbol):
    try:
        family_name = symbol.FamilyName
        if family_name:
            return safe_str(family_name)
    except Exception:
        pass

    try:
        if symbol.Family is not None and symbol.Family.Name:
            return safe_str(symbol.Family.Name)
    except Exception:
        pass

    return ""


class SymbolOption(object):
    def __init__(self, symbol):
        self.symbol = symbol
        self.name = "{0} : {1}".format(get_family_name(symbol), get_type_name(symbol))


def get_mark_parameter(element):
    return element.LookupParameter("Mark")


def has_bop_parameter(element):
    param = element.LookupParameter("BOP")
    return param is not None


def get_selected_elements():
    selected_ids = uidoc.Selection.GetElementIds()
    if not selected_ids:
        return []

    elements = []
    for elem_id in selected_ids:
        elem = doc.GetElement(elem_id)
        if isinstance(elem, Element):
            elements.append(elem)
    return elements


def get_visible_elements_in_active_view():
    active_view = doc.ActiveView
    return list(FilteredElementCollector(doc, active_view.Id).WhereElementIsNotElementType().ToElements())


def is_pipe_accessory(element):
    if not isinstance(element, FamilyInstance):
        return False
    if element.Category is None:
        return False
    return element.Category.Id.IntegerValue == int(TARGET_CATEGORY)


def get_hangers_from_scope(scope_elements):
    hangers = []
    for elem in scope_elements:
        if not is_pipe_accessory(elem):
            continue
        if not has_bop_parameter(elem):
            continue
        hangers.append(elem)
    return hangers


def get_element_center_point(element):
    location = element.Location
    if location is not None:
        if hasattr(location, "Point") and location.Point is not None:
            return location.Point
        if hasattr(location, "Curve") and location.Curve is not None:
            return location.Curve.Evaluate(0.5, True)

    bbox = element.get_BoundingBox(None)
    if bbox is not None:
        return XYZ(
            (bbox.Min.X + bbox.Max.X) / 2.0,
            (bbox.Min.Y + bbox.Max.Y) / 2.0,
            (bbox.Min.Z + bbox.Max.Z) / 2.0,
        )

    bbox_view = element.get_BoundingBox(doc.ActiveView)
    if bbox_view is not None:
        return XYZ(
            (bbox_view.Min.X + bbox_view.Max.X) / 2.0,
            (bbox_view.Min.Y + bbox_view.Max.Y) / 2.0,
            (bbox_view.Min.Z + bbox_view.Max.Z) / 2.0,
        )

    return None


def get_absolute_element_point(element):
    location = element.Location
    if location is not None:
        if hasattr(location, "Point") and location.Point is not None:
            return location.Point
        if hasattr(location, "Curve") and location.Curve is not None:
            return location.Curve.Evaluate(0.5, True)

    return get_element_center_point(element)


def get_level_by_id(level_id):
    if level_id is None or level_id == ElementId.InvalidElementId:
        return None

    level = doc.GetElement(level_id)
    if level is not None and hasattr(level, "Elevation"):
        return level

    return None


def get_hanger_level(hanger):
    try:
        level = get_level_by_id(hanger.LevelId)
        if level is not None:
            return level, "LevelId"
    except Exception:
        pass

    for bip, source_name in [
        (BuiltInParameter.FAMILY_LEVEL_PARAM, "FAMILY_LEVEL_PARAM"),
        (BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM, "INSTANCE_REFERENCE_LEVEL_PARAM"),
        (BuiltInParameter.SCHEDULE_LEVEL_PARAM, "SCHEDULE_LEVEL_PARAM"),
    ]:
        try:
            param = hanger.get_Parameter(bip)
            if param and param.HasValue:
                level = get_level_by_id(param.AsElementId())
                if level is not None:
                    return level, source_name
        except Exception:
            pass

    return None, None


def get_hanger_elevation_from_level(hanger, level):
    for bip, source_name in [
        (BuiltInParameter.INSTANCE_ELEVATION_PARAM, "INSTANCE_ELEVATION_PARAM"),
        (BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM, "INSTANCE_FREE_HOST_OFFSET_PARAM"),
    ]:
        try:
            param = hanger.get_Parameter(bip)
            if param and param.HasValue and param.StorageType == StorageType.Double:
                return param.AsDouble(), source_name
        except Exception:
            pass

    for param_name in ["Elevation from Level", "Offset from Host", "Offset"]:
        try:
            param = hanger.LookupParameter(param_name)
            if param and param.HasValue and param.StorageType == StorageType.Double:
                return param.AsDouble(), param_name
        except Exception:
            pass

    absolute_point = get_absolute_element_point(hanger)
    if level is not None and absolute_point is not None:
        return absolute_point.Z - level.Elevation, "absolute_point.Z - level.Elevation"

    return None, None


def get_target_point_for_hanger(hanger):
    absolute_point = get_absolute_element_point(hanger)
    if absolute_point is None:
        return None, None, None, None, None

    level, level_source = get_hanger_level(hanger)
    if level is None:
        return absolute_point, None, None, None, level_source

    elevation_from_level, offset_source = get_hanger_elevation_from_level(hanger, level)
    if elevation_from_level is None:
        return absolute_point, level, None, offset_source, level_source

    target_point = XYZ(absolute_point.X, absolute_point.Y, level.Elevation + elevation_from_level)
    return target_point, level, elevation_from_level, offset_source, level_source


def get_target_family_symbols():
    symbols = list(
        FilteredElementCollector(doc)
        .OfClass(FamilySymbol)
        .WhereElementIsElementType()
        .ToElements()
    )
    matches = [s for s in symbols if get_family_name(s) == TARGET_FAMILY_NAME]
    return matches


def choose_preferred_symbol(symbols):
    if not symbols:
        return None

    for symbol in symbols:
        type_name = get_type_name(symbol).lower()
        if "control" in type_name and "point" in type_name:
            return symbol

    return symbols[0]


def get_pipe_accessory_symbols():
    symbols = list(
        FilteredElementCollector(doc)
        .OfCategory(TARGET_CATEGORY)
        .OfClass(FamilySymbol)
        .WhereElementIsElementType()
        .ToElements()
    )

    symbols_sorted = sorted(symbols, key=lambda s: "{0}:{1}".format(get_family_name(s), get_type_name(s)))
    return symbols_sorted


def pick_fallback_symbol_from_pipe_accessories():
    symbols = get_pipe_accessory_symbols()
    if not symbols:
        return None

    options = [SymbolOption(sym) for sym in symbols]
    selected = forms.SelectFromList.show(
        options,
        title="Select Family Type to Place",
        button_name="Use Selected Type",
        name_attr="name",
        multiselect=False,
    )

    if selected is None:
        return None

    if isinstance(selected, list):
        if not selected:
            return None
        return selected[0].symbol

    return selected.symbol


def ensure_symbol_active(symbol):
    if symbol.IsActive:
        return

    tx = Transaction(doc, "Activate Point Family Symbol")
    tx.Start()
    try:
        symbol.Activate()
        doc.Regenerate()
        tx.Commit()
    except Exception:
        tx.RollBack()
        raise


def set_mark_to_hanger_id(point_instance, hanger):
    mark_param = get_mark_parameter(point_instance)
    if mark_param is None or mark_param.IsReadOnly:
        return False

    hanger_id_value = str(hanger.Id.IntegerValue)
    if mark_param.StorageType == StorageType.String:
        mark_param.Set(hanger_id_value)
        return True

    return False


def set_instance_comments(instance, comments_value):
    comments_param = instance.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if comments_param is None or comments_param.IsReadOnly:
        return False

    comments_param.Set(comments_value)
    return True


def create_point_instance(symbol, point, level=None):
    if level is None:
        active_view = doc.ActiveView
        level = getattr(active_view, "GenLevel", None)

    if level is not None:
        try:
            placement_point = XYZ(point.X, point.Y, level.Elevation)
            return doc.Create.NewFamilyInstance(placement_point, symbol, level, StructuralType.NonStructural)
        except Exception:
            pass

    return doc.Create.NewFamilyInstance(point, symbol, StructuralType.NonStructural)


def set_instance_level(instance, level):
    if instance is None or level is None:
        return

    for bip in [
        BuiltInParameter.FAMILY_LEVEL_PARAM,
        BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
        BuiltInParameter.SCHEDULE_LEVEL_PARAM,
    ]:
        try:
            param = instance.get_Parameter(bip)
            if param and not param.IsReadOnly and param.StorageType == StorageType.ElementId:
                param.Set(level.Id)
                return
        except Exception:
            pass


def match_instance_elevation_to_point(instance, target_point, level=None, elevation_from_level=None):
    if instance is None or target_point is None:
        return

    set_instance_level(instance, level)
    try:
        doc.Regenerate()
    except Exception:
        pass

    location = instance.Location
    if location is None or not hasattr(location, "Point") or location.Point is None:
        return

    current_point = location.Point
    delta_z = target_point.Z - current_point.Z

    if abs(delta_z) < 1e-9:
        return

    try:
        location.Move(XYZ(0.0, 0.0, delta_z))
        return
    except Exception:
        pass

    try:
        ElementTransformUtils.MoveElement(doc, instance.Id, XYZ(0.0, 0.0, delta_z))
    except Exception:
        pass


def main():
    selected = get_selected_elements()
    scope_elements = selected if selected else get_visible_elements_in_active_view()

    hangers = get_hangers_from_scope(scope_elements)
    if not hangers:
        TaskDialog.Show("Points Over Hangers", "No pipe accessories with a BOP parameter were found in the current scope.")
        return

    target_symbols = get_target_family_symbols()
    point_symbol = choose_preferred_symbol(target_symbols)

    if point_symbol is None:
        message = (
            "Family '{0}' is not loaded in this project.\n\n"
            "Select a family type from pipe accessories to place instead."
        ).format(TARGET_FAMILY_NAME)
        forms.alert(message, title="Points Over Hangers")
        point_symbol = pick_fallback_symbol_from_pipe_accessories()
        if point_symbol is None:
            TaskDialog.Show("Points Over Hangers", "No family type selected. Command cancelled.")
            return

    ensure_symbol_active(point_symbol)

    placed_count = 0
    created_instances = []
    tx = Transaction(doc, "Points Over Hangers")
    tx.Start()

    try:
        for hanger in hangers:
            target_point, hanger_level, elevation_from_level, _offset_source, _level_source = get_target_point_for_hanger(hanger)
            if target_point is None:
                continue

            point_instance = create_point_instance(point_symbol, target_point, hanger_level)
            if point_instance is None:
                continue

            match_instance_elevation_to_point(point_instance, target_point, hanger_level, elevation_from_level)
            set_mark_to_hanger_id(point_instance, hanger)
            created_instances.append(point_instance)
            placed_count += 1

        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        TaskDialog.Show("Points Over Hangers", "Command failed: {0}".format(str(ex)))
        return

    comments_value = forms.ask_for_string(
        prompt="Enter Comments text for created points (optional)",
        title="Points Over Hangers",
        default=""
    )

    comments_applied_count = 0
    if comments_value is not None and comments_value.strip() != "":
        tx_comments = Transaction(doc, "Set Comments on Hanger points")
        tx_comments.Start()
        try:
            for instance in created_instances:
                if set_instance_comments(instance, comments_value):
                    comments_applied_count += 1
            tx_comments.Commit()
        except Exception:
            tx_comments.RollBack()
            raise

    TaskDialog.Show(
        "Points Over Hangers",
        "Placed {0} points from {1} hangers. Comments applied to {2} points.".format(
            placed_count,
            len(hangers),
            comments_applied_count,
        ),
    )


if __name__ == "__main__":
    main()
