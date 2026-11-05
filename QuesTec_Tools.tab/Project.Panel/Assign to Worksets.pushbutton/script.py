# -*- coding: utf-8 -*-
"""Assign model elements to the Questec standard worksets.

Rules (in priority order):
  1. Links (Revit, CAD, point cloud) -> "Link-<EXT>-<Filename>" (created if missing).
  2. Pipe accessories whose family name starts with SSW and contains "Point":
       family "SSW Control Point", or an SSW type named "...Control Point..."
         -> "Points - Control"
       all other SSW point families -> "Points - Layout"
  3. Piping elements below the underground level -> "Pipe - Underground"
  4. System containing MP- or MS- -> "Pipe - Mechanical"
     System containing PL- or PP- -> "Pipe - Plumbing"
     Hangers (pipe accessories with a BOP parameter) go to "Hangers - Mechanical"
     or "Hangers - Plumbing" instead, matched by, in order:
       a. Support Discipline = a piping system abbreviation (e.g. "C" ->
          the PP-Domestic Cold Water system type -> Hangers - Plumbing)
       b. Comments containing a system name (MP-/MS-/PL-/PP-)
       c. The hanger's own system, if it has one

The underground level is asked for on the first run in each project and
remembered. Shift+Click the button to pick a different level.

Elements owned by another user, or out of date with central, are skipped.
"""

import os

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    CADLinkType,
    ElementId,
    ElementMulticategoryFilter,
    ExternalFileUtils,
    FamilyInstance,
    FilteredElementCollector,
    FilteredWorksetCollector,
    ImportInstance,
    ModelPathUtils,
    PointCloudInstance,
    RevitLinkInstance,
    Transaction,
    Workset,
    WorksetKind,
    WorksharingUtils,
    CheckoutStatus,
    ModelUpdatesStatus,
)
from Autodesk.Revit.DB.Plumbing import PipingSystemType
from System.Collections.Generic import List
from pyrevit import forms, script

import underground_level


doc = __revit__.ActiveUIDocument.Document

TITLE = "Assign to Worksets"

WS_MECH = "Pipe - Mechanical"
WS_PLUMB = "Pipe - Plumbing"
WS_UNDERGROUND = "Pipe - Underground"
WS_POINT_CONTROL = "Points - Control"
WS_POINT_LAYOUT = "Points - Layout"
WS_HANGER_MECH = "Hangers - Mechanical"
WS_HANGER_PLUMB = "Hangers - Plumbing"

# Hangers use the same system rules but land on their own worksets.
HANGER_WORKSET_MAP = {
    WS_MECH: WS_HANGER_MECH,
    WS_PLUMB: WS_HANGER_PLUMB,
}

MECH_TOKENS = ("MP-", "MS-")
PLUMB_TOKENS = ("PL-", "PP-")

POINT_FAMILY_PREFIX = "SSW"
CONTROL_POINT_FAMILY = "SSW Control Point"

# Elements must sit more than this far below the level to count as underground (ft).
UNDERGROUND_TOLERANCE = 0.01

PIPING_CATEGORY_NAMES = [
    "OST_PipeCurves",
    "OST_PipeFitting",
    "OST_PipeAccessory",
    "OST_FlexPipeCurves",
    "OST_MechanicalEquipment",
    "OST_PlumbingFixtures",
    "OST_PlumbingEquipment",  # Revit 2024+
]

HANGER_PARAM = "BOP"
SUPPORT_DISCIPLINE_PARAM = "Support Discipline"

INVALID_WORKSET_CHARS = '\\:{}[]|;<>?`~'


# ---------------------------------------------------------------- generic helpers

