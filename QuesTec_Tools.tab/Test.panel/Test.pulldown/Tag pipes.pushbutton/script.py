# -*- coding: utf-8 -*-
import math
import clr
clr.AddReference('System.Windows.Forms')
from System.Windows.Forms import Control, Keys
from pyrevit import revit, DB, forms, script


doc = revit.doc
active_view = revit.active_view

DEFAULT_TAG_FAMILY = 'QTC Pipe Tag'
DEFAULT_TAG_TYPE = 'Size/System Abbreviation'
ANGLE_TOLERANCE_DEG = 12.0
LINE_BUCKET_TOLERANCE_FT = 0.25


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


def collect_pipe_tag_symbols():
    symbols = DB.FilteredElementCollector(doc) \
        .OfClass(DB.FamilySymbol) \
        .OfCategory(DB.BuiltInCategory.OST_PipeTags) \
        .WhereElementIsElementType() \
        .ToElements()

    sorted_symbols = sorted(symbols, key=lambda s: tag_display_name(s).lower())
    return {tag_display_name(s): s for s in sorted_symbols}


def find_default_tag_symbol(symbols_by_name):
    exact_name = '{} : {}'.format(DEFAULT_TAG_FAMILY, DEFAULT_TAG_TYPE)
    if exact_name in symbols_by_name:
        return symbols_by_name[exact_name]

    family_lower = DEFAULT_TAG_FAMILY.lower()
    type_lower = DEFAULT_TAG_TYPE.lower()

    for display_name, symbol in symbols_by_name.items():
        name_lower = display_name.lower()
        if family_lower in name_lower and type_lower in name_lower:
            return symbol

    return None


def configure_tag_type():
    symbols_by_name = collect_pipe_tag_symbols()
    if not symbols_by_name:
        forms.alert('No pipe tag types were found in this project.', exitscript=True)

    default_symbol = find_default_tag_symbol(symbols_by_name)
    default_name = tag_display_name(default_symbol) if default_symbol else None

    prompt = 'Select Pipe Tag Type'
    if default_name:
        prompt += ' (default: {})'.format(default_name)

    selected_name = forms.SelectFromList.show(
        sorted(symbols_by_name.keys()),
        title=prompt,
        button_name='Select Pipe Tag',
        multiselect=False,
    )
    if not selected_name:
        forms.alert('Tag setup cancelled.', exitscript=True)

    config = script.get_config()
    config.pipe_tag_type_id = symbols_by_name[selected_name].Id.IntegerValue
    script.save_config()

    forms.alert('Saved pipe tag type: {}'.format(selected_name), title='Tag pipes')


def get_saved_or_default_tag_type_id():
    symbols_by_name = collect_pipe_tag_symbols()
    if not symbols_by_name:
        forms.alert('No pipe tag types were found in this project.', exitscript=True)

    config = script.get_config()
    saved_type_id = getattr(config, 'pipe_tag_type_id', None)

    if saved_type_id:
        saved_symbol = doc.GetElement(DB.ElementId(saved_type_id))
        if saved_symbol is not None:
            return saved_symbol.Id

    default_symbol = find_default_tag_symbol(symbols_by_name)
    if default_symbol is None:
        forms.alert(
            'No saved tag setup found and default tag type was not found. Use Shift+Click to configure tag type.',
            exitscript=True,
        )

    config.pipe_tag_type_id = default_symbol.Id.IntegerValue
    script.save_config()
    return default_symbol.Id


def get_pipe_length(pipe):
    length_param = pipe.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
    if length_param and length_param.HasValue:
        return length_param.AsDouble()

    location = pipe.Location
    if isinstance(location, DB.LocationCurve):
        return location.Curve.Length

    return 0.0


def get_param_string(elem, bip_list, name_list):
    for bip in bip_list:
        try:
            p = elem.get_Parameter(bip)
        except Exception:
            p = None

        if p and p.HasValue:
            value = p.AsString() or p.AsValueString()
            if value:
                return value.strip()

    for pname in name_list:
        p = elem.LookupParameter(pname)
        if p and p.HasValue:
            value = p.AsString() or p.AsValueString()
            if value:
                return value.strip()

    return '<No Value>'


def resolve_bips(*names):
    resolved = []
    for name in names:
        bip = getattr(DB.BuiltInParameter, name, None)
        if bip is not None:
            resolved.append(bip)
    return resolved


