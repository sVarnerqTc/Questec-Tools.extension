# -*- coding: utf-8 -*-
"""Place layout points on both ends of every SL-Sleeves pipe in the active view.

If elements are selected when the command runs, only the selected pipes are used.
"""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Element,
    ElementId,
    ElementTransformUtils,
    FamilySymbol,
    FilteredElementCollector,
    StorageType,
    Transaction,
    XYZ,
)
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import TaskDialog
from pyrevit import forms


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TITLE = "Points On Sleeve Ends"
TARGET_SYSTEM_NAME = "SL-Sleeves"
TARGET_FAMILY_NAME = "SSW Layout Point"
FALLBACK_CATEGORY = BuiltInCategory.OST_PipeAccessory
DUPLICATE_TOLERANCE = 1.0 / 12.0 / 64.0  # 1/64" in feet


# ---------------------------------------------------------------- helpers

def safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def norm(text):
    return safe_str(text).strip().lower()


def get_type_name(symbol):
    try:
        if symbol.Name:
            return safe_str(symbol.Name)
    except Exception:
        pass
    try:
        param = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if param and param.HasValue and param.AsString():
            return safe_str(param.AsString())
    except Exception:
        pass
    return ""


def get_family_name(symbol):
    try:
        if symbol.FamilyName:
            return safe_str(symbol.FamilyName)
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


# ---------------------------------------------------------------- scope / filtering

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


