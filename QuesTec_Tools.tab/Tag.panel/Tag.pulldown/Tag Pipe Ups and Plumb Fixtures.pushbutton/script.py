# -*- coding: utf-8 -*-
"""Tag pipes that rise through a deck level in the active plan view.

Replaces the Dynamo graph "Tag Pipe Ups and Plumb Fixtures.Beta3.0".
  * Scope: current selection if any, otherwise all pipes in the active view.
  * Pipes crossing the deck level get the UP tag type.
  * Tags are horizontal, at the bottom-right of the pipe, plus the X/Y offset
    (feet). Default offset is 1 ft up, as in the graph.
  * Pipes that already have the same tag type in this view are skipped.

Note: despite its name, the original graph only tagged pipes, not plumbing
fixtures, so this does the same.
"""

from Autodesk.Revit.DB import Transaction
from pyrevit import forms, script
from rpw.ui.forms import FlexForm, Label, ComboBox, TextBox, CheckBox, Separator, Button

import qtc_pipe_tags as qpt


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
TITLE = "Tag Pipe Ups and Plumb Fixtures"

DEFAULT_TAG = "Pipe Tag QTC:UP"
H_ALIGN = "Right"
V_ALIGN = "Bottom"


def pick_default(options, *preferred):
    for p in preferred:
        if p in options:
            return p
    return options[0] if options else None


def main():
    view = doc.ActiveView
    if not qpt.is_taggable_view(view):
        forms.alert("Open a floor plan view and run this again.", title=TITLE)
        return

    tag_types = qpt.get_pipe_tag_types(doc)
    if not tag_types:
        forms.alert("No pipe tag types are loaded in this project.", title=TITLE)
        return
    levels = qpt.get_levels(doc)
    if not levels:
        forms.alert("No levels found.", title=TITLE)
        return

    pipes, used_selection = qpt.get_scope_pipes(doc, uidoc)
    if not pipes:
        forms.alert(
            "No pipes in the {0}.".format("selection" if used_selection else "active view"),
            title=TITLE,
        )
        return

    config = script.get_config()
    tag_names = sorted(tag_types.keys())
    level_names = [lv.Name for lv in levels]
    view_level = getattr(view, "GenLevel", None)

    components = [
        Label("Pipes in scope: {0} ({1})".format(
            len(pipes), "current selection" if used_selection else "all in active view")),
        Separator(),
        Label("Deck level (pipes crossing it get tagged):"),
        ComboBox("level", level_names, default=pick_default(
            level_names, getattr(config, "level", ""), view_level.Name if view_level else "")),
        Label("Tag type:"),
        ComboBox("tag", tag_names,
                 default=pick_default(tag_names, getattr(config, "tag", ""), DEFAULT_TAG, "QTC Pipe Tag:UP")),
        Separator(),
        CheckBox("add_leader", "Add leader", default=getattr(config, "add_leader", False)),
        Label("X offset (ft):"),
        TextBox("offset_x", Text=str(getattr(config, "offset_x", "0"))),
        Label("Y offset (ft):"),
        TextBox("offset_y", Text=str(getattr(config, "offset_y", "1"))),
        Separator(),
        Button("Tag Pipes"),
    ]
    form = FlexForm(TITLE, components)
    if not form.show():
        return
    v = form.values

    offset_x = qpt.parse_feet(v["offset_x"])
    offset_y = qpt.parse_feet(v["offset_y"], 1.0)

    config.level = v["level"]
    config.tag = v["tag"]
    config.add_leader = v["add_leader"]
    config.offset_x = str(offset_x)
    config.offset_y = str(offset_y)
    script.save_config()

    level_z = qpt.level_internal_z(qpt.find_level(levels, v["level"]))
    up_pipes = [p for p in pipes if qpt.crosses_level(p, level_z)]
    if not up_pipes:
        forms.alert("No pipes cross {0}.".format(v["level"]), title=TITLE)
        return

    tx = Transaction(doc, TITLE)
    tx.Start()
    try:
        created, skipped, failed = qpt.tag_pipes(
            doc, view, up_pipes, tag_types[v["tag"]], v["add_leader"],
            H_ALIGN, V_ALIGN, offset_x, offset_y)
        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        forms.alert("Command failed, nothing was changed:\n\n{0}".format(ex), title=TITLE)
        return

    lines = ["{0} pipes cross {1}".format(len(up_pipes), v["level"]),
             "Tagged: {0}".format(created)]
    if skipped:
        lines.append("Already tagged, skipped: {0}".format(skipped))
    if failed:
        lines.append("Could not tag: {0}".format(failed))
    forms.alert("\n".join(lines), title=TITLE)


if __name__ == "__main__":
    main()
