import clr
import re

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import TaskDialog
from pyrevit import forms


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

CONTROL_POINT_FAMILY_NAME = "SSW Control Point"


def sanitize_name(value):
    return re.sub(r'[^A-Za-z0-9]+', '', value or "")


def get_control_point_symbol():
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
    for symbol in collector:
        if symbol.FamilyName == CONTROL_POINT_FAMILY_NAME:
            return symbol
    return None


def get_visible_grids(active_view):
    collector = FilteredElementCollector(doc, active_view.Id).OfClass(Grid)
    return list(collector)


def get_grid_intersections(grids):
    intersections = []
    seen_keys = set()

    for i in range(len(grids)):
        grid_a = grids[i]
        curve_a = grid_a.Curve
        if curve_a is None:
            continue

        for j in range(i + 1, len(grids)):
            grid_b = grids[j]
            curve_b = grid_b.Curve
            if curve_b is None:
                continue

            results_ref = clr.Reference[IntersectionResultArray]()
            curve_a.Intersect(curve_b, results_ref)

            results = results_ref.Value
            if results is None or results.Size == 0:
                continue

            for result_index in range(results.Size):
                point = results.get_Item(result_index).XYZPoint
                if point is None:
                    continue

                # Deduplicate almost-identical intersections from overlapping geometry cases.
                # XY-based key is sufficient for plan placement and avoids losing matches due to tiny Z drift.
                key = "{0:.6f}|{1:.6f}".format(point.X, point.Y)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                names = sorted([grid_a.Name, grid_b.Name])
                base_name = sanitize_name("{0}{1}".format(names[0], names[1]))
                if not base_name:
                    base_name = "GridIntersection"

                intersections.append((point, base_name))

    return intersections


def get_offsets(style, distance_feet):
    if style == "+":
        return [
            (XYZ(0, distance_feet, 0), "N"),
            (XYZ(0, -distance_feet, 0), "S"),
            (XYZ(distance_feet, 0, 0), "E"),
            (XYZ(-distance_feet, 0, 0), "W"),
        ]

    return [
        (XYZ(-distance_feet, distance_feet, 0), "NW"),
        (XYZ(distance_feet, distance_feet, 0), "NE"),
        (XYZ(distance_feet, -distance_feet, 0), "SE"),
        (XYZ(-distance_feet, -distance_feet, 0), "SW"),
    ]


def set_mark(instance, mark_value):
    mark_param = instance.LookupParameter("Mark")
    if mark_param and not mark_param.IsReadOnly:
        mark_param.Set(mark_value)


def set_zero_level_offset(instance):
    for bip in [
        BuiltInParameter.INSTANCE_ELEVATION_PARAM,
        BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM,
    ]:
        try:
            param = instance.get_Parameter(bip)
            if param and not param.IsReadOnly:
                param.Set(0.0)
        except Exception:
            pass


def main():
    active_view = doc.ActiveView

    if not isinstance(active_view, ViewPlan):
        TaskDialog.Show("Create Offset points", "Active view must be a plan view.")
        return

    level = active_view.GenLevel
    if level is None:
        TaskDialog.Show("Create Offset points", "Could not determine level from active plan view.")
        return

    grids = get_visible_grids(active_view)
    if len(grids) < 2:
        TaskDialog.Show("Create Offset points", "Need at least two visible grids in the active view.")
        return

    intersections = get_grid_intersections(grids)
    if not intersections:
        TaskDialog.Show("Create Offset points", "No grid intersections were found in the active view.")
        return

    distance_input = forms.ask_for_string(
        prompt="Enter offset distance in inches",
        title="Create Offset points",
        default="24"
    )

    if distance_input is None:
        return

    try:
        distance_inches = float(distance_input)
    except Exception:
        TaskDialog.Show("Create Offset points", "Offset distance must be a number.")
        return

    if distance_inches <= 0:
        TaskDialog.Show("Create Offset points", "Offset distance must be greater than zero.")
        return

    style = forms.CommandSwitchWindow.show(["+", "x"], message="Select offset style")
    if style is None:
        return

    symbol = get_control_point_symbol()
    if symbol is None:
        TaskDialog.Show("Create Offset points", "SSW Control Point family is not loaded.")
        return

    if not symbol.IsActive:
        tx_activate = Transaction(doc, "Activate SSW Control Point")
        tx_activate.Start()
        symbol.Activate()
        tx_activate.Commit()

    distance_feet = distance_inches / 12.0
    offsets = get_offsets(style, distance_feet)

    created_count = 0
    created_instances = []
    tx = Transaction(doc, "Create Offset points")
    tx.Start()

    try:
        for intersection, base_name in intersections:
            origin = XYZ(intersection.X, intersection.Y, level.Elevation)

            for offset, suffix in offsets:
                point = origin.Add(offset)
                instance = doc.Create.NewFamilyInstance(
                    point,
                    symbol,
                    level,
                    StructuralType.NonStructural
                )

                set_mark(instance, "{0}{1}".format(base_name, suffix))
                set_zero_level_offset(instance)
                created_instances.append(instance)
                created_count += 1

        tx.Commit()

    except Exception:
        tx.RollBack()
        raise

    comments_value = forms.ask_for_string(
        prompt="Enter Comments text for created points (optional)",
        title="Create Offset points",
        default=""
    )

    comments_applied_count = 0
    if comments_value is not None and comments_value.strip() != "":
        tx_comments = Transaction(doc, "Set Comments on Offset points")
        tx_comments.Start()
        try:
            for instance in created_instances:
                comments_param = instance.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if comments_param and not comments_param.IsReadOnly:
                    comments_param.Set(comments_value)
                    comments_applied_count += 1
            tx_comments.Commit()
        except Exception:
            tx_comments.RollBack()
            raise

    TaskDialog.Show(
        "Create Offset points",
        "Created {0} offset points from {1} grid intersections. Comments applied to {2} points.".format(
            created_count,
            len(intersections),
            comments_applied_count
        )
    )


if __name__ == '__main__':
    main()
