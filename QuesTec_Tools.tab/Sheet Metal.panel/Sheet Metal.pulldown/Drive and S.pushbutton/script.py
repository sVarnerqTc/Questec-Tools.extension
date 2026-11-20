# -*- coding: utf-8 -*-
"""Drive and S: on vertical rectangular duct elbows and vertical rectangular
offsets, rename connector names "S and Drive-<n>" to "Drive and S-<n>" and
"Standing S and Drive-<n>" to "Standing Drive and S-<n>" (the number is kept).

  * Elbow = duct fitting whose family Part Type is Elbow, all connectors
    rectangular. Vertical = at least one connector points straight up or down.
  * Offset = duct fitting whose family Part Type is Offset, all connectors
    rectangular. Vertical offset = the shift between its two connector centers
    (measured across the duct run) is mostly up/down rather than sideways.
    Horizontal offsets, and offsets in a duct that itself runs vertically,
    are left alone.
  * Text: every instance parameter whose name starts with "Connector Name"
    (Connector Name1, Connector Name2, ...) or is "C1 Name", "C2 Name", ...
    when present - "S and Drive-n" becomes
    "Drive and S-n", and "Standing S and Drive-n" becomes
    "Standing Drive and S-n".
  * The Yes/No connection check boxes (S and Drive1, Drive and S1, ...) are
    not edited; they are managed separately (SysQue Duct updater).
  * Scope: asks "Selection" or "Active View". Selection uses the current
    selection, or lets you pick elements if nothing is selected. Active View
    uses everything visible in the active view.
  * Elements owned by another user (or not synced) are skipped.
  * Afterwards the changed fittings are temporarily isolated in the active view
    and a summary is shown.
"""

import re

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    CheckoutStatus,
    ConnectorProfileType,
    ElementId,
    FamilyInstance,
    FilteredElementCollector,
    ModelUpdatesStatus,
    PartType,
    StorageType,
    TemporaryViewMode,
    Transaction,
    WorksharingUtils,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List
from pyrevit import forms


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TITLE = "Drive and S"
PARAM_PREFIX = "Connector Name"
C_NAME_PATTERN = re.compile(r"^C\d+ Name$")   # C1 Name, C2 Name, ...
# "S and Drive-1" -> "Drive and S-1"; "Standing S and Drive-1" -> "Standing Drive and S-1"
OLD_PATTERN = re.compile(r"^(\s*)(Standing\s+)?S and Drive(.*)$", re.IGNORECASE)
NEW_TEXT = "Drive and S"
VERTICAL_TOLERANCE = 0.999  # |Z| of the connector direction
MIN_OFFSET = 1.0 / 96.0     # 1/8" - smaller shifts count as "no offset"

KIND_ELBOW = "Vertical elbows"
KIND_OFFSET = "Vertical offsets"


# ---------------------------------------------------------------- tests

def get_part_type(element):
    try:
        param = element.Symbol.Family.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
        return param.AsInteger() if param is not None else None
    except Exception:
        return None


def get_rect_connectors(element):
    """All connectors if every one is rectangular, otherwise None."""
    if not isinstance(element, FamilyInstance):
        return None
    try:
        connectors = list(element.MEPModel.ConnectorManager.Connectors)
    except Exception:
        return None
    if not connectors or not all(c.Shape == ConnectorProfileType.Rectangular for c in connectors):
        return None
    return connectors


def is_rectangular_elbow(element):
    return get_part_type(element) == int(PartType.Elbow) and get_rect_connectors(element) is not None


def is_vertical_offset(element):
    """Rectangular offset whose shift (across the duct run) is mostly vertical."""
    if get_part_type(element) != int(PartType.Offset):
        return False
    connectors = get_rect_connectors(element)
    if not connectors or len(connectors) != 2:
        return False
    flow = connectors[0].CoordinateSystem.BasisZ
    if abs(flow.Z) >= VERTICAL_TOLERANCE:
        return False  # duct runs vertically; up/down isn't an offset here
    shift = connectors[1].Origin.Subtract(connectors[0].Origin)
    across = shift.Subtract(flow.Multiply(shift.DotProduct(flow)))
    vertical = abs(across.Z)
    horizontal = (across.X ** 2 + across.Y ** 2) ** 0.5
    if max(vertical, horizontal) < MIN_OFFSET:
        return False
    return vertical > horizontal


