from pyrevit import revit, DB, forms
from System.Collections.Generic import List


def _owned_by_other_user(doc, elem_id):
    """Return True when an element is currently owned/borrowed by someone else."""
    try:
        checkout_status = DB.WorksharingUtils.GetCheckoutStatus(doc, elem_id)
        return checkout_status == DB.CheckoutStatus.OwnedByOtherUser
    except Exception:
        return False


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
            "This model is not workshared. There are no borrowed/checked-out elements to hide.",
            title="Hide Unavailable",
            warn_icon=True,
        )
        return

    if active_view is None:
        forms.alert("No active view found.", title="Hide Unavailable", warn_icon=True)
        return

    collector = (
        DB.FilteredElementCollector(doc, active_view.Id)
        .WhereElementIsNotElementType()
        .ToElementIds()
    )

    to_hide = List[DB.ElementId]()
    for elem_id in collector:
        if not _owned_by_other_user(doc, elem_id):
            continue

        element = doc.GetElement(elem_id)
        if _can_temp_hide(element, active_view):
            to_hide.Add(elem_id)

    if to_hide.Count == 0:
        forms.alert(
            "No elements in this view are currently checked out or borrowed by another user.",
            title="Hide Unavailable",
        )
        return

    # Temporary hide does not persist and can be reset with Reveal Hidden Elements/Reset Temporary Hide.
    with revit.Transaction("Hide unavailable elements"):
        active_view.HideElementsTemporary(to_hide)

    forms.alert(
        "Temporarily hid {} unavailable element(s) in the active view.".format(to_hide.Count),
        title="Hide Unavailable",
    )


if __name__ == "__main__":
    main()
