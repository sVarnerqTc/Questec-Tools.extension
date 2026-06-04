# -*- coding: utf-8 -*-
import math
from pyrevit import revit, DB, forms
from System.Collections.Generic import List

doc = revit.doc
active_view = revit.active_view


def get_elem_length(elem):
    """Best-effort representative length for fittings/accessories."""
    length_param = elem.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
    if length_param and length_param.HasValue:
        return length_param.AsDouble()

    for pname in ('Length', 'LENGTH', 'Overall Length', 'Nominal Length'):
        p = elem.LookupParameter(pname)
        if p and p.HasValue:
            try:
                return p.AsDouble()
            except Exception:
                pass

    bbox = elem.get_BoundingBox(None)
    if bbox:
        dx = abs(bbox.Max.X - bbox.Min.X)
        dy = abs(bbox.Max.Y - bbox.Min.Y)
        dz = abs(bbox.Max.Z - bbox.Min.Z)
        return max(dx, dy, dz)

    return 0.0


def safe_type_name(elem):
    symbol = getattr(elem, 'Symbol', None)
    if symbol:
        p = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.HasValue:
            name = p.AsString()
            if name:
                return name
        try:
            return symbol.FamilyName or ''
        except Exception:
            return ''
    return ''


def safe_family_name(elem):
    symbol = getattr(elem, 'Symbol', None)
    if symbol:
        p = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        if p and p.HasValue:
            name = p.AsString()
            if name:
                return name
        family = getattr(symbol, 'Family', None)
        if family:
            try:
                p2 = family.get_Parameter(DB.BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if p2 and p2.HasValue:
                    name2 = p2.AsString()
                    if name2:
                        return name2
            except Exception:
                pass
    return ''


def choose_fitting_accessory(candidates):
    preferred = []
    for elem in candidates:
        lowered = safe_family_name(elem).lower()
        if 'unistrut' in lowered or 'angle' in lowered:
            preferred.append(elem)

    pick_pool = preferred if preferred else candidates
    return max(pick_pool, key=get_elem_length)


is_2d_view = not isinstance(active_view, DB.View3D)

# Collect all pipes in the active view
pipes = DB.FilteredElementCollector(doc, active_view.Id) \
          .OfClass(DB.Plumbing.Pipe) \
          .ToElements()

# spool_tag -> list of (pipe, is_horizontal, length)
spool_data = {}

for pipe in pipes:
    # Get Spool Tag parameter
    spool_tag_param = pipe.LookupParameter('Spool Tag')
    if spool_tag_param is None or not spool_tag_param.HasValue:
        spool_tag = '<No Spool Tag>'
    else:
        spool_tag = spool_tag_param.AsString() or '<No Spool Tag>'

    # Get pipe curve
    location = pipe.Location
    if not isinstance(location, DB.LocationCurve):
        continue
    curve = location.Curve

    # Determine slope angle from horizontal using endpoints
    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)
    dx = end.X - start.X
    dy = end.Y - start.Y
    dz = end.Z - start.Z
    horiz_run = math.sqrt(dx ** 2 + dy ** 2)
    vert_rise = abs(dz)

    if horiz_run == 0 and vert_rise == 0:
        continue

    angle_from_horizontal = math.degrees(math.atan2(vert_rise, horiz_run))
    is_horizontal = angle_from_horizontal < 45.0

    # Get length from built-in parameter
    length_param = pipe.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
    length = length_param.AsDouble() if length_param else curve.Length

    spool_data.setdefault(spool_tag, []).append((pipe, is_horizontal, length))

# Collect pipe accessories and fittings in the active view, grouped by Spool Tag
# spool_tag -> list of candidate elements (used as fallback representative)
fitting_accessory_spool = {}

non_pipe_elements = DB.FilteredElementCollector(doc, active_view.Id) \
                      .OfClass(DB.FamilyInstance) \
                      .ToElements()

for elem in non_pipe_elements:
    cat_id = elem.Category.Id.IntegerValue if elem.Category else None
    if cat_id not in (
        int(DB.BuiltInCategory.OST_PipeFitting),
        int(DB.BuiltInCategory.OST_PipeAccessory),
    ):
        continue
    spool_tag_param = elem.LookupParameter('Spool Tag')
    if spool_tag_param is None or not spool_tag_param.HasValue:
        continue
    tag = spool_tag_param.AsString()
    if not tag:
        continue
    fitting_accessory_spool.setdefault(tag, []).append(elem)

# For each spool tag pick the representative pipe
result_pipe_ids = []
represented_pipe_tags = set()
vertical_pipe_skipped_tags = []
fallback_debug = {}

for spool_tag, pipe_list in spool_data.items():
    horizontal_pipes = [(p, l) for p, is_h, l in pipe_list if is_h]

    if horizontal_pipes:
        best = max(horizontal_pipes, key=lambda x: x[1])[0]
        result_pipe_ids.append(best.Id)
        represented_pipe_tags.add(spool_tag)
    elif not is_2d_view:
        best = max(pipe_list, key=lambda x: x[2])[0]
        result_pipe_ids.append(best.Id)
        represented_pipe_tags.add(spool_tag)
    else:
        vertical_pipe_skipped_tags.append(spool_tag)

# Add one representative fitting/accessory for each spool tag with no selected pipe
fallback_tags = [t for t in fitting_accessory_spool if t not in represented_pipe_tags]
for tag in fallback_tags:
    chosen_elem = choose_fitting_accessory(fitting_accessory_spool[tag])
    result_pipe_ids.append(chosen_elem.Id)
    family_name = safe_family_name(chosen_elem)
    type_name = safe_type_name(chosen_elem)
    fallback_debug[tag] = '{} : {} (Id {})'.format(
        family_name if family_name else '<No Family>',
        type_name if type_name else '<No Type>',
        chosen_elem.Id.IntegerValue,
    )

if not result_pipe_ids:
    forms.alert('No elements to isolate.', exitscript=True)

element_id_list = List[DB.ElementId](result_pipe_ids)

# Temporary isolate in the active view (requires a transaction)
t = DB.Transaction(doc, 'Isolate Spool Rep Pipes')
t.Start()
active_view.IsolateElementsTemporary(element_id_list)
t.Commit()

# Build summary message
msg = 'Isolated {} element(s) - one representative per spool tag.'.format(len(result_pipe_ids))

orphan_tags = [t for t in fitting_accessory_spool if t not in spool_data]
if orphan_tags:
    msg += '\n\nInfo: the following spool tag(s) have no pipe in this view ' \
           '(represented by a fitting/accessory):\n  ' + '\n  '.join(sorted(orphan_tags))

if vertical_pipe_skipped_tags:
    msg += '\n\nInfo: in this 2D view, vertical-only pipe spool tag(s) were represented by fittings/accessories when available:\n  ' \
           + '\n  '.join(sorted(set(vertical_pipe_skipped_tags)))

if fallback_debug:
    msg += '\n\nDebug: fallback representative chosen per spool tag:\n  ' + '\n  '.join(
        '{} -> {}'.format(tag, fallback_debug[tag]) for tag in sorted(fallback_debug)
    )

forms.alert(msg)