def classify(element):
    """Return KIND_ELBOW, KIND_OFFSET, or None if the fitting doesn't qualify."""
    if is_rectangular_elbow(element) and is_vertical(element):
        return KIND_ELBOW
    if is_vertical_offset(element):
        return KIND_OFFSET
    return None


def is_vertical(element):
    for c in element.MEPModel.ConnectorManager.Connectors:
        try:
            if abs(c.CoordinateSystem.BasisZ.Z) >= VERTICAL_TOLERANCE:
                return True
        except Exception:
            pass
    return False


def get_connector_name_params(element):
    params = []
    for p in element.Parameters:
        try:
            name = p.Definition.Name
            if p.StorageType == StorageType.String and (
                    name.startswith(PARAM_PREFIX) or C_NAME_PATTERN.match(name)):
                params.append(p)
        except Exception:
            pass
    return sorted(params, key=lambda p: p.Definition.Name)


def new_value_for(value):
    """'S and Drive-2' -> 'Drive and S-2';
    'Standing S and Drive-2' -> 'Standing Drive and S-2'.
    Returns None if no change applies."""
    if not value:
        return None
    match = OLD_PATTERN.match(value)
    if not match:
        return None
    return u"{0}{1}{2}{3}".format(match.group(1), match.group(2) or u"", NEW_TEXT, match.group(3))


def is_editable(element_id):
    if not doc.IsWorkshared:
        return True
    try:
        if WorksharingUtils.GetCheckoutStatus(doc, element_id) == CheckoutStatus.OwnedByOtherUser:
            return False
        status = WorksharingUtils.GetModelUpdatesStatus(doc, element_id)
        if status in (ModelUpdatesStatus.UpdatedInCentral, ModelUpdatesStatus.DeletedInCentral):
            return False
    except Exception:
        pass
    return True


# ---------------------------------------------------------------- scope

SCOPE_SELECTION = "Selection"
SCOPE_VIEW = "Active View"


def choose_scope():
    return forms.CommandSwitchWindow.show(
        [SCOPE_SELECTION, SCOPE_VIEW],
        message="Which duct fittings should be checked?",
    )


def get_selection_ids():
    """Current selection, or let the user pick if nothing is selected.
    Returns (ids, label) or (None, None) if cancelled."""
    selected_ids = uidoc.Selection.GetElementIds()
    if selected_ids.Count > 0:
        return selected_ids, "current selection"
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, "Select duct fittings for Drive and S, then click Finish")
    except OperationCanceledException:
        return None, None
    ids = List[ElementId]([r.ElementId for r in refs])
    if ids.Count == 0:
        return None, None
    return ids, "picked elements"


