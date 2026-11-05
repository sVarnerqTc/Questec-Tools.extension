# -*- coding: utf-8 -*-
"""Shift+Click: pick a different underground level for this project."""

from pyrevit import forms

import underground_level


doc = __revit__.ActiveUIDocument.Document


def main():
    current = underground_level.get_saved_level(doc)
    level = underground_level.pick_level(doc, title="Change Underground Level")
    if level is None:
        return
    previous = current.Name if current is not None else "(none)"
    forms.alert(
        "Underground level saved for this project.\n\nPrevious: {0}\nNew: {1}\n\n"
        "Click the button (without Shift) to assign worksets.".format(previous, level.Name),
        title="Assign to Worksets",
    )


if __name__ == "__main__":
    main()
