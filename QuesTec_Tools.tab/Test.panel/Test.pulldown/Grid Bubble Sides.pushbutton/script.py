# -*- coding: utf-8 -*-

__title__ = "Grid Bubble\nSides"
__author__ = "QuesTec"
__doc__ = "Turn grid bubbles on/off by Left, Right, Top, Bottom for selected grids in active view."

from Autodesk.Revit.DB import DatumEnds, DatumExtentType, ElementId, Grid, TemporaryViewMode
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms, revit, script
from System.Collections.Generic import List


def get_selected_or_picked_elements(uidoc, doc):
    selected_ids = uidoc.Selection.GetElementIds()
    if selected_ids and selected_ids.Count > 0:
        return [doc.GetElement(eid) for eid in selected_ids]

    try:
        picked_refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            "Select gridlines and click Finish"
        )
        return [doc.GetElement(r.ElementId) for r in picked_refs]
    except OperationCanceledException:
        return []


def filter_grids(elements):
    return [el for el in elements if isinstance(el, Grid)]


def get_grid_curve_for_view(grid, view):
    view_curves = list(grid.GetCurvesInView(DatumExtentType.ViewSpecific, view))
    if not view_curves:
        view_curves = list(grid.GetCurvesInView(DatumExtentType.Model, view))
    if not view_curves:
        return grid.Curve
    return view_curves[0]


def classify_orientation(grid, view):
    curve = get_grid_curve_for_view(grid, view)

    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)

    if dy >= dx:
        return "North/South"
    return "East/West"


def get_page_xy(point, right_dir, up_dir):
    x = point.DotProduct(right_dir)
    y = point.DotProduct(up_dir)
    return x, y


def get_side_membership(grid, view):
    curve = get_grid_curve_for_view(grid, view)
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)

    right_dir = view.RightDirection
    up_dir = view.UpDirection

    x0, y0 = get_page_xy(p0, right_dir, up_dir)
    x1, y1 = get_page_xy(p1, right_dir, up_dir)

    side_end0 = set()
    side_end1 = set()

    orientation = classify_orientation(grid, view)
    if orientation == "North/South":
        if y0 <= y1:
            side_end0.add("Bottom")
            side_end1.add("Top")
        else:
            side_end0.add("Top")
            side_end1.add("Bottom")
    else:
        if x0 <= x1:
            side_end0.add("Left")
            side_end1.add("Right")
        else:
            side_end0.add("Right")
            side_end1.add("Left")

    return {
        DatumEnds.End0: side_end0,
        DatumEnds.End1: side_end1
    }


def ask_sides(dominant, ns_count, ew_count):
    title = "Grid Bubble Sides | Mostly {0} (N/S: {1}, E/W: {2})".format(
        dominant,
        ns_count,
        ew_count
    )
    options = ["Left", "Right", "Top", "Bottom"]
    selected = forms.SelectFromList.show(
        options,
        title=title,
        multiselect=True,
        button_name="Apply"
    )

    if selected is None:
        return None

    return set(selected)


def set_bubbles_for_grid(grid, view, selected_sides, doc):
    side_by_end = get_side_membership(grid, view)
    target_by_end = {
        DatumEnds.End0: any(side in selected_sides for side in side_by_end[DatumEnds.End0]),
        DatumEnds.End1: any(side in selected_sides for side in side_by_end[DatumEnds.End1])
    }

    before_end0 = grid.IsBubbleVisibleInView(DatumEnds.End0, view)
    before_end1 = grid.IsBubbleVisibleInView(DatumEnds.End1, view)

    # Force a deterministic state before setting desired visibility.
    grid.HideBubbleInView(DatumEnds.End0, view)
    grid.HideBubbleInView(DatumEnds.End1, view)

    for datum_end, should_show in target_by_end.items():
        if should_show:
            grid.ShowBubbleInView(datum_end, view)

    doc.Regenerate()

    actual_end0 = grid.IsBubbleVisibleInView(DatumEnds.End0, view)
    actual_end1 = grid.IsBubbleVisibleInView(DatumEnds.End1, view)
    actual_by_end = {
        DatumEnds.End0: actual_end0,
        DatumEnds.End1: actual_end1
    }

    score = 0
    for datum_end, should_show in target_by_end.items():
        if actual_by_end[datum_end] == should_show:
            score += 1

    if score != 2:
        raise Exception(
            "Visibility mismatch. Desired End0={0}, End1={1}; Actual End0={2}, End1={3}".format(
                target_by_end[DatumEnds.End0],
                target_by_end[DatumEnds.End1],
                actual_by_end[DatumEnds.End0],
                actual_by_end[DatumEnds.End1]
            )
        )

    return {
        "before": (before_end0, before_end1),
        "after": (actual_end0, actual_end1),
        "target": (target_by_end[DatumEnds.End0], target_by_end[DatumEnds.End1]),
        "sides_end0": ",".join(sorted(side_by_end[DatumEnds.End0])),
        "sides_end1": ",".join(sorted(side_by_end[DatumEnds.End1]))
    }