def collect_fittings(view, scope):
    """Return (fittings, scope label) or (None, None) if cancelled."""
    if scope == SCOPE_SELECTION:
        ids, label = get_selection_ids()
        if ids is None:
            return None, None
        elements = (
            FilteredElementCollector(doc, ids)
            .OfCategory(BuiltInCategory.OST_DuctFitting)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        return list(elements), label

    elements = list(
        FilteredElementCollector(doc, view.Id)
        .OfCategory(BuiltInCategory.OST_DuctFitting)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    if view.IsTemporaryHideIsolateActive():
        visible = []
        for e in elements:
            try:
                if view.IsElementVisibleInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate, e.Id):
                    visible.append(e)
            except Exception:
                visible.append(e)
        elements = visible
    return elements, "active view"


# ---------------------------------------------------------------- main

def find_changes(fittings):
    """Return ({kind: count of qualifying fittings},
    list of (element, [(param, new value, summary label or None)]))."""
    kind_counts = {KIND_ELBOW: 0, KIND_OFFSET: 0}
    changes = []
    for elem in fittings:
        kind = classify(elem)
        if kind is None:
            continue
        kind_counts[kind] += 1
        edits = []
        for param in get_connector_name_params(elem):
            old = param.AsString()
            new = new_value_for(old)
            if new is not None and new != old:
                edits.append((param, new, u"{0}  ->  {1}".format(old, new)))
        if edits:
            changes.append((elem, edits))
    return kind_counts, changes


def describe_counts(kind_counts):
    return "{0} vertical rectangular elbows, {1} vertical rectangular offsets".format(
        kind_counts[KIND_ELBOW], kind_counts[KIND_OFFSET])


def isolate_in_view(view, elements):
    ids = List[ElementId]([e.Id for e in elements])
    tx = Transaction(doc, TITLE + " - Isolate")
    tx.Start()
    try:
        view.IsolateElementsTemporary(ids)
        tx.Commit()
        return True
    except Exception:
        tx.RollBack()
        return False


def main():
    view = doc.ActiveView
    scope = choose_scope()
    if not scope:
        return
    fittings, scope_label = collect_fittings(view, scope)
    if fittings is None:
        return
    if not fittings:
        forms.alert("No duct fittings found in the {0}.".format(scope_label), title=TITLE)
        return

    kind_counts, changes = find_changes(fittings)
    if not changes:
        forms.alert(
            "Checked {0} duct fittings in the {1}.\n\n"
            "Found {2}; none have an \"S and Drive\" connection.".format(
                len(fittings), scope_label, describe_counts(kind_counts)),
            title=TITLE,
        )
        return

    editable = [(e, edits) for e, edits in changes if is_editable(e.Id)]
    skipped_owned = len(changes) - len(editable)

    if doc.IsWorkshared and editable:
        ids = List[ElementId]([e.Id for e, _ in editable])
        try:
            borrowed = set(i.IntegerValue for i in WorksharingUtils.CheckoutElements(doc, ids))
            before = len(editable)
            editable = [(e, edits) for e, edits in editable if e.Id.IntegerValue in borrowed]
            skipped_owned += before - len(editable)
        except Exception:
            pass

    changed_elbows = []
    changed_params = 0
    value_changes = {}  # summary label -> count
    failed = 0
    if editable:
        tx = Transaction(doc, TITLE)
        tx.Start()
        try:
            for elem, edits in editable:
                elem_changed = False
                for param, new, label in edits:
                    if param.IsReadOnly:
                        failed += 1
                        continue
                    try:
                        if param.Set(new):
                            if label:
                                changed_params += 1
                                value_changes[label] = value_changes.get(label, 0) + 1
                            elem_changed = True
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                if elem_changed:
                    changed_elbows.append(elem)
            tx.Commit()
        except Exception as ex:
            tx.RollBack()
            forms.alert("Command failed, nothing was changed:\n\n{0}".format(ex), title=TITLE)
            return

    isolated = isolate_in_view(view, changed_elbows) if changed_elbows else False
    if changed_elbows:
        try:
            uidoc.Selection.SetElementIds(List[ElementId]([e.Id for e in changed_elbows]))
        except Exception:
            pass

    lines = [
        "Scope: {0} ({1} duct fittings)".format(scope_label, len(fittings)),
        "Found: {0}".format(describe_counts(kind_counts)),
        "",
        "Changed {0} fittings ({1} connections):".format(len(changed_elbows), changed_params),
    ]
    for label, n in sorted(value_changes.items()):
        lines.append(u"    {0}   x{1}".format(label, n))
    if changed_elbows:
        lines.append("")
        if isolated:
            lines.append("The changed fittings are temporarily isolated and selected in '{0}'.".format(view.Name))
        else:
            lines.append("The changed fittings are selected (could not isolate them in this view).")
    if skipped_owned:
        lines.append("Skipped (owned by another user or not synced): {0}".format(skipped_owned))
    if failed:
        lines.append("Could not change (read-only): {0} parameters".format(failed))
    forms.alert("\n".join(lines), title=TITLE)


if __name__ == "__main__":
    main()
