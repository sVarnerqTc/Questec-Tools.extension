# -*- coding: utf-8 -*-
"""Save the open family into the new Dropbox content folder.

Run from the Family Editor. Takes the family's current path, finds the
"Imperial" folder in it (any capitalization), replaces everything up to and
including it with NEW_ROOT, and saves the family there with the same file name.

  Q:\\BIM Department\\Sysque\\Sysque Root Path\\SysQueContent2020\\BuildingData\\Imperial\\PressureFittings\\...\\X.rfa
  -> C:\\Questec Mechanical Dropbox\\Sysque Root Path\\SysQueContent2020\\BuildingData\\Imperial\\PressureFittings\\...\\X.rfa

Missing folders are created (after asking). If the file already exists you're
asked before it is overwritten. After saving, Revit works on the new copy.
"""

import os

from Autodesk.Revit.DB import SaveAsOptions
from pyrevit import forms


doc = __revit__.ActiveUIDocument.Document

TITLE = "Save as New Dropbox"
NEW_ROOT = r"C:\Questec Mechanical Dropbox\Sysque Root Path\SysQueContent2020\BuildingData\Imperial"
ANCHOR = "imperial"


def build_new_path(old_path):
    """Swap everything through the Imperial folder for NEW_ROOT. None if no Imperial folder."""
    parts = old_path.replace("/", "\\").split("\\")
    for index, part in enumerate(parts):
        if part.lower() == ANCHOR:
            return os.path.join(NEW_ROOT, *parts[index + 1:])
    return None


def main():
    if not doc.IsFamilyDocument:
        forms.alert("Open a family in the Family Editor, then run this again.", title=TITLE)
        return

    old_path = doc.PathName
    if not old_path:
        forms.alert("This family hasn't been saved yet, so there's no path to convert.\n\n"
                    "Save it once (in the old location), then run this again.", title=TITLE)
        return

    new_path = build_new_path(old_path)
    if new_path is None:
        forms.alert("There's no 'Imperial' folder in this family's path:\n\n{0}".format(old_path), title=TITLE)
        return

    if os.path.normcase(os.path.abspath(new_path)) == os.path.normcase(os.path.abspath(old_path)):
        forms.alert("This family is already saved in the new Dropbox:\n\n{0}".format(new_path), title=TITLE)
        return

    if not os.path.isdir(NEW_ROOT):
        forms.alert("The new Dropbox folder wasn't found on this computer:\n\n{0}".format(NEW_ROOT), title=TITLE)
        return

    folder = os.path.dirname(new_path)
    if not os.path.isdir(folder):
        if not forms.alert("This folder doesn't exist in the new Dropbox yet:\n\n{0}\n\nCreate it?".format(folder),
                           title=TITLE, yes=True, no=True):
            return
        try:
            os.makedirs(folder)
        except Exception as ex:
            forms.alert("Could not create the folder:\n\n{0}".format(ex), title=TITLE)
            return

    overwrite = False
    if os.path.isfile(new_path):
        if not forms.alert("A file with this name is already in the new Dropbox:\n\n{0}\n\nOverwrite it?".format(new_path),
                           title=TITLE, yes=True, no=True, warn_icon=True):
            return
        overwrite = True

    options = SaveAsOptions()
    options.OverwriteExistingFile = overwrite
    try:
        doc.SaveAs(new_path, options)
    except Exception as ex:
        forms.alert("Save failed:\n\n{0}".format(ex), title=TITLE)
        return

    forms.alert("Saved to the new Dropbox:\n\n{0}\n\nFrom:\n{1}{2}".format(
        new_path, old_path, "\n\n(Replaced the existing file.)" if overwrite else ""), title=TITLE)


if __name__ == "__main__":
    main()
