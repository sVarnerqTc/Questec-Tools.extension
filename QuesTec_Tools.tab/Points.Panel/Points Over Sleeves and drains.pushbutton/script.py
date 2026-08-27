# -*- coding: utf-8 -*-
"""Place points over sleeves and drains in the active view with sequential Mark values."""

import re

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

TARGET_FAMILY_NAME = "SSW Layout Point"
PIPE_ACCESSORY_CAT = BuiltInCategory.OST_PipeAccessory
PLUMBING_FIXTURE_CAT = BuiltInCategory.OST_PlumbingFixtures


class SymbolOption(object):
    def __init__(self, symbol):
        self.symbol = symbol
        self.name = "{0} : {1}".format(get_family_name(symbol), get_type_name(symbol))


def safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def get_type_name(symbol):
    try:
        if symbol.Name:
            return safe_str(symbol.Name)
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


def get_target_family_symbols():
    symbols = list(
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


def get_pipe_accessory_symbols():
    symbols = list(
        FilteredElementCollector(doc)
        .OfCategory(PIPE_ACCESSORY_CAT)
        .OfClass(FamilySymbol)
        .WhereElementIsElementType()
        .ToElements()
    )
    return sorted(symbols, key=lambda s: "{0}:{1}".format(get_family_name(s), get_type_name(s)))


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


def get_visible_elements_in_active_view():
    active_view = doc.ActiveView
    return list(FilteredElementCollector(doc, active_view.Id).WhereElementIsNotElementType().ToElements())


def is_family_instance_in_category(element, category):
    if not isinstance(element, FamilyInstance):
        return False
    if element.Category is None:
        return False
    return element.Category.Id.IntegerValue == int(category)


def get_instance_family_name(element):
    try:
        symbol = element.Symbol
        if symbol is not None:
            return get_family_name(symbol)
    except Exception:
        pass
    return ""


def is_drain(element):
    if not is_family_instance_in_category(element, PLUMBING_FIXTURE_CAT):
        return False

    name = get_instance_family_name(element).lower()
    return ("drain" in name) or ("cleanout" in name) or ("clean out" in name)


def is_sleeve(element):
    if not is_family_instance_in_category(element, PIPE_ACCESSORY_CAT):
        return False

    name = get_instance_family_name(element).lower()
    if "sleeve" not in name:
        return False

    if "extension" in name:
        return False

    if "deck clips" in name:
        return False

    return True


def get_type_mark(instance):
    symbol = None
    try:
        symbol = instance.Symbol
    except Exception:
        symbol = None

    if symbol is not None:
        try:
            param = symbol.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
            if param and param.HasValue:
                value = param.AsString()
                if value and value.strip():
                    return value.strip()
        except Exception:
            pass

        try:
            param = symbol.LookupParameter("Type Mark")
            if param and param.HasValue:
                value = param.AsString()
                if value and value.strip():
                    return value.strip()
        except Exception:
            pass

    return ""


def get_family_type_label(instance):
    symbol = None
    try:
        symbol = instance.Symbol
    except Exception:
        symbol = None

    if symbol is None:
        return "Unknown Family : Unknown Type"

    family_name = get_family_name(symbol) or "Unknown Family"
    type_name = get_type_name(symbol) or "Unknown Type"
    return "{0} : {1}".format(family_name, type_name)


def get_parameter_display_value(param):
    if param is None or not param.HasValue:
        return ""

    try:
        value_str = param.AsValueString()
        if value_str and value_str.strip():
            return value_str.strip()
    except Exception:
        pass

    try:
        if param.StorageType == StorageType.String:
            value_str = param.AsString()
            if value_str and value_str.strip():
                return value_str.strip()
    except Exception:
        pass

    return ""


def get_nom_pipe_size(instance):
    try:
        param = instance.LookupParameter("Nom Pipe Size")
        value = get_parameter_display_value(param)
        if value:
            return value
    except Exception:
        pass

    try:
        symbol = instance.Symbol
    except Exception:
        symbol = None

    if symbol is not None:
        try:
            param = symbol.LookupParameter("Nom Pipe Size")
            value = get_parameter_display_value(param)
            if value:
                return value
        except Exception:
            pass

    return ""


def normalize_nom_pipe_size(size_text):
    if not size_text:
        return ""

    value = safe_str(size_text)
    value = value.replace(" ", "")
    value = value.replace("/", "")
    value = value.replace('"', "")
    return value



def normalize_type_mark(type_mark_text):
    if not type_mark_text:
        return ""

    value = safe_str(type_mark_text)
    value = value.replace(" ", "")
    value = value.replace("-", "")
    value = value.replace("/", "")
    value = value.replace('"', "in")
    return value

def collect_targets_from_active_view():
    targets = []

    for elem in get_visible_elements_in_active_view():
        if not isinstance(elem, Element):
            continue

        if is_drain(elem):
            targets.append({
                "element": elem,
                "kind": "drain",
                "type_mark": get_type_mark(elem),
                "prefix": "",
            })
        elif is_sleeve(elem):
            targets.append({
                "element": elem,
                "kind": "sleeve",
                "type_mark": get_type_mark(elem),
                "prefix": "",
            })

    return targets


def get_level_by_id(level_id):
    if level_id is None or level_id == ElementId.InvalidElementId:
        return None

    level = doc.GetElement(level_id)
    if level is not None and hasattr(level, "Elevation"):
        return level

    return None


def get_source_level(source_element):
    try:
        level = get_level_by_id(source_element.LevelId)
        if level is not None:
            return level
    except Exception:
        pass

    for bip in [
        BuiltInParameter.FAMILY_LEVEL_PARAM,
        BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM,
        BuiltInParameter.SCHEDULE_LEVEL_PARAM,
    ]:
        try:
            param = source_element.get_Parameter(bip)
            if param and param.HasValue:
                level = get_level_by_id(param.AsElementId())
                if level is not None:
                    return level
        except Exception:
            pass

    return None


def get_source_offset_from_level(source_element):
    for bip in [
        BuiltInParameter.INSTANCE_ELEVATION_PARAM,
        BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
    ]:
        try:
            param = source_element.get_Parameter(bip)
            if param and param.HasValue and param.StorageType == StorageType.Double:
                return param.AsDouble()
        except Exception:
            pass

    for param_name in ["Elevation from Level", "Offset from Host", "Offset"]:
        try:
            param = source_element.LookupParameter(param_name)
            if param and param.HasValue and param.StorageType == StorageType.Double:
                return param.AsDouble()
        except Exception:
            pass

    return None


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


def get_target_point_for_source(source_element):
    absolute_point = get_absolute_element_point(source_element)
    if absolute_point is None:
        return None, None, None

    level = get_source_level(source_element)
    if level is None:
        return absolute_point, None, None

    elevation_from_level = get_source_offset_from_level(source_element)
    if elevation_from_level is None:
        return absolute_point, level, None

    target_point = XYZ(absolute_point.X, absolute_point.Y, level.Elevation + elevation_from_level)
    return target_point, level, elevation_from_level


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


def get_mark_parameter(element):
    return element.LookupParameter("Mark")


def set_point_mark(point_instance, mark_value):
    mark_param = get_mark_parameter(point_instance)
    if mark_param is None or mark_param.IsReadOnly:
        return False

    if mark_param.StorageType != StorageType.String:
        return False

    mark_param.Set(mark_value)
    return True


def set_instance_comments(instance, comments_value):
    comments_param = instance.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if comments_param is None or comments_param.IsReadOnly:
        return False

    comments_param.Set(comments_value)
    return True


def get_all_project_marks():
    values = []
    for elem in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements():
        param = get_mark_parameter(elem)
        if param is None or not param.HasValue:
            continue
        if param.StorageType != StorageType.String:
            continue

        mark = param.AsString()
        if mark and mark.strip():
            values.append(mark.strip())

    return values


def get_longest_matching_prefix(mark_value, prefixes):
    mark_lower = mark_value.lower()
    best = None
    for prefix in prefixes:
        if mark_lower.startswith(prefix.lower()):
            if best is None or len(prefix) > len(best):
                best = prefix
    return best


def get_highest_numbers_by_prefix(prefixes):
    highest = dict((p.lower(), 0) for p in prefixes)
    all_marks = get_all_project_marks()

    for mark in all_marks:
        prefix = get_longest_matching_prefix(mark, prefixes)
        if prefix is None:
            continue

        suffix = mark[len(prefix):]
        match = re.search(r"(\d+)\s*$", suffix)
        if not match:
            continue

        number = int(match.group(1))
        key = prefix.lower()
        if number > highest[key]:
            highest[key] = number

    return highest


def build_summary_lines(placed_by_prefix):
    lines = []
    for prefix, count in placed_by_prefix:
        lines.append("{0} {1} points placed".format(count, prefix))
    return lines


def main():
    targets = collect_targets_from_active_view()
    if not targets:
        TaskDialog.Show(
            "Points Over Sleeves and drains",
            "No matching drains or sleeves were found in the active view.",
        )
        return

    missing_type_marks = []
    missing_type_keys = set()
    for target in targets:
        clean_type_mark = normalize_type_mark(target["type_mark"])
        target["type_mark_clean"] = clean_type_mark
        if not clean_type_mark:
            elem = target["element"]
            label = get_family_type_label(elem)
            key = label.lower()
            if key in missing_type_keys:
                continue
            missing_type_keys.add(key)
            missing_type_marks.append(label)

    if missing_type_marks:
        message = "Type Mark is required on every matched drain/sleeve.\n\n"
        message += "Missing Type Mark for these family types:\n"
        message += "\n".join(missing_type_marks)
        message += "\n\nCommand aborted."
        TaskDialog.Show("Points Over Sleeves and drains", message)
        return

    missing_sleeve_sizes = []
    missing_sleeve_size_keys = set()
    for target in targets:
        if target["kind"] == "drain":
            target["prefix"] = target["type_mark_clean"]
            continue

        elem = target["element"]
        raw_size = get_nom_pipe_size(elem)
        clean_size = normalize_nom_pipe_size(raw_size)
        if not clean_size:
            label = get_family_type_label(elem)
            key = label.lower()
            if key not in missing_sleeve_size_keys:
                missing_sleeve_size_keys.add(key)
                missing_sleeve_sizes.append(label)
            continue

        target["prefix"] = "{0}in{1}".format(clean_size, target["type_mark_clean"])

    if missing_sleeve_sizes:
        message = "Nom Pipe Size is required on matched sleeves to build sleeve prefixes.\n\n"
        message += "Missing Nom Pipe Size for these family types:\n"
        message += "\n".join(missing_sleeve_sizes)
        message += "\n\nCommand aborted."
        TaskDialog.Show("Points Over Sleeves and drains", message)
        return

    target_symbols = get_target_family_symbols()
    point_symbol = choose_preferred_symbol(target_symbols)

    if point_symbol is None:
        message = (
            "Family '{0}' is not loaded in this project.\n\n"
            "Select a family type from pipe accessories to place instead."
        ).format(TARGET_FAMILY_NAME)
        forms.alert(message, title="Points Over Sleeves and drains")
        point_symbol = pick_fallback_symbol_from_pipe_accessories()
        if point_symbol is None:
            TaskDialog.Show("Points Over Sleeves and drains", "No family type selected. Command cancelled.")
            return

    ensure_symbol_active(point_symbol)

    ordered_targets = sorted(
        targets,
        key=lambda t: (t["prefix"].lower(), t["element"].Id.IntegerValue),
    )

    ordered_prefixes = []
    seen_prefixes = set()
    for target in ordered_targets:
        prefix = target["prefix"]
        key = prefix.lower()
        if key in seen_prefixes:
            continue
        seen_prefixes.add(key)
        ordered_prefixes.append(prefix)

    highest_numbers = get_highest_numbers_by_prefix(ordered_prefixes)
    next_numbers = dict((p.lower(), highest_numbers[p.lower()] + 1) for p in ordered_prefixes)

    placed_counts_map = dict((p.lower(), 0) for p in ordered_prefixes)
    created_instances = []

    tx = Transaction(doc, "Points Over Sleeves and drains")
    tx.Start()

    try:
        for target in ordered_targets:
            source = target["element"]
            prefix = target["prefix"]
            key = prefix.lower()

            target_point, level, _elevation_from_level = get_target_point_for_source(source)
            if target_point is None:
                continue

            point_instance = create_point_instance(point_symbol, target_point, level)
            if point_instance is None:
                continue

            match_instance_elevation_to_point(point_instance, target_point, level)

            mark_number = next_numbers[key]
            mark_value = "{0}{1}".format(prefix, mark_number)
            if not set_point_mark(point_instance, mark_value):
                raise Exception(
                    "Could not set Mark on point instance {0}.".format(point_instance.Id.IntegerValue)
                )

            created_instances.append(point_instance)
            next_numbers[key] += 1
            placed_counts_map[key] += 1

        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        TaskDialog.Show("Points Over Sleeves and drains", "Command failed: {0}".format(str(ex)))
        return

    comments_value = forms.ask_for_string(
        prompt="Enter Comments text for created points (optional)",
        title="Points Over Sleeves and drains",
        default=""
    )

    comments_applied_count = 0
    if comments_value is not None and comments_value.strip() != "":
        tx_comments = Transaction(doc, "Set Comments on Sleeve/Drain points")
        tx_comments.Start()
        try:
            for instance in created_instances:
                if set_instance_comments(instance, comments_value):
                    comments_applied_count += 1
            tx_comments.Commit()
        except Exception:
            tx_comments.RollBack()
            raise

    placed_by_prefix = []
    for prefix in ordered_prefixes:
        count = placed_counts_map[prefix.lower()]
        if count > 0:
            placed_by_prefix.append((prefix, count))

    if not placed_by_prefix:
        TaskDialog.Show(
            "Points Over Sleeves and drains",
            "No points were placed. Matched elements did not provide placeable points.",
        )
        return

    summary = "Placed point elements:\n\n"
    summary += "\n".join(build_summary_lines(placed_by_prefix))
    summary += "\n\nComments applied to {0} points.".format(comments_applied_count)

    TaskDialog.Show("Points Over Sleeves and drains", summary)


if __name__ == "__main__":
    main()
