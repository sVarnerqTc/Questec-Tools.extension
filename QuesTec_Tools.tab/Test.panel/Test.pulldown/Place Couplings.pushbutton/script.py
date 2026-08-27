# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB.Plumbing import Pipe, PlumbingUtils

__title__ = 'Place\nCouplings'
__author__ = 'QuesTec BIM'

# Pipe type display name -> max length (in feet)
MAX_LENGTH_BY_TYPE_NAME = {
    'Pipe, Type L Hard Copper QTC': 20.0,
}

LENGTH_TOLERANCE_FT = 1e-6
CONNECTOR_TOLERANCE_FT = 1e-4
MAX_SPLITS_PER_PIPE = 100


doc = revit.doc
active_view = revit.active_view
output = script.get_output()


def normalize_name(value):
    return (value or '').strip().lower()


def safe_name_from_element(elem):
    if elem is None:
        return ''

    p_name = elem.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    if p_name and p_name.HasValue:
        value = p_name.AsString()
        if value:
            return value

    p_type_name = elem.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_NAME)
    if p_type_name and p_type_name.HasValue:
        value = p_type_name.AsString()
        if value:
            return value

    name_attr = getattr(elem, 'Name', None)
    if name_attr:
        try:
            return str(name_attr)
        except Exception:
            pass

    return ''


def safe_family_name_from_type(elem_type):
    if elem_type is None:
        return ''

    family_param = elem_type.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
    if family_param and family_param.HasValue:
        value = family_param.AsString()
        if value:
            return value

    return ''


def get_pipe_length(pipe):
    location = pipe.Location
    if isinstance(location, DB.LocationCurve):
        return location.Curve.Length

    length_param = pipe.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
    if length_param and length_param.HasValue:
        return length_param.AsDouble()

    return 0.0


def get_pipe_name_candidates(pipe):
    names = set()

    pipe_name = safe_name_from_element(pipe)
    if pipe_name:
        names.add(pipe_name)

    pipe_type = doc.GetElement(pipe.GetTypeId())
    if pipe_type:
        type_name = safe_name_from_element(pipe_type)
        if type_name:
            names.add(type_name)

        family_name = safe_family_name_from_type(pipe_type)

        if family_name and type_name:
            names.add('{}, {}'.format(family_name, type_name))
            names.add('{} : {}'.format(family_name, type_name))

    return [normalize_name(n) for n in names if n]


def fmt_ft(value):
    return '{:.4f} ft'.format(value)


def fmt_in(value):
    return '{:.3f} in'.format(value * 12.0)


def get_max_length_for_pipe(pipe, rule_map):
    for candidate in get_pipe_name_candidates(pipe):
        if candidate in rule_map:
            return rule_map[candidate]
    return None


def get_pipe_end_connectors(pipe):
    connectors = []
    connector_set = pipe.ConnectorManager.Connectors
    for conn in connector_set:
        if conn.ConnectorType == DB.ConnectorType.End:
            connectors.append(conn)
    return connectors


def point_is_near(pt_a, pt_b, tol):
    return pt_a.DistanceTo(pt_b) <= tol


def get_pipe_curve_endpoints(pipe):
    location = pipe.Location
    if not isinstance(location, DB.LocationCurve):
        return None, None
    curve = location.Curve
    return curve.GetEndPoint(0), curve.GetEndPoint(1)


def split_result_upstream_downstream(pipe_a, pipe_b, original_start, original_end):
    a0, a1 = get_pipe_curve_endpoints(pipe_a)
    b0, b1 = get_pipe_curve_endpoints(pipe_b)

    if a0 is None or b0 is None:
        return None, None

    a_has_start = point_is_near(a0, original_start, CONNECTOR_TOLERANCE_FT) or point_is_near(a1, original_start, CONNECTOR_TOLERANCE_FT)
    b_has_start = point_is_near(b0, original_start, CONNECTOR_TOLERANCE_FT) or point_is_near(b1, original_start, CONNECTOR_TOLERANCE_FT)

    a_has_end = point_is_near(a0, original_end, CONNECTOR_TOLERANCE_FT) or point_is_near(a1, original_end, CONNECTOR_TOLERANCE_FT)
    b_has_end = point_is_near(b0, original_end, CONNECTOR_TOLERANCE_FT) or point_is_near(b1, original_end, CONNECTOR_TOLERANCE_FT)

    upstream = None
    downstream = None

    if a_has_start and not b_has_start:
        upstream = pipe_a
    elif b_has_start and not a_has_start:
        upstream = pipe_b

    if a_has_end and not b_has_end:
        downstream = pipe_a
    elif b_has_end and not a_has_end:
        downstream = pipe_b

    if upstream is None or downstream is None or upstream.Id == downstream.Id:
        len_a = get_pipe_length(pipe_a)
        len_b = get_pipe_length(pipe_b)
        if len_a <= len_b:
            upstream = pipe_a
            downstream = pipe_b
        else:
            upstream = pipe_b
            downstream = pipe_a

    return upstream, downstream