def safe_str(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def get_family_and_type(instance):
    family_name = ""
    type_name = ""
    try:
        symbol = instance.Symbol
    except Exception:
        return family_name, type_name
    try:
        family_name = safe_str(symbol.FamilyName)
    except Exception:
        pass
    try:
        type_name = get_param_text(symbol, BuiltInParameter.SYMBOL_NAME_PARAM)
    except Exception:
        pass
    return family_name, type_name


def get_param_text(element, bip):
    try:
        param = element.get_Parameter(bip)
        if param is None or not param.HasValue:
            return ""
        text = param.AsString()
        if not text:
            text = param.AsValueString()
        return safe_str(text)
    except Exception:
        return ""


def get_current_workset_id(element):
    param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
    if param is None:
        return None
    return param.AsInteger()


def sanitize_workset_name(name):
    for ch in INVALID_WORKSET_CHARS:
        name = name.replace(ch, "_")
    return name.strip()


# ---------------------------------------------------------------- links

def get_link_file_name(type_elem):
    """Return the linked file's name with extension, e.g. 'Architecture23.rvt'."""
    try:
        if ExternalFileUtils.IsExternalFileReference(doc, type_elem.Id):
            ref = ExternalFileUtils.GetExternalFileReference(doc, type_elem.Id)
            path = ModelPathUtils.ConvertModelPathToUserVisiblePath(ref.GetAbsolutePath())
            name = os.path.basename(path)
            if name:
                return name
    except Exception:
        pass

    try:
        return safe_str(type_elem.Name)
    except Exception:
        return ""


def build_link_workset_name(file_name, fallback_ext):
    base, ext = os.path.splitext(file_name)
    ext = ext.lstrip(".").upper() or fallback_ext
    base = base or file_name or "Unknown"
    return sanitize_workset_name("Link-{0}-{1}".format(ext, base))


def collect_link_assignments():
    """Return list of (element, target workset name)."""
    results = []

    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
        link_type = doc.GetElement(inst.GetTypeId())
        if link_type is None:
            continue
        ws_name = build_link_workset_name(get_link_file_name(link_type), "RVT")
        results.append((inst, ws_name))
        results.append((link_type, ws_name))

    for inst in FilteredElementCollector(doc).OfClass(ImportInstance).ToElements():
        if not inst.IsLinked:
            continue
        link_type = doc.GetElement(inst.GetTypeId())
        if not isinstance(link_type, CADLinkType):
            continue
        ws_name = build_link_workset_name(get_link_file_name(link_type), "CAD")
        results.append((inst, ws_name))
        results.append((link_type, ws_name))

    for inst in FilteredElementCollector(doc).OfClass(PointCloudInstance).ToElements():
        cloud_type = doc.GetElement(inst.GetTypeId())
        if cloud_type is None:
            continue
        ws_name = build_link_workset_name(get_link_file_name(cloud_type), "PCD")
        results.append((inst, ws_name))
        results.append((cloud_type, ws_name))

    return results


# ---------------------------------------------------------------- points

def is_point(element):
    if not isinstance(element, FamilyInstance) or element.Category is None:
        return False
    if element.Category.Id.IntegerValue != int(BuiltInCategory.OST_PipeAccessory):
        return False
    family_name, _ = get_family_and_type(element)
    name = family_name.upper()
    return name.startswith(POINT_FAMILY_PREFIX) and "POINT" in name


def get_point_workset(element):
    family_name, type_name = get_family_and_type(element)
    if family_name.strip().lower() == CONTROL_POINT_FAMILY.lower():
        return WS_POINT_CONTROL
    if "control point" in type_name.lower():
        return WS_POINT_CONTROL
    return WS_POINT_LAYOUT


# ---------------------------------------------------------------- piping

def get_piping_categories():
    cats = List[BuiltInCategory]()
    for name in PIPING_CATEGORY_NAMES:
        bic = getattr(BuiltInCategory, name, None)
        if bic is not None:
            cats.Add(bic)
    return cats


def get_system_text(element):
    parts = [
        get_param_text(element, BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM),
        get_param_text(element, BuiltInParameter.RBS_SYSTEM_NAME_PARAM),
        get_param_text(element, BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM),
    ]
    return " | ".join(p for p in parts if p).upper()


def classify_system_text(text):
    """Return (workset name or None, is_conflict) for a piece of system text."""
    text = safe_str(text).upper()
    if not text:
        return None, False
    is_mech = any(tok in text for tok in MECH_TOKENS)
    is_plumb = any(tok in text for tok in PLUMB_TOKENS)
    if is_mech and is_plumb:
        return None, True
    if is_mech:
        return WS_MECH, False
    if is_plumb:
        return WS_PLUMB, False
    return None, False


def get_system_workset(element):
    """Return (workset name or None, is_conflict)."""
    return classify_system_text(get_system_text(element))


# ---------------------------------------------------------------- hangers

def is_hanger(element):
    if not isinstance(element, FamilyInstance) or element.Category is None:
        return False
    if element.Category.Id.IntegerValue != int(BuiltInCategory.OST_PipeAccessory):
        return False
    return element.LookupParameter(HANGER_PARAM) is not None


def build_abbreviation_map():
    """Map piping system abbreviation (upper case) -> workset name.

    Abbreviations shared by system types that land on different worksets are
    left out, so they fall through to the Comments rule.
    """
    found = {}
    for sys_type in FilteredElementCollector(doc).OfClass(PipingSystemType).ToElements():
        abbr = get_param_text(sys_type, BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM).strip().upper()
        if not abbr:
            continue
        name = get_param_text(sys_type, BuiltInParameter.SYMBOL_NAME_PARAM) or \
            get_param_text(sys_type, BuiltInParameter.ALL_MODEL_TYPE_NAME)
        ws_name, _ = classify_system_text(name)
        found.setdefault(abbr, set()).add(ws_name)

    result = {}
    for abbr, worksets in found.items():
        worksets.discard(None)
        if len(worksets) == 1:
            result[abbr] = worksets.pop()
    return result


def get_hanger_workset(element, abbreviation_map):
    """Return (workset name or None, source label, is_conflict)."""
    param = element.LookupParameter(SUPPORT_DISCIPLINE_PARAM)
    if param is not None and param.HasValue:
        discipline = safe_str(param.AsString() or param.AsValueString()).strip().upper()
        if discipline:
            ws_name = abbreviation_map.get(discipline)
            if ws_name is None:
                # Support Discipline may itself hold a full system name.
                ws_name, _ = classify_system_text(discipline)
            if ws_name:
                return ws_name, "Support Discipline", False

    comments = get_param_text(element, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    ws_name, is_conflict = classify_system_text(comments)
    if ws_name:
        return ws_name, "Comments", False

    ws_name, own_conflict = get_system_workset(element)
    if ws_name:
        return ws_name, "System", False
    return None, None, (is_conflict or own_conflict)


def get_reference_z(element):
    """Insertion point for families (so a floor drain set on the level is not
    'below' it), curve midpoint for pipes, bounding box center otherwise."""
    location = element.Location
    try:
        if location is not None and hasattr(location, "Point") and location.Point is not None:
            return location.Point.Z
    except Exception:
        pass
    try:
        if location is not None and hasattr(location, "Curve") and location.Curve is not None:
            return location.Curve.Evaluate(0.5, True).Z
    except Exception:
        pass
    bbox = element.get_BoundingBox(None)
    if bbox is not None:
        return (bbox.Min.Z + bbox.Max.Z) / 2.0
    return None


def is_below_level(element, level_z):
    z = get_reference_z(element)
    if z is None:
        return False
    return z < level_z - UNDERGROUND_TOLERANCE


# ---------------------------------------------------------------- worksets

def get_user_worksets():
    worksets = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
    return dict((ws.Name.strip().lower(), ws) for ws in worksets)


def is_editable(element_id):
    try:
        if WorksharingUtils.GetCheckoutStatus(doc, element_id) == CheckoutStatus.OwnedByOtherUser:
            return False
        status = WorksharingUtils.GetModelUpdatesStatus(doc, element_id)
        if status in (ModelUpdatesStatus.UpdatedInCentral, ModelUpdatesStatus.DeletedInCentral):
            return False
    except Exception:
        pass
    return True


# ---------------------------------------------------------------- main

def main():
    if doc.IsFamilyDocument or not doc.IsWorkshared:
        forms.alert("This model is not workshared. Enable worksharing first.", title=TITLE)
        return

    level = underground_level.get_or_pick_level(doc)
    if level is None:
        return
    level_z = level.ProjectElevation

    plan = {}  # element id int -> (element, workset name)
    conflicts = 0
    abbreviation_map = build_abbreviation_map()
    hanger_sources = {}
    hangers_unmatched = 0

    # 1. Links
    for elem, ws_name in collect_link_assignments():
        plan[elem.Id.IntegerValue] = (elem, ws_name)

    # 2-4. Piping elements and points
    piping = (
        FilteredElementCollector(doc)
        .WherePasses(ElementMulticategoryFilter(get_piping_categories()))
        .WhereElementIsNotElementType()
        .ToElements()
    )
    for elem in piping:
        key = elem.Id.IntegerValue
        if key in plan:
            continue

        if is_point(elem):
            plan[key] = (elem, get_point_workset(elem))
            continue

        if is_below_level(elem, level_z):
            plan[key] = (elem, WS_UNDERGROUND)
            continue

        if is_hanger(elem):
            ws_name, source, is_conflict = get_hanger_workset(elem, abbreviation_map)
            ws_name = HANGER_WORKSET_MAP.get(ws_name, ws_name)
            if ws_name:
                hanger_sources[source] = hanger_sources.get(source, 0) + 1
            elif not is_conflict:
                hangers_unmatched += 1
        else:
            ws_name, is_conflict = get_system_workset(elem)

        if is_conflict:
            conflicts += 1
        elif ws_name:
            plan[key] = (elem, ws_name)

    if not plan:
        forms.alert("No elements matched any workset rule.", title=TITLE)
        return

    existing = get_user_worksets()

    # Drop elements already on the right workset.
    to_move = []
    already_correct = 0
    for elem, ws_name in plan.values():
        ws = existing.get(ws_name.lower())
        if ws is not None and get_current_workset_id(elem) == ws.Id.IntegerValue:
            already_correct += 1
        else:
            to_move.append((elem, ws_name))

    # Borrow what we can; skip anything owned by others / out of date.
    editable = [(e, n) for e, n in to_move if is_editable(e.Id)]
    skipped_owned = len(to_move) - len(editable)

    if editable:
        ids = List[ElementId]([e.Id for e, _ in editable])
        try:
            borrowed = set(i.IntegerValue for i in WorksharingUtils.CheckoutElements(doc, ids))
        except Exception:
            borrowed = set(i.IntegerValue for i in ids)
        before = len(editable)
        editable = [(e, n) for e, n in editable if e.Id.IntegerValue in borrowed]
        skipped_owned += before - len(editable)

    moved = {}
    failed = 0
    created_worksets = []

    if editable:
        tx = Transaction(doc, TITLE)
        tx.Start()
        try:
            for elem, ws_name in editable:
                ws = existing.get(ws_name.lower())
                if ws is None:
                    ws = Workset.Create(doc, ws_name)
                    existing[ws_name.lower()] = ws
                    created_worksets.append(ws_name)

                param = elem.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
                if param is None or param.IsReadOnly:
                    failed += 1
                    continue
                try:
                    param.Set(ws.Id.IntegerValue)
                    moved[ws_name] = moved.get(ws_name, 0) + 1
                except Exception:
                    failed += 1
            tx.Commit()
        except Exception as ex:
            tx.RollBack()
            forms.alert("Command failed, nothing was changed:\n\n{0}".format(ex), title=TITLE)
            return

    lines = ["Underground level: {0}".format(level.Name), ""]
    if moved:
        lines.append("Moved:")
        for ws_name in sorted(moved):
            lines.append("  {0}: {1}".format(ws_name, moved[ws_name]))
    else:
        lines.append("No elements needed to move.")
    lines.append("")
    lines.append("Already on the correct workset: {0}".format(already_correct))
    if skipped_owned:
        lines.append("Skipped (owned by another user or not synced): {0}".format(skipped_owned))
    if failed:
        lines.append("Skipped (workset parameter is read-only): {0}".format(failed))
    if conflicts:
        lines.append("Skipped (system has both mechanical and plumbing codes): {0}".format(conflicts))
    if hanger_sources or hangers_unmatched:
        lines.append("")
        lines.append("Hangers matched by:")
        for source in ("Support Discipline", "Comments", "System"):
            if hanger_sources.get(source):
                lines.append("  {0}: {1}".format(source, hanger_sources[source]))
        if hangers_unmatched:
            lines.append("  No system found (left as is): {0}".format(hangers_unmatched))
    if created_worksets:
        lines.append("")
        lines.append("Created worksets:")
        lines.extend("  " + n for n in sorted(created_worksets))
    lines.append("")
    lines.append("Shift+Click the button to change the underground level.")

    forms.alert("\n".join(lines), title=TITLE)


if __name__ == "__main__":
    main()
