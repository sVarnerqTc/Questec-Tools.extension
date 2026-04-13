# -*- coding: utf-8 -*-
import math
from pyrevit import revit, DB, forms
from System.Collections.Generic import List

doc = revit.doc
active_view = revit.active_view

# Collect all pipes in the active view
pipes = DB.FilteredElementCollector(doc, active_view.Id) \
          .OfClass(DB.Plumbing.Pipe) \
          .ToElements()

if not pipes:
    forms.alert('No pipes found in the active view.', exitscript=True)

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

if not spool_data:
    forms.alert('No pipes with valid geometry found.', exitscript=True)

# Collect pipe accessories and fittings in the active view, grouped by Spool Tag
# spool_tag -> first element found (used as fallback representative)
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
    fitting_accessory_spool.setdefault(tag, elem)

# Spool tags on fittings/accessories that have NO pipe in the view
pipe_spool_tags = set(spool_data.keys())
orphan_tags = [t for t in fitting_accessory_spool if t not in pipe_spool_tags]

# For each spool tag pick the representative pipe
result_pipe_ids = []

for spool_tag, pipe_list in spool_data.items():
    horizontal_pipes = [(p, l) for p, is_h, l in pipe_list if is_h]

    if horizontal_pipes:
        best = max(horizontal_pipes, key=lambda x: x[1])[0]
    else:
        best = max(pipe_list, key=lambda x: x[2])[0]

    result_pipe_ids.append(best.Id)

# Add one representative element for each orphan spool tag
for tag in orphan_tags:
    result_pipe_ids.append(fitting_accessory_spool[tag].Id)

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
if orphan_tags:
    msg += '\n\nWarning: the following spool tag(s) have no pipe in this view ' \
           '(represented by a fitting/accessory):\n  ' + '\n  '.join(sorted(orphan_tags))

forms.alert(msg)
