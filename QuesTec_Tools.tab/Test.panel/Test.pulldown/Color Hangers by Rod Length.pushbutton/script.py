from pyrevit import revit, DB, forms


def get_solid_fill_pattern_id(doc):
    """Return the drafting solid fill pattern id if available."""
    for pattern_name in ("<Solid fill>", "Solid fill"):
        pattern = DB.FillPatternElement.GetFillPatternElementByName(
            doc,
            DB.FillPatternTarget.Drafting,
            pattern_name
        )
        if pattern:
            return pattern.Id
    return DB.ElementId.InvalidElementId


def get_total_rod_length_feet(element):
    """Read Total Rod Length as internal feet from supported parameter storage types."""
    param = element.LookupParameter("Total Rod Length")
    if not param or not param.HasValue:
        return None

    storage_type = param.StorageType

    if storage_type == DB.StorageType.Double:
        return param.AsDouble()

    if storage_type == DB.StorageType.Integer:
        return float(param.AsInteger())

    if storage_type == DB.StorageType.String:
        value = param.AsString()
        if not value:
            return None
        value = value.strip().replace('"', '').replace("'", "")
        try:
            return float(value)
        except Exception:
            return None

    return None


def is_hanger_pipe_accessory(element):
    """Identify hanger-like pipe accessories by category plus BOP parameter."""
    if not isinstance(element, DB.FamilyInstance):
        return False

    category = element.Category
    if not category:
        return False

    if category.Id.IntegerValue != int(DB.BuiltInCategory.OST_PipeAccessory):
        return False

    bop_param = element.LookupParameter("BOP")
    return bop_param is not None


def build_override_settings(color, solid_fill_id):
    ogs = DB.OverrideGraphicSettings()

    if solid_fill_id and solid_fill_id != DB.ElementId.InvalidElementId:
        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
        ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
        ogs.SetCutForegroundPatternId(solid_fill_id)
        ogs.SetCutBackgroundPatternId(solid_fill_id)

    ogs.SetProjectionLineColor(color)
    ogs.SetCutLineColor(color)
    ogs.SetSurfaceForegroundPatternColor(color)
    ogs.SetSurfaceBackgroundPatternColor(color)
    ogs.SetCutForegroundPatternColor(color)
    ogs.SetCutBackgroundPatternColor(color)
    return ogs


def main():
    doc = revit.doc
    active_view = revit.active_view

    visible_elements = (
        DB.FilteredElementCollector(doc, active_view.Id)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    # Thresholds are in Revit internal units (feet).
    green_max = 4.5
    orange_max = 6.0

    green_color = DB.Color(0, 176, 80)
    orange_color = DB.Color(255, 165, 0)
    red_color = DB.Color(255, 0, 0)

    solid_fill_id = get_solid_fill_pattern_id(doc)
    green_ogs = build_override_settings(green_color, solid_fill_id)
    orange_ogs = build_override_settings(orange_color, solid_fill_id)
    red_ogs = build_override_settings(red_color, solid_fill_id)

    green_ids = []
    orange_ids = []
    red_ids = []
    skipped_ids = []

    for element in visible_elements:
        if not is_hanger_pipe_accessory(element):
            continue

        rod_length = get_total_rod_length_feet(element)
        if rod_length is None:
            skipped_ids.append(element.Id)
            continue

        if rod_length < green_max:
            green_ids.append(element.Id)
        elif rod_length < orange_max:
            orange_ids.append(element.Id)
        else:
            red_ids.append(element.Id)

    if not (green_ids or orange_ids or red_ids):
        forms.alert(
            "No visible hanger pipe accessories with BOP and usable Total Rod Length were found in the active view.",
            exitscript=True
        )

    with revit.Transaction("Color Hangers by Rod Length"):
        for elem_id in green_ids:
            active_view.SetElementOverrides(elem_id, green_ogs)
        for elem_id in orange_ids:
            active_view.SetElementOverrides(elem_id, orange_ogs)
        for elem_id in red_ids:
            active_view.SetElementOverrides(elem_id, red_ogs)

    forms.alert(
        "Applied in-view hanger color overrides by Total Rod Length.\n\n"
        "Green (< 4' 6\"): {}\n"
        "Orange (>= 4' 6\" and < 6' 0\"): {}\n"
        "Red (>= 6' 0\"): {}\n"
        "Skipped (missing or unreadable Total Rod Length): {}".format(
            len(green_ids),
            len(orange_ids),
            len(red_ids),
            len(skipped_ids)
        )
    )


if __name__ == "__main__":
    main()