def get_pipes_in_active_view():
    return list(
        FilteredElementCollector(doc, doc.ActiveView.Id)
        .OfClass(Pipe)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def get_param_text(element, bip):
    try:
        param = element.get_Parameter(bip)
        if param is None or not param.HasValue:
            return ""
        if param.StorageType == StorageType.String:
            return safe_str(param.AsString())
        return safe_str(param.AsValueString())
    except Exception:
        return ""


def get_pipe_system_names(pipe):
    """Return every system label on the pipe (type, name, abbreviation)."""
    names = set()

    # Piping System Type (e.g. "SL-Sleeves")
    try:
        param = pipe.get_Parameter(BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
        if param and param.HasValue:
            names.add(norm(param.AsValueString()))
            type_elem = doc.GetElement(param.AsElementId())
            if type_elem is not None:
                names.add(norm(Element.Name.GetValue(type_elem)))
    except Exception:
        pass

    names.add(norm(get_param_text(pipe, BuiltInParameter.RBS_SYSTEM_NAME_PARAM)))
    names.add(norm(get_param_text(pipe, BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM)))

    names.discard("")
    return names


def is_sleeve_pipe(element):
    if not isinstance(element, Pipe):
        return False
    return norm(TARGET_SYSTEM_NAME) in get_pipe_system_names(element)


# ---------------------------------------------------------------- geometry

def get_pipe_endpoints(pipe):
    location = pipe.Location
    if location is None or not hasattr(location, "Curve") or location.Curve is None:
        return []
    curve = location.Curve
    return [curve.GetEndPoint(0), curve.GetEndPoint(1)]


def get_level_by_id(level_id):
    if level_id is None or level_id == ElementId.InvalidElementId:
        return None
    level = doc.GetElement(level_id)
    if level is not None and hasattr(level, "Elevation"):
        return level
    return None


def get_pipe_level(pipe):
    try:
        level = pipe.ReferenceLevel
        if level is not None:
            return level
    except Exception:
        pass

    try:
        level = get_level_by_id(pipe.LevelId)
        if level is not None:
            return level
    except Exception:
        pass

    try:
        param = pipe.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM)
        if param and param.HasValue:
            return get_level_by_id(param.AsElementId())
    except Exception:
        pass

    return getattr(doc.ActiveView, "GenLevel", None)


def is_duplicate(point, existing_points):
    for other in existing_points:
        if point.DistanceTo(other) <= DUPLICATE_TOLERANCE:
            return True
    return False


# ---------------------------------------------------------------- point family

def get_target_family_symbols():
    symbols = (
        FilteredElementCollector(doc)
        .OfClass(FamilySymbol)
        .WhereElementIsElementType()
        .ToElements()
    )
    return [s for s in symbols if get_family_name(s) == TARGET_FAMILY_NAME]


def choose_preferred_symbol(symbols):
    if not symbols:
        return None
    for symbol in symbols:
        type_name = get_type_name(symbol).lower()
        if "control" in type_name and "point" in type_name:
            return symbol
    return symbols[0]


def pick_fallback_symbol():
    symbols = list(
        FilteredElementCollector(doc)
        .OfCategory(FALLBACK_CATEGORY)
        .OfClass(FamilySymbol)
        .WhereElementIsElementType()
        .ToElements()
    )
    if not symbols:
        return None

    symbols = sorted(symbols, key=lambda s: "{0}:{1}".format(get_family_name(s), get_type_name(s)))
    selected = forms.SelectFromList.show(
        [SymbolOption(s) for s in symbols],
        title="Select Family Type to Place",
        button_name="Use Selected Type",
        name_attr="name",
        multiselect=False,
    )
    if selected is None:
        return None
    if isinstance(selected, list):
        return selected[0].symbol if selected else None
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


def create_point_instance(symbol, point, level=None):
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


def match_instance_elevation_to_point(instance, target_point, level=None):
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

    delta_z = target_point.Z - location.Point.Z
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


def set_point_mark(point_instance, mark_value):
    param = point_instance.LookupParameter("Mark")
    if param is None or param.IsReadOnly or param.StorageType != StorageType.String:
        return False
    param.Set(mark_value)
    return True


def set_instance_comments(instance, comments_value):
    param = instance.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if param is None or param.IsReadOnly:
        return False
    param.Set(comments_value)
    return True


# ---------------------------------------------------------------- main

def main():
    selected = get_selected_elements()
    using_selection = bool(selected)
    scope = selected if using_selection else get_pipes_in_active_view()
    scope_label = "selection" if using_selection else "active view"

    sleeves = [e for e in scope if is_sleeve_pipe(e)]
    if not sleeves:
        TaskDialog.Show(
            TITLE,
            "No pipes on system '{0}' were found in the {1}.".format(TARGET_SYSTEM_NAME, scope_label),
        )
        return

    point_symbol = choose_preferred_symbol(get_target_family_symbols())
    if point_symbol is None:
        forms.alert(
            "Family '{0}' is not loaded in this project.\n\n"
            "Select a family type from pipe accessories to place instead.".format(TARGET_FAMILY_NAME),
            title=TITLE,
        )
        point_symbol = pick_fallback_symbol()
        if point_symbol is None:
            TaskDialog.Show(TITLE, "No family type selected. Command cancelled.")
            return

    ensure_symbol_active(point_symbol)

    created_instances = []
    placed_points = []
    skipped_duplicates = 0
    skipped_no_geometry = 0

    tx = Transaction(doc, TITLE)
    tx.Start()
    try:
        for pipe in sorted(sleeves, key=lambda p: p.Id.IntegerValue):
            endpoints = get_pipe_endpoints(pipe)
            if not endpoints:
                skipped_no_geometry += 1
                continue

            level = get_pipe_level(pipe)
            for index, end_point in enumerate(endpoints):
                if is_duplicate(end_point, placed_points):
                    skipped_duplicates += 1
                    continue

                instance = create_point_instance(point_symbol, end_point, level)
                if instance is None:
                    continue

                match_instance_elevation_to_point(instance, end_point, level)
                set_point_mark(instance, "{0}-{1}".format(pipe.Id.IntegerValue, index + 1))

                placed_points.append(end_point)
                created_instances.append(instance)

        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        TaskDialog.Show(TITLE, "Command failed: {0}".format(str(ex)))
        return

    comments_value = forms.ask_for_string(
        prompt="Enter Comments text for created points (optional)",
        title=TITLE,
        default="",
    )

    comments_applied = 0
    if created_instances and comments_value is not None and comments_value.strip() != "":
        tx_comments = Transaction(doc, "Set Comments on Sleeve points")
        tx_comments.Start()
        try:
            for instance in created_instances:
                if set_instance_comments(instance, comments_value):
                    comments_applied += 1
            tx_comments.Commit()
        except Exception:
            tx_comments.RollBack()
            raise

    lines = [
        "Sleeves found ({0}): {1}".format(scope_label, len(sleeves)),
        "Points placed: {0}".format(len(created_instances)),
    ]
    if skipped_duplicates:
        lines.append("Shared endpoints skipped: {0}".format(skipped_duplicates))
    if skipped_no_geometry:
        lines.append("Sleeves without a centerline skipped: {0}".format(skipped_no_geometry))
    lines.append("Comments applied to {0} points.".format(comments_applied))

    TaskDialog.Show(TITLE, "\n".join(lines))


if __name__ == "__main__":
    main()
