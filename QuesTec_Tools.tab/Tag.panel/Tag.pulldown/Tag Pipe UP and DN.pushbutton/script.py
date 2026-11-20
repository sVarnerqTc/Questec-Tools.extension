# -*- coding: utf-8 -*-
"""Tag pipes that rise through the UP deck level and/or drop through the DN
deck level in the active plan view.

Replaces the Dynamo graph "Tag Pipe UP and DN 1.3".
  * Scope: current selection if any, otherwise all pipes in the active view.
  * UP: pipes crossing the UP level get the UP tag type.
  * DN: pipes crossing the DN level get the DN tag type.
  * Pipes crossing BOTH levels (when both are tagged) get Comments = "&DN".
  * Tags are horizontal, centered on the pipe, plus the X/Y offset (feet).
  * Pipes that already have the same tag type in this view are skipped.
"""

from Autodesk.Revit.DB import Transaction
from pyrevit import forms, script
from rpw.ui.forms import FlexForm, Label, ComboBox, TextBox, CheckBox, Separator, Button

import qtc_pipe_tags as qpt


doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
TITLE = "Tag Pipe UP and DN"

DEFAULT_UP_TAG = "QTC Pipe Tag:UP"
DEFAULT_DN_TAG = "QTC Pipe Tag:DN"
BOTH_COMMENT = "&DN"


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

    up_level_default = pick_default(level_names, getattr(config, "up_level", ""))
    dn_level_default = pick_default(level_names, getattr(config, "dn_level", ""),
                                    getattr(config, "up_level", ""))

    components = [
        Label("Pipes in scope: {0} ({1})".format(
            len(pipes), "current selection" if used_selection else "all in active view")),
        Separator(),
        CheckBox("tag_up", "Tag UPs", default=getattr(config, "tag_up", True)),
        Label('"UP" deck level (pipes crossing it get the UP tag):'),
        ComboBox("up_level", level_names, default=up_level_default),
        Label("UP tag type:"),
        ComboBox("up_tag", tag_names,
                 default=pick_default(tag_names, getattr(config, "up_tag", ""), DEFAULT_UP_TAG)),
        Separator(),
        CheckBox("tag_dn", "Tag DNs", default=getattr(config, "tag_dn", True)),
        Label('"DN" deck level (pipes crossing it get the DN tag):'),
        ComboBox("dn_level", level_names, default=dn_level_default),
        Label("DN tag type:"),
        ComboBox("dn_tag", tag_names,
                 default=pick_default(tag_names, getattr(config, "dn_tag", ""), DEFAULT_DN_TAG)),
        Separator(),
        CheckBox("add_leader", "Add leader", default=getattr(config, "add_leader", False)),
        Label("X offset (ft):"),
        TextBox("offset_x", Text=str(getattr(config, "offset_x", "0"))),
        Label("Y offset (ft):"),
        TextBox("offset_y", Text=str(getattr(config, "offset_y", "0"))),
        Separator(),
        Button("Tag Pipes"),
    ]
    form = FlexForm(TITLE, components)
    if not form.show():
        return
    v = form.values

    if not v["tag_up"] and not v["tag_dn"]:
        forms.alert("Neither Tag UPs nor Tag DNs was checked. Nothing to do.", title=TITLE)
        return

    offset_x = qpt.parse_feet(v["offset_x"])
    offset_y = qpt.parse_feet(v["offset_y"])

    # Remember choices
    config.tag_up = v["tag_up"]
    config.tag_dn = v["tag_dn"]
    config.up_level = v["up_level"]
    config.dn_level = v["dn_level"]
    config.up_tag = v["up_tag"]
    config.dn_tag = v["dn_tag"]
    config.add_leader = v["add_leader"]
    config.offset_x = str(offset_x)
    config.offset_y = str(offset_y)
    script.save_config()

    up_pipes = []
    dn_pipes = []
    if v["tag_up"]:
        up_z = qpt.level_internal_z(qpt.find_level(levels, v["up_level"]))
        up_pipes = [p for p in pipes if qpt.crosses_level(p, up_z)]
    if v["tag_dn"]:
        dn_z = qpt.level_internal_z(qpt.find_level(levels, v["dn_level"]))
        dn_pipes = [p for p in pipes if qpt.crosses_level(p, dn_z)]

    dn_ids = set(p.Id.IntegerValue for p in dn_pipes)
    both = [p for p in up_pipes if p.Id.IntegerValue in dn_ids] if (v["tag_up"] and v["tag_dn"]) else []

    if not up_pipes and not dn_pipes:
        forms.alert("No pipes cross the chosen level(s).", title=TITLE)
        return

    results = []
    tx = Transaction(doc, TITLE)
    tx.Start()
    try:
        if up_pipes:
            c, s, f = qpt.tag_pipes(doc, view, up_pipes, tag_types[v["up_tag"]], v["add_leader"],
                                    "Center", "Middle", offset_x, offset_y)
            results.append(("UP", v["up_level"], len(up_pipes), c, s, f))
        if both:
            comments_set = qpt.set_comments(both, BOTH_COMMENT)
        else:
            comments_set = 0
        if dn_pipes:
            c, s, f = qpt.tag_pipes(doc, view, dn_pipes, tag_types[v["dn_tag"]], v["add_leader"],
                                    "Center", "Middle", offset_x, offset_y)
            results.append(("DN", v["dn_level"], len(dn_pipes), c, s, f))
        tx.Commit()
    except Exception as ex:
        tx.RollBack()
        forms.alert("Command failed, nothing was changed:\n\n{0}".format(ex), title=TITLE)
        return

    lines = []
    for kind, level_name, found, created, skipped, failed in results:
        lines.append("{0} ({1}): {2} pipes cross the level".format(kind, level_name, found))
        lines.append("  Tagged: {0}".format(created))
        if skipped:
            lines.append("  Already tagged, skipped: {0}".format(skipped))
        if failed:
            lines.append("  Could not tag: {0}".format(failed))
        lines.append("")
    if comments_set:
        lines.append('{0} pipes cross both levels; Comments set to "{1}".'.format(comments_set, BOTH_COMMENT))
    forms.alert("\n".join(lines).strip(), title=TITLE)


if __name__ == "__main__":
    main()
