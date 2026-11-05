# -*- coding: utf-8 -*-
"""Add the Questec standard user worksets to a workshared project.

Worksets that already exist are skipped and listed in the summary.
"""

from Autodesk.Revit.DB import (
    FilteredWorksetCollector,
    Transaction,
    Workset,
    WorksetKind,
)
from Autodesk.Revit.UI import TaskDialog


doc = __revit__.ActiveUIDocument.Document

TITLE = "Create Standard Worksets"

STANDARD_WORKSETS = [
    "Pipe - Mechanical",
    "Pipe - Plumbing",
    "Pipe - Underground",
    "Hangers - Mechanical",
    "Hangers - Plumbing",
    "Points - Control",
    "Points - Layout",
    "Sheet Metal",
]


def get_existing_workset_names():
    worksets = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset).ToWorksets()
    return set(ws.Name.strip().lower() for ws in worksets)


def main():
    if doc.IsFamilyDocument:
        TaskDialog.Show(TITLE, "Worksets can't be created in a family document.")
        return

    if not doc.IsWorkshared:
        TaskDialog.Show(
            TITLE,
            "Worksharing is not enabled in this model.\n\n"
            "Enable it first (Collaborate > Worksets), then run this command again.",
        )
        return

    existing = get_existing_workset_names()
    to_create = [n for n in STANDARD_WORKSETS if n.strip().lower() not in existing]
    already_there = [n for n in STANDARD_WORKSETS if n.strip().lower() in existing]

    created = []
    failed = []

    if to_create:
        tx = Transaction(doc, TITLE)
        tx.Start()
        try:
            for name in to_create:
                try:
                    Workset.Create(doc, name)
                    created.append(name)
                except Exception as ex:
                    failed.append("{0} ({1})".format(name, ex))
            tx.Commit()
        except Exception as ex:
            tx.RollBack()
            TaskDialog.Show(TITLE, "Command failed, no worksets were created:\n\n{0}".format(ex))
            return

    lines = []
    if created:
        lines.append("Created ({0}):".format(len(created)))
        lines.extend("  " + n for n in created)
    if already_there:
        if lines:
            lines.append("")
        lines.append("Already existed, skipped ({0}):".format(len(already_there)))
        lines.extend("  " + n for n in already_there)
    if failed:
        if lines:
            lines.append("")
        lines.append("Failed ({0}):".format(len(failed)))
        lines.extend("  " + n for n in failed)

    if not created and not failed:
        lines.insert(0, "All standard worksets already exist. Nothing to do.\n")

    TaskDialog.Show(TITLE, "\n".join(lines))


if __name__ == "__main__":
    main()
