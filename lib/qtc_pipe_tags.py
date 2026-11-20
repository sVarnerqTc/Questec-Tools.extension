# -*- coding: utf-8 -*-
"""Shared logic for the Tag panel's pipe UP/DN tagging tools.

Replaces the Dynamo graphs "Tag Pipe UP and DN 1.3" and
"Tag Pipe Ups and Plumb Fixtures.Beta3.0":

  * Scope = current selection if there is one, otherwise everything in the
    active view. Only pipes are used.
  * A pipe "crosses" a level when one end is above the level and the other
    end is not (same XOR test as the graphs).
  * Crossing pipes get a tag of the chosen type, placed at an alignment point
    on the pipe's bounding box in the view, plus an X/Y offset in feet
    (same as Dynamo's Tag.ByElement).
"""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FamilySymbol,
    FilteredElementCollector,
    IndependentTag,
    Level,
    Reference,
    TagOrientation,
    Transaction,
    ViewPlan,
    XYZ,
)
from Autodesk.Revit.DB.Plumbing import Pipe


# ---------------------------------------------------------------- lookups

def get_type_label(symbol):
    family = ""
    name = ""
    try:
        family = symbol.FamilyName
    except Exception:
        pass
    param = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if param is not None and param.HasValue:
        name = param.AsString()
    return u"{0}:{1}".format(family, name)


def get_pipe_tag_types(doc):
    symbols = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_PipeTags)
        .OfClass(FamilySymbol)
        .WhereElementIsElementType()
        .ToElements()
    )
    return dict((get_type_label(s), s) for s in symbols)


def get_levels(doc):
    levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
    return sorted(levels, key=lambda lv: lv.ProjectElevation)


def find_level(levels, name):
    for lv in levels:
        if lv.Name == name:
            return lv
    return None


# ---------------------------------------------------------------- scope

def get_scope_pipes(doc, uidoc):
    """Return (pipes, used_selection)."""
    selected_ids = uidoc.Selection.GetElementIds()
    if selected_ids.Count > 0:
        elems = [doc.GetElement(i) for i in selected_ids]
        return [e for e in elems if isinstance(e, Pipe)], True

    pipes = (
        FilteredElementCollector(doc, doc.ActiveView.Id)
        .OfClass(Pipe)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    return list(pipes), False


def get_end_z(pipe):
    curve = pipe.Location.Curve
    return curve.GetEndPoint(0).Z, curve.GetEndPoint(1).Z


def crosses_level(pipe, level_z):
    """One end above the level, the other end not above it."""
    try:
        start_z, end_z = get_end_z(pipe)
    except Exception:
        return False
    return (start_z > level_z) != (end_z > level_z)


def level_internal_z(level):
    # ProjectElevation is measured from the internal origin, which is the
    # coordinate system pipe endpoints use. (The graphs did the same thing by
    # adding the project base point Z to Level.Elevation.)
    return level.ProjectElevation


# ---------------------------------------------------------------- tagging

def get_existing_tagged_ids(doc, view, tag_symbol):
    """Pipe ids already tagged in this view with this tag type."""
    tagged = set()
    tags = (
        FilteredElementCollector(doc, view.Id)
        .OfClass(IndependentTag)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    for tag in tags:
        if tag.GetTypeId() != tag_symbol.Id:
            continue
        try:
            ids = tag.GetTaggedLocalElementIds()  # Revit 2022+
        except AttributeError:
            ids = [tag.TaggedLocalElementId]
        for i in ids:
            tagged.add(i.IntegerValue)
    return tagged


def get_tag_point(pipe, view, h_align, v_align, offset_x, offset_y):
    box = pipe.get_BoundingBox(view) or pipe.get_BoundingBox(None)
    if box is None:
        return None

    if h_align == "Left":
        x = box.Min.X
    elif h_align == "Right":
        x = box.Max.X
    else:
        x = (box.Min.X + box.Max.X) / 2.0

    if v_align == "Top":
        y = box.Max.Y
    elif v_align == "Bottom":
        y = box.Min.Y
    else:
        y = (box.Min.Y + box.Max.Y) / 2.0

    z = (box.Min.Z + box.Max.Z) / 2.0
    return XYZ(x + offset_x, y + offset_y, z)


def tag_pipes(doc, view, pipes, tag_symbol, add_leader, h_align, v_align,
              offset_x, offset_y, horizontal=True):
    """Create tags. Must be called inside a transaction.
    Returns (created_count, skipped_already_tagged, failed)."""
    if not tag_symbol.IsActive:
        tag_symbol.Activate()

    already = get_existing_tagged_ids(doc, view, tag_symbol)
    orientation = TagOrientation.Horizontal if horizontal else TagOrientation.Vertical

    created = 0
    skipped = 0
    failed = 0
    for pipe in pipes:
        if pipe.Id.IntegerValue in already:
            skipped += 1
            continue
        point = get_tag_point(pipe, view, h_align, v_align, offset_x, offset_y)
        if point is None:
            failed += 1
            continue
        try:
            IndependentTag.Create(
                doc, tag_symbol.Id, view.Id, Reference(pipe), add_leader, orientation, point
            )
            created += 1
        except Exception:
            failed += 1
    return created, skipped, failed


def set_comments(pipes, value):
    count = 0
    for pipe in pipes:
        param = pipe.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if param is None or param.IsReadOnly:
            continue
        param.Set(value)
        count += 1
    return count


def is_taggable_view(view):
    return isinstance(view, ViewPlan)


def parse_feet(text, default=0.0):
    try:
        return float(str(text).strip())
    except Exception:
        return default