def get_system_key(pipe):
    return get_param_string(
        pipe,
        resolve_bips(
            'RBS_PIPING_SYSTEM_ABBREVIATION_PARAM',
            'RBS_PIPING_SYSTEM_TYPE_PARAM',
            'RBS_SYSTEM_NAME_PARAM',
        ),
        ['System Abbreviation', 'System Type', 'System Name'],
    )


def get_size_key(pipe):
    p = pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
    if p and p.HasValue:
        return str(round(p.AsDouble(), 8))

    return get_param_string(pipe, [], ['Size', 'Diameter', 'Nominal Diameter'])


def classify_pipe(pipe):
    location = pipe.Location
    if not isinstance(location, DB.LocationCurve):
        return None

    curve = location.Curve
    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)

    dx = end.X - start.X
    dy = end.Y - start.Y
    horiz_len = math.sqrt((dx * dx) + (dy * dy))
    if horiz_len < 1e-6:
        return None

    angle_from_x = math.degrees(math.atan2(abs(dy), abs(dx)))

    midpoint = curve.Evaluate(0.5, True)

    if angle_from_x <= ANGLE_TOLERANCE_DEG:
        bucket = int(round(midpoint.Y / LINE_BUCKET_TOLERANCE_FT))
        return ('EW', bucket)

    if abs(90.0 - angle_from_x) <= ANGLE_TOLERANCE_DEG:
        bucket = int(round(midpoint.X / LINE_BUCKET_TOLERANCE_FT))
        return ('NS', bucket)

    return None


def collect_representative_pipes():
    pipes = DB.FilteredElementCollector(doc, active_view.Id) \
        .OfClass(DB.Plumbing.Pipe) \
        .WhereElementIsNotElementType() \
        .ToElements()

    grouped = {}
    skipped_askew = 0
    skipped_no_curve = 0

    for pipe in pipes:
        orientation_data = classify_pipe(pipe)
        if orientation_data is None:
            location = pipe.Location
            if isinstance(location, DB.LocationCurve):
                skipped_askew += 1
            else:
                skipped_no_curve += 1
            continue

        orientation, line_bucket = orientation_data
        system_key = get_system_key(pipe)
        size_key = get_size_key(pipe)
        group_key = (orientation, line_bucket, system_key, size_key)

        length = get_pipe_length(pipe)
        existing = grouped.get(group_key)
        if existing is None or length > existing[1]:
            grouped[group_key] = (pipe, length)

    representatives = [v[0] for v in grouped.values()]
    return representatives, skipped_askew, skipped_no_curve


def get_tag_point(pipe):
    location = pipe.Location
    if isinstance(location, DB.LocationCurve):
        return location.Curve.Evaluate(0.5, True)

    return None


def tag_representative_pipes():
    pipe_tag_type_id = get_saved_or_default_tag_type_id()
    representatives, skipped_askew, skipped_no_curve = collect_representative_pipes()

    if not representatives:
        forms.alert('No representative pipes found to tag in the active view.', exitscript=True)

    tagged = 0
    failed = []

    with revit.Transaction('Tag pipes'):
        for pipe in representatives:
            point = get_tag_point(pipe)
            if point is None:
                failed.append('Id {}: no tag point'.format(pipe.Id.IntegerValue))
                continue

            try:
                tag = DB.IndependentTag.Create(
                    doc,
                    active_view.Id,
                    DB.Reference(pipe),
                    False,
                    DB.TagMode.TM_ADDBY_CATEGORY,
                    DB.TagOrientation.Horizontal,
                    point,
                )

                if tag.GetTypeId() != pipe_tag_type_id:
                    tag.ChangeTypeId(pipe_tag_type_id)

                tagged += 1
            except Exception as ex:
                failed.append('Id {}: {}'.format(pipe.Id.IntegerValue, ex))

    message = 'Tagged {} representative pipe(s).'.format(tagged)
    if skipped_askew:
        message += '\n\nSkipped {} pipe(s) that were not close to east-west or north-south.'.format(skipped_askew)
    if skipped_no_curve:
        message += '\nSkipped {} pipe(s) without a usable curve location.'.format(skipped_no_curve)
    if failed:
        message += '\n\nFailed to tag {} pipe(s):\n  {}'.format(
            len(failed),
            '\n  '.join(failed[:20]),
        )

    forms.alert(message, title='Tag pipes')


if __name__ == '__main__':
    modifier_keys = Control.ModifierKeys
    if modifier_keys == Keys.Shift:
        configure_tag_type()
    else:
        tag_representative_pipes()