def get_closest_open_connector_pair(pipe_a, pipe_b):
    connectors_a = [c for c in get_pipe_end_connectors(pipe_a) if not c.IsConnected]
    connectors_b = [c for c in get_pipe_end_connectors(pipe_b) if not c.IsConnected]

    if not connectors_a or not connectors_b:
        return None, None

    best_pair = (None, None)
    best_dist = None

    for conn_a in connectors_a:
        for conn_b in connectors_b:
            dist = conn_a.Origin.DistanceTo(conn_b.Origin)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_pair = (conn_a, conn_b)

    if best_dist is None or best_dist > CONNECTOR_TOLERANCE_FT:
        return None, None

    return best_pair


def get_fitting_length(fitting):
    mep_model = getattr(fitting, 'MEPModel', None)
    if mep_model and mep_model.ConnectorManager:
        points = []
        for conn in mep_model.ConnectorManager.Connectors:
            points.append(conn.Origin)

        if len(points) >= 2:
            max_dist = 0.0
            for i in range(len(points)):
                for j in range(i + 1, len(points)):
                    dist = points[i].DistanceTo(points[j])
                    if dist > max_dist:
                        max_dist = dist
            if max_dist > LENGTH_TOLERANCE_FT:
                return max_dist

    length_param = fitting.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
    if length_param and length_param.HasValue:
        return length_param.AsDouble()

    for pname in ('Length', 'Overall Length', 'Nominal Length'):
        p = fitting.LookupParameter(pname)
        if p and p.HasValue:
            try:
                return p.AsDouble()
            except Exception:
                pass

    return 0.0


def place_union_between_pipes(pipe_a, pipe_b):
    conn_a, conn_b = get_closest_open_connector_pair(pipe_a, pipe_b)
    if conn_a is None or conn_b is None:
        raise Exception('Could not find matching open connectors for union placement.')

    union_fitting = doc.Create.NewUnionFitting(conn_a, conn_b)
    if union_fitting is None:
        raise Exception('NewUnionFitting returned no fitting.')

    return union_fitting


