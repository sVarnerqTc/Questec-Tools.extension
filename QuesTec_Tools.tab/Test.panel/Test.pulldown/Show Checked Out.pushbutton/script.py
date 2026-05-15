from pyrevit import revit, DB, forms
from System.Collections.Generic import List


TITLE = "Show Checked Out"


def _is_checked_out(doc, elem_id):
    try:
        status = DB.WorksharingUtils.GetCheckoutStatus(doc, elem_id)
        return (
            status == DB.CheckoutStatus.OwnedByOtherUser
            or status == DB.CheckoutStatus.OwnedByCurrentUser
        )
    except Exception:
        return False


def _get_owner_name(doc, elem_id):
    try:
        info = DB.WorksharingUtils.GetWorksharingTooltipInfo(doc, elem_id)
        if info and info.Owner and info.Owner.strip():
            return info.Owner.strip()
    except Exception:
        pass
    return doc.Application.Username or "Unknown User"


def _can_temp_hide(element, view):
    try:
        return element is not None and element.CanBeHidden(view)
    except Exception:
        return False


def main():
    doc = revit.doc
    active_view = doc.ActiveView

    if not doc.IsWorkshared:
        forms.alert(
            "This model is not workshared. There are no checked out elements to isolate.",
            title=TITLE,
            warn_icon=True,
        )
        return

    if active_view is None:
        forms.alert("No active view found.", title=TITLE, warn_icon=True)
        return

    owner_to_ids = {}

    visible_ids = (
        DB.FilteredElementCollector(doc, active_view.Id)
        .WhereElementIsNotElementType()
        .ToElementIds()
    )

    for elem_id in visible_ids:
        if not _is_checked_out(doc, elem_id):
            continue

        element = doc.GetElement(elem_id)
        if not _can_temp_hide(element, active_view):
            continue

        owner = _get_owner_name(doc, elem_id)
        if owner not in owner_to_ids:
            owner_to_ids[owner] = List[DB.ElementId]()
        owner_to_ids[owner].Add(elem_id)

    if not owner_to_ids:
        forms.alert(
            "No checked out elements were found in this view.",
            title=TITLE,
        )
        return

    owner_labels = []
    label_to_owner = {}
    for owner in sorted(owner_to_ids.keys(), key=lambda o: o.lower()):
        label = "{} ({})".format(owner, owner_to_ids[owner].Count)
        owner_labels.append(label)
        label_to_owner[label] = owner

    selected_labels = forms.SelectFromList.show(
        owner_labels,
        title=TITLE,
        button_name="Isolate",
        multiselect=True,
        info_panel="Select one or more owners to temporarily isolate their elements in the active view.",
    )

    if not selected_labels:
        return

    to_isolate = List[DB.ElementId]()
    for label in selected_labels:
        owner = label_to_owner[label]
        for elem_id in owner_to_ids[owner]:
            to_isolate.Add(elem_id)

    if to_isolate.Count == 0:
        forms.alert("No elements found for selected owners.", title=TITLE)
        return

    with revit.Transaction("Temporarily isolate checked out elements"):
        active_view.IsolateElementsTemporary(to_isolate)

    forms.alert(
        "Temporarily isolated {} element(s) from {} owner(s).".format(
            to_isolate.Count,
            len(selected_labels),
        ),
        title=TITLE,
    )


if __name__ == "__main__":
    main()
