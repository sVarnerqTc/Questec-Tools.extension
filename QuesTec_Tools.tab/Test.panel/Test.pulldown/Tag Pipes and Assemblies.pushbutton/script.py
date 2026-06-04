# -*- coding: utf-8 -*-
import math
import System.Windows.Forms
from pyrevit import revit, DB, forms, script


doc = revit.doc
active_view = revit.active_view


def get_elem_length(elem):
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


def get_repr_elements():
    is_2d_view = not isinstance(active_view, DB.View3D)

    pipes = DB.FilteredElementCollector(doc, active_view.Id) \
              .OfClass(DB.Plumbing.Pipe) \
              .ToElements()

    spool_data = {}
    for pipe in pipes:
        spool_tag_param = pipe.LookupParameter('Spool Tag')
        if spool_tag_param is None or not spool_tag_param.HasValue:
            spool_tag = '<No Spool Tag>'
        else:
            spool_tag = spool_tag_param.AsString() or '<No Spool Tag>'

        location = pipe.Location
        if not isinstance(location, DB.LocationCurve):
            continue
        curve = location.Curve

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

        length_param = pipe.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
        length = length_param.AsDouble() if length_param else curve.Length

        spool_data.setdefault(spool_tag, []).append((pipe, is_horizontal, length))

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

    result_elements = []
    represented_pipe_tags = set()

    for spool_tag, pipe_list in spool_data.items():
        horizontal_pipes = [(p, l) for p, is_h, l in pipe_list if is_h]

        if horizontal_pipes:
            best = max(horizontal_pipes, key=lambda x: x[1])[0]
            result_elements.append(best)
            represented_pipe_tags.add(spool_tag)
        elif not is_2d_view:
            best = max(pipe_list, key=lambda x: x[2])[0]
            result_elements.append(best)
            represented_pipe_tags.add(spool_tag)

    fallback_tags = [t for t in fitting_accessory_spool if t not in represented_pipe_tags]
    for tag in fallback_tags:
        result_elements.append(choose_fitting_accessory(fitting_accessory_spool[tag]))

    return result_elements


def tag_display_name(symbol):
    family = ''
    type_name = ''

    p_fam = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
    if p_fam and p_fam.HasValue:
        family = p_fam.AsString() or ''

    p_type = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    if p_type and p_type.HasValue:
        type_name = p_type.AsString() or ''

    if not family:
        try:
            family = symbol.FamilyName or ''
        except Exception:
            family = ''

    if family and type_name:
        return '{} : {}'.format(family, type_name)
    return family or type_name or str(symbol.Id.IntegerValue)


def collect_tag_symbols(bic):
    symbols = DB.FilteredElementCollector(doc) \
        .OfClass(DB.FamilySymbol) \
        .OfCategory(bic) \
        .WhereElementIsElementType() \
        .ToElements()

    sorted_symbols = sorted(symbols, key=lambda s: tag_display_name(s).lower())
    return {tag_display_name(s): s.Id.IntegerValue for s in sorted_symbols}


def configure_tags():
    pipe_tags = collect_tag_symbols(DB.BuiltInCategory.OST_PipeTags)
    if not pipe_tags:
        forms.alert('No pipe tag types were found in this project.', exitscript=True)

    multi_tags = collect_tag_symbols(DB.BuiltInCategory.OST_MultiCategoryTags)
    if not multi_tags:
        forms.alert('No multi-category tag types were found in this project.', exitscript=True)

    selected_pipe = forms.SelectFromList.show(
        sorted(pipe_tags.keys()),
        title='Select Pipe Tag Type',
        button_name='Select Pipe Tag',
        multiselect=False
    )
    if not selected_pipe:
        forms.alert('Tag setup cancelled.', exitscript=True)

    selected_multi = forms.SelectFromList.show(
        sorted(multi_tags.keys()),
        title='Select Multi-Category Tag Type',
        button_name='Select Multi-Tag',
        multiselect=False
    )
    if not selected_multi:
        forms.alert('Tag setup cancelled.', exitscript=True)

    config = script.get_config()
    config.pipe_tag_type_id = pipe_tags[selected_pipe]
    config.multi_tag_type_id = multi_tags[selected_multi]
    script.save_config()

    forms.alert(
        'Saved tag setup:\n\nPipe Tag: {}\nMulti-Category Tag: {}'.format(
            selected_pipe,
            selected_multi,
        ),
        title='Tag Pipes and Assemblies'
    )


def get_saved_tag_type_ids():
    config = script.get_config()
    pipe_id = getattr(config, 'pipe_tag_type_id', None)
    multi_id = getattr(config, 'multi_tag_type_id', None)

    if not pipe_id or not multi_id:
        forms.alert('No tag setup found. Use Shift+Click to configure tag types.', exitscript=True)

    pipe_tag_type = doc.GetElement(DB.ElementId(pipe_id))
    multi_tag_type = doc.GetElement(DB.ElementId(multi_id))

    if pipe_tag_type is None or multi_tag_type is None:
        forms.alert('Saved tag type(s) are missing. Use Shift+Click to reconfigure.', exitscript=True)

    return pipe_tag_type.Id, multi_tag_type.Id


def get_tag_point(elem):
    loc = elem.Location
    if isinstance(loc, DB.LocationCurve):
        curve = loc.Curve
        return curve.Evaluate(0.5, True)

    if isinstance(loc, DB.LocationPoint):
        return loc.Point

    bbox = elem.get_BoundingBox(active_view) or elem.get_BoundingBox(None)
    if bbox:
        return DB.XYZ(
            (bbox.Min.X + bbox.Max.X) * 0.5,
            (bbox.Min.Y + bbox.Max.Y) * 0.5,
            (bbox.Min.Z + bbox.Max.Z) * 0.5,
        )

    return None


def tag_representatives():
    pipe_tag_type_id, multi_tag_type_id = get_saved_tag_type_ids()
    rep_elements = get_repr_elements()

    if not rep_elements:
        forms.alert('No representative elements found to tag.', exitscript=True)

    tagged = 0
    failed = []

    with revit.Transaction('Tag Pipes and Assemblies'):
        for elem in rep_elements:
            point = get_tag_point(elem)
            if point is None:
                failed.append('Id {}: no tag point'.format(elem.Id.IntegerValue))
                continue

            cat_id = elem.Category.Id.IntegerValue if elem.Category else None
            if cat_id == int(DB.BuiltInCategory.OST_PipeCurves):
                tag_type_id = pipe_tag_type_id
            else:
                tag_type_id = multi_tag_type_id

            try:
                tag = DB.IndependentTag.Create(
                    doc,
                    active_view.Id,
                    DB.Reference(elem),
                    False,
                    DB.TagMode.TM_ADDBY_CATEGORY,
                    DB.TagOrientation.Horizontal,
                    point,
                )
                if tag_type_id and tag.GetTypeId() != tag_type_id:
                    tag.ChangeTypeId(tag_type_id)
                tagged += 1
            except Exception as ex:
                failed.append('Id {}: {}'.format(elem.Id.IntegerValue, ex))

    msg = 'Tagged {} representative element(s).'.format(tagged)
    if failed:
        msg += '\n\nFailed to tag {} element(s):\n  {}'.format(
            len(failed),
            '\n  '.join(failed[:20])
        )

    forms.alert(msg, title='Tag Pipes and Assemblies')


if __name__ == '__main__':
    modifier_keys = System.Windows.Forms.Control.ModifierKeys
    if modifier_keys == System.Windows.Forms.Keys.Shift:
        configure_tags()
    else:
        tag_representatives()