def split_pipe_and_place_unions(pipe_id, max_length_ft):
    split_count = 0
    union_count = 0
    union_lengths_used = []
    debug_records = []
    current_pipe_id = pipe_id
    carried_union_length_ft = 0.0

    for iteration in range(1, MAX_SPLITS_PER_PIPE + 1):
        current_pipe = doc.GetElement(current_pipe_id)
        if current_pipe is None:
            break

        location = current_pipe.Location
        if not isinstance(location, DB.LocationCurve):
            break

        curve = location.Curve
        original_start = curve.GetEndPoint(0)
        original_end = curve.GetEndPoint(1)
        curve_length = curve.Length

        # Keep the first segment at max length, then offset future split targets
        # by the full upstream union length on the continuing segment.
        effective_length = curve_length - carried_union_length_ft
        if effective_length <= (max_length_ft + LENGTH_TOLERANCE_FT):
            break

        split_distance = max_length_ft + carried_union_length_ft
        split_distance = min(split_distance, curve_length - LENGTH_TOLERANCE_FT)
        if split_distance <= LENGTH_TOLERANCE_FT:
            raise Exception('Computed split distance is too small for pipe Id {}.'.format(current_pipe_id.IntegerValue))

        split_point = curve.Evaluate(split_distance / curve_length, True)
        new_pipe_id = PlumbingUtils.BreakCurve(doc, current_pipe_id, split_point)

        if new_pipe_id == DB.ElementId.InvalidElementId:
            raise Exception('BreakCurve failed for pipe Id {}.'.format(current_pipe_id.IntegerValue))

        split_count += 1

        # Place the routing-preference-based union between the two new open ends.
        first_piece = doc.GetElement(current_pipe_id)
        second_piece = doc.GetElement(new_pipe_id)

        union_fitting = place_union_between_pipes(first_piece, second_piece)
        union_count += 1

        measured_union_length = get_fitting_length(union_fitting)
        union_length_for_next = measured_union_length if measured_union_length > LENGTH_TOLERANCE_FT else 0.0
        union_lengths_used.append(union_length_for_next)

        upstream_piece, downstream_piece = split_result_upstream_downstream(
            first_piece,
            second_piece,
            original_start,
            original_end,
        )

        if upstream_piece is None or downstream_piece is None:
            raise Exception('Failed to determine upstream/downstream split results for pipe Id {}.'.format(pipe_id.IntegerValue))

        first_length = get_pipe_length(first_piece) if first_piece else 0.0
        second_length = get_pipe_length(second_piece) if second_piece else 0.0
        upstream_length = get_pipe_length(upstream_piece)
        downstream_length = get_pipe_length(downstream_piece)

        current_pipe_id = downstream_piece.Id
        carried_union_length_ft = union_length_for_next
        continuing_side = 'downstream'

        debug_records.append({
            'source_pipe_id': pipe_id.IntegerValue,
            'iteration': iteration,
            'split_pipe_id': current_pipe_id.IntegerValue,
            'split_distance_ft': split_distance,
            'curve_length_before_ft': curve_length,
            'effective_length_before_ft': effective_length,
            'target_max_ft': max_length_ft,
            'first_piece_id': first_piece.Id.IntegerValue if first_piece else -1,
            'second_piece_id': second_piece.Id.IntegerValue if second_piece else -1,
            'first_piece_len_ft': first_length,
            'second_piece_len_ft': second_length,
            'upstream_piece_id': upstream_piece.Id.IntegerValue,
            'downstream_piece_id': downstream_piece.Id.IntegerValue,
            'upstream_piece_len_ft': upstream_length,
            'downstream_piece_len_ft': downstream_length,
            'union_id': union_fitting.Id.IntegerValue,
            'union_len_ft': measured_union_length,
            'carried_union_next_ft': carried_union_length_ft,
            'continuing_side': continuing_side,
            'delta_upstream_minus_target_ft': upstream_length - max_length_ft,
        })

    return split_count, union_count, union_lengths_used, debug_records


def write_debug_output(debug_records):
    if not debug_records:
        output.print_md('### Place Couplings Debug\nNo split records were captured.')
        return

    output.print_md('### Place Couplings Debug')
    output.print_md('Showing per-split length math and union measurements used for downstream offsets.')
    output.print_md('|Source Pipe|Step|Target Max|Curve Before|Effective Before|Split Distance|First Piece (Id/Len)|Second Piece (Id/Len)|Upstream (Id/Len)|Downstream (Id/Len)|Union Id|Union Len|Carry Next|Upstream-Target Delta|Continue|')
    output.print_md('|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|')

    for rec in debug_records:
        output.print_md(
            '|{source_pipe_id}|{iteration}|{target_max}|{curve_before}|{effective_before}|{split_distance}|{first_piece}|{second_piece}|{upstream_piece}|{downstream_piece}|{union_id}|{union_len}|{carry_next}|{delta}|{continuing_side}|'.format(
                source_pipe_id=rec['source_pipe_id'],
                iteration=rec['iteration'],
                target_max=fmt_ft(rec['target_max_ft']),
                curve_before=fmt_ft(rec['curve_length_before_ft']),
                effective_before=fmt_ft(rec['effective_length_before_ft']),
                split_distance=fmt_ft(rec['split_distance_ft']),
                first_piece='{} / {}'.format(rec['first_piece_id'], fmt_ft(rec['first_piece_len_ft'])),
                second_piece='{} / {}'.format(rec['second_piece_id'], fmt_ft(rec['second_piece_len_ft'])),
                upstream_piece='{} / {}'.format(rec['upstream_piece_id'], fmt_ft(rec['upstream_piece_len_ft'])),
                downstream_piece='{} / {}'.format(rec['downstream_piece_id'], fmt_ft(rec['downstream_piece_len_ft'])),
                union_id=rec['union_id'],
                union_len='{} ({})'.format(fmt_ft(rec['union_len_ft']), fmt_in(rec['union_len_ft'])),
                carry_next='{} ({})'.format(fmt_ft(rec['carried_union_next_ft']), fmt_in(rec['carried_union_next_ft'])),
                delta='{} ({})'.format(fmt_ft(rec['delta_upstream_minus_target_ft']), fmt_in(rec['delta_upstream_minus_target_ft'])),
                continuing_side=rec['continuing_side'],
            )
        )