def capture_temp_isolate_ids(view):
    if not view.IsTemporaryHideIsolateActive():
        return []

    try:
        return list(view.GetTemporaryHideIsolateElementIds())
    except Exception:
        return []


def refresh_temp_isolate(uidoc, view, isolate_ids):
    if not isolate_ids:
        return False, "No isolated element ids found"

    id_list = List[ElementId]()
    for eid in isolate_ids:
        id_list.Add(eid)

    # Split disable/reapply into separate transactions so Revit redraws datum bubbles.
    with revit.Transaction("Clear Temporary Isolate"):
        view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)

    uidoc.RefreshActiveView()

    with revit.Transaction("Reapply Temporary Isolate"):
        view.IsolateElementsTemporary(id_list)

    uidoc.RefreshActiveView()
    return True, "Reapplied {0} isolated elements".format(id_list.Count)


def main():
    uidoc = revit.uidoc
    doc = revit.doc
    active_view = doc.ActiveView
    output = script.get_output()
    output.set_title("Grid Bubble Sides")

    elements = get_selected_or_picked_elements(uidoc, doc)
    if not elements:
        forms.alert("No elements selected.", exitscript=True)

    grids = filter_grids(elements)
    if not grids:
        forms.alert("No Grids found in selection.", exitscript=True)

    ns_count = 0
    ew_count = 0
    for grid in grids:
        if classify_orientation(grid, active_view) == "North/South":
            ns_count += 1
        else:
            ew_count += 1

    dominant = "North/South" if ns_count >= ew_count else "East/West"

    selected_sides = ask_sides(dominant, ns_count, ew_count)
    if selected_sides is None:
        forms.alert("Operation cancelled.", exitscript=True)

    temp_isolate_ids = capture_temp_isolate_ids(active_view)

    failed = 0
    errors = []
    changed = 0
    unchanged = 0
    debug_rows = []

    with revit.Transaction("Set Grid Bubble Sides"):
        for grid in grids:
            try:
                result = set_bubbles_for_grid(grid, active_view, selected_sides, doc)
                before_state = result["before"]
                after_state = result["after"]
                target_state = result["target"]

                if before_state != after_state:
                    changed += 1
                else:
                    unchanged += 1

                if len(debug_rows) < 25:
                    debug_rows.append(
                        "Grid {0} | End0 sides={1} End1 sides={2} | before E0/E1={3}/{4} | target E0/E1={5}/{6} | after E0/E1={7}/{8}".format(
                            grid.Id.IntegerValue,
                            result["sides_end0"],
                            result["sides_end1"],
                            before_state[0],
                            before_state[1],
                            target_state[0],
                            target_state[1],
                            after_state[0],
                            after_state[1]
                        )
                    )
            except Exception as ex:
                failed += 1
                errors.append("Grid {0}: {1}".format(grid.Id.IntegerValue, str(ex)))

    temp_isolate_refreshed = False
    temp_isolate_message = ""
    if temp_isolate_ids:
        try:
            temp_isolate_refreshed, temp_isolate_message = refresh_temp_isolate(uidoc, active_view, temp_isolate_ids)
        except Exception as ex:
            temp_isolate_message = str(ex)
            errors.append("Temporary isolate refresh failed: {0}".format(str(ex)))

    uidoc.RefreshActiveView()

    summary = (
        "Processed {0} grids.\n"
        "Changed: {1}, Unchanged: {2}.\n"
        "Dominant orientation: {3} (N/S: {4}, E/W: {5}).\n"
        "Bubbles ON sides: {6}.\n"
        "Failed: {7}"
    ).format(
        len(grids),
        changed,
        unchanged,
        dominant,
        ns_count,
        ew_count,
        ", ".join(sorted(selected_sides)) if selected_sides else "None",
        failed
    )

    print("=" * 80)
    print("Grid Bubble Sides")
    print("=" * 80)
    print(summary)

    if temp_isolate_ids:
        print("Temporary isolate refresh: {0}".format("Applied" if temp_isolate_refreshed else "Not applied"))
        if temp_isolate_message:
            print("Temporary isolate details: {0}".format(temp_isolate_message))

    if errors:
        print("\nErrors:")
        for row in errors[:200]:
            print(row)

    if debug_rows:
        print("\nDebug:")
        for row in debug_rows:
            print(row)

    print("=" * 80)
    forms.alert(
        "Run complete. Details were written to the pyRevit output window for copy/paste.",
        title="Grid Bubble Sides"
    )


if __name__ == "__main__":
    main()
