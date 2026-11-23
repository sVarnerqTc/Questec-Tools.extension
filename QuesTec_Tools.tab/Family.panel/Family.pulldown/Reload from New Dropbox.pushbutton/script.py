# -*- coding: utf-8 -*-
"""Reload families from the new Dropbox content folder.

For each chosen family:
  1. Get the path it was loaded from (e.g. Q:\\BIM Department\\Sysque\\...\\Imperial\\PressureFittings\\...\\X.rfa).
  2. Find the "Imperial" folder in that path (any capitalization).
  3. Replace everything up to and including it with NEW_ROOT, keeping the rest.
  4. Reload the family from that new path.

Families come from the selected elements, or from a checklist if nothing is selected.
Each run asks whether to keep the project's parameter values or overwrite them.
"""

import os

import clr
from Autodesk.Revit.DB import (
    ElementId,
    Family,
    FamilyInstance,
    FamilySource,
    FilteredElementCollector,
    IFamilyLoadOptions,
    Transaction,
)
from pyrevit import forms, script


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

TITLE = "Reload from New Dropbox"
NEW_ROOT = r"C:\Questec Mechanical Dropbox\Sysque Root Path\SysQueContent2020\BuildingData\Imperial"
ANCHOR = "imperial"

KEEP_VALUES = "Keep Project Parameter Values"
OVERWRITE_VALUES = "Overwrite Parameter Values"


class ReloadOptions(IFamilyLoadOptions):
    def __init__(self, overwrite_values):
        self.overwrite_values = overwrite_values

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = self.overwrite_values
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = FamilySource.Family
        overwriteParameterValues.Value = self.overwrite_values
        return True


# ---------------------------------------------------------------- helpers

def family_label(family):
    category = family.FamilyCategory.Name if family.FamilyCategory else "No Category"
    return u"{0}: {1}".format(category, family.Name)


def families_from_selection():
    families = {}
    for element_id in uidoc.Selection.GetElementIds():
        element = doc.GetElement(element_id)
        family = None
        if isinstance(element, Family):
            family = element
        elif isinstance(element, FamilyInstance):
            family = element.Symbol.Family
        else:
            try:
                symbol = doc.GetElement(element.GetTypeId())
                family = getattr(symbol, "Family", None)
            except Exception:
                family = None
        if family is not None and family.IsEditable and not family.IsInPlace:
            families[family.Id.IntegerValue] = family
    return list(families.values())


def pick_families():
    families = [f for f in FilteredElementCollector(doc).OfClass(Family) if f.IsEditable and not f.IsInPlace]
    options = dict((family_label(f), f) for f in families)
    chosen = forms.SelectFromList.show(
        sorted(options.keys()),
        title="Select Families to Reload from the New Dropbox",
        button_name="Reload Selected",
        multiselect=True,
    )
    if not chosen:
        return []
    if not isinstance(chosen, list):
        chosen = [chosen]
    return [options[c] for c in chosen]


def get_saved_path(family):
    """Path the family was last loaded from, read from the family document."""
    family_doc = doc.EditFamily(family)
    try:
        return family_doc.PathName or ""
    finally:
        family_doc.Close(False)


def build_new_path(old_path):
    """Swap everything through the Imperial folder for NEW_ROOT. None if no Imperial folder."""
    parts = old_path.replace("/", "\\").split("\\")
    for index, part in enumerate(parts):
        if part.lower() == ANCHOR:
            return os.path.join(NEW_ROOT, *parts[index + 1:])
    return None


# ---------------------------------------------------------------- main

def main():
    if doc.IsFamilyDocument:
        forms.alert("Run this from a project, not a family document.", title=TITLE)
        return

    families = families_from_selection()
    if families:
        source_label = "selected elements"
    else:
        families = pick_families()
        source_label = "family list"
    if not families:
        return

    mode = forms.CommandSwitchWindow.show(
        [KEEP_VALUES, OVERWRITE_VALUES],
        message="{0} famil{1} chosen. How should existing parameter values be handled?".format(
            len(families), "y" if len(families) == 1 else "ies"),
    )
    if not mode:
        return
    overwrite_values = (mode == OVERWRITE_VALUES)

    # Work out the new path for each family (must happen outside a transaction).
    ready = []     # (family, old path, new path)
    skipped = []   # (family name, reason)
    with forms.ProgressBar(title="Reading family paths ({value} of {max_value})") as bar:
        for i, family in enumerate(families):
            bar.update_progress(i + 1, len(families))
            name = family.Name
            try:
                old_path = get_saved_path(family)
            except Exception as ex:
                skipped.append((name, "could not read its path ({0})".format(ex)))
                continue
            if not old_path:
                skipped.append((name, "no saved path in the project"))
                continue
            new_path = build_new_path(old_path)
            if new_path is None:
                skipped.append((name, "no 'Imperial' folder in its path: {0}".format(old_path)))
                continue
            if not os.path.isfile(new_path):
                skipped.append((name, "not found in the new Dropbox: {0}".format(new_path)))
                continue
            file_name = os.path.splitext(os.path.basename(new_path))[0]
            if file_name.lower() != name.lower():
                skipped.append((name, "file name '{0}' doesn't match the family name, so it would "
                                      "load as a new family".format(file_name)))
                continue
            ready.append((family, old_path, new_path))

    reloaded = []
    failed = []
    if ready:
        options = ReloadOptions(overwrite_values)
        for family, old_path, new_path in ready:
            name = family.Name
            tx = Transaction(doc, "{0}: {1}".format(TITLE, name))
            tx.Start()
            try:
                loaded = clr.Reference[Family]()
                doc.LoadFamily(new_path, options, loaded)
                tx.Commit()
                reloaded.append((name, new_path))
            except Exception as ex:
                tx.RollBack()
                failed.append((name, str(ex)))

    output = script.get_output()
    lines = ["Source: {0}".format(source_label),
             "Mode: {0}".format(mode),
             "",
             "Reloaded {0} of {1} famil{2}.".format(len(reloaded), len(families),
                                                    "y" if len(families) == 1 else "ies")]
    if skipped or failed:
        lines.append("Not reloaded: {0} (details in the output window)".format(len(skipped) + len(failed)))
        output.print_md("## {0} - not reloaded".format(TITLE))
        for name, reason in skipped + failed:
            output.print_md(u"* **{0}**: {1}".format(name, reason))
    if reloaded:
        output.print_md("## Reloaded from")
        for name, path in reloaded:
            output.print_md(u"* **{0}**: {1}".format(name, path))
    forms.alert("\n".join(lines), title=TITLE)


if __name__ == "__main__":
    main()