def main():
    if not MAX_LENGTH_BY_TYPE_NAME:
        forms.alert('No pipe type max-length rules are configured.', exitscript=True)

    normalized_rules = {
        normalize_name(type_name): max_len
        for type_name, max_len in MAX_LENGTH_BY_TYPE_NAME.items()
        if type_name and max_len and max_len > 0
    }

    if not normalized_rules:
        forms.alert('Configured rules are invalid. Add at least one positive max length.', exitscript=True)

    visible_pipes = DB.FilteredElementCollector(doc, active_view.Id) \
        .OfClass(Pipe) \
        .WhereElementIsNotElementType() \
        .ToElements()

    visible_pipe_count = len(visible_pipes)
    if visible_pipe_count == 0:
        forms.alert('No pipes were found in the active view.', exitscript=True)

    selected_ids = set(revit.uidoc.Selection.GetElementIds())
    selected_pipes = [pipe for pipe in visible_pipes if pipe.Id in selected_ids]

    if selected_pipes:
        pipes = selected_pipes
    else:
        process_all = forms.alert(
            'No pipes selected. Split all visible pipes?',
            yes=True,
            no=True,
            exitscript=False,
        )
        if process_all:
            pipes = visible_pipes
        else:
            forms.alert('No pipes selected. Script cancelled.', exitscript=True)

    targets = []
    matched_count = 0

    for pipe in pipes:
        max_length_ft = get_max_length_for_pipe(pipe, normalized_rules)
        if max_length_ft is None:
            continue

        matched_count += 1
        pipe_length = get_pipe_length(pipe)
        if pipe_length > (max_length_ft + LENGTH_TOLERANCE_FT):
            targets.append((pipe.Id, max_length_ft))

    if not targets:
        forms.alert(
            'Found {} matching pipe(s) in the active view. None exceed configured max lengths.'.format(matched_count),
            title='Place Couplings',
        )
        return

    split_total = 0
    union_total = 0
    all_union_lengths_used = []
    debug_records = []
    failures = []

    with revit.Transaction('Place Couplings (Split Pipes + Unions)'):
        for pipe_id, max_length_ft in targets:
            try:
                pipe_splits, pipe_unions, pipe_union_lengths, pipe_debug_records = split_pipe_and_place_unions(pipe_id, max_length_ft)
                split_total += pipe_splits
                union_total += pipe_unions
                all_union_lengths_used.extend(pipe_union_lengths)
                debug_records.extend(pipe_debug_records)
            except Exception as ex:
                failures.append('Pipe Id {}: {}'.format(pipe_id.IntegerValue, ex))

    message = [
        'Matching pipes in active view: {}'.format(matched_count),
        'Pipes requiring splits: {}'.format(len(targets)),
        'Total splits created: {}'.format(split_total),
        'Total unions placed: {}'.format(union_total),
    ]

    if failures:
        message.append('\nFailed to split {} pipe(s):'.format(len(failures)))
        message.extend(failures[:10])
        if len(failures) > 10:
            message.append('...and {} more'.format(len(failures) - 10))

    if all_union_lengths_used:
        avg_all = sum(all_union_lengths_used) / float(len(all_union_lengths_used))
        message.append('\nDebug: measured union lengths (all)')
        message.append(
            'count={}, min={:.4f} ft, avg={:.4f} ft, max={:.4f} ft'.format(
                len(all_union_lengths_used),
                min(all_union_lengths_used),
                avg_all,
                max(all_union_lengths_used),
            )
        )

        preview_count = min(20, len(all_union_lengths_used))
        preview = ', '.join('{:.4f}'.format(v) for v in all_union_lengths_used[:preview_count])
        message.append('first {} value(s): {}'.format(preview_count, preview))
        if len(all_union_lengths_used) > preview_count:
            message.append('...and {} more'.format(len(all_union_lengths_used) - preview_count))

    write_debug_output(debug_records)

    forms.alert('\n'.join(message), title='Place Couplings')


if __name__ == '__main__':
    main()
