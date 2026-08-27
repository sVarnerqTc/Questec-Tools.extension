# -*- coding: utf-8 -*-
import re
from math import pi

import clr

clr.AddReference('RevitAPI')

from Autodesk.Revit import Exceptions
from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ConnectorType,
    ElementId,
    ElementTransformUtils,
    FamilyInstance,
    FilteredElementCollector,
    Line,
    XYZ,
)
from Autodesk.Revit.DB.Plumbing import Pipe
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from pyrevit import forms, revit, script


doc = revit.doc
uidoc = revit.uidoc
logger = script.get_logger()


class PipeSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        return isinstance(elem, Pipe)

    def AllowReference(self, reference, position):
        return True


class PipeFittingSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if elem is None:
            return False
        if elem.Category is None:
            return False
        return elem.Category.Id.IntegerValue == int(BuiltInCategory.OST_PipeFitting)

    def AllowReference(self, reference, position):
        return True


class NippleChoice(forms.TemplateListItem):
    @property
    def name(self):
        return self.item['display']


def get_choice_data(choice):
    if choice is None:
        return None

    if isinstance(choice, dict):
        return choice

    item = getattr(choice, 'item', None)
    if isinstance(item, dict):
        return item

    raise Exception('Unexpected nipple selection type: {}'.format(type(choice)))


def get_connectors(elem):
    if isinstance(elem, Pipe):
        return list(elem.ConnectorManager.Connectors)

    mep_model = getattr(elem, 'MEPModel', None)
    if mep_model and mep_model.ConnectorManager:
        return list(mep_model.ConnectorManager.Connectors)

    connector_manager = getattr(elem, 'ConnectorManager', None)
    if connector_manager:
        return list(connector_manager.Connectors)

    return []


def get_end_connectors(elem):
    return [c for c in get_connectors(elem) if c.ConnectorType == ConnectorType.End]


def get_other_owner_connector(connector):
    for ref in connector.AllRefs:
        if ref.Owner.Id != connector.Owner.Id:
            return ref
    return None


def get_connected_pipe_ids(fitting):
    pipe_ids = set()
    for conn in get_connectors(fitting):
        for ref in conn.AllRefs:
            owner = ref.Owner
            if owner.Id == fitting.Id:
                continue
            if isinstance(owner, Pipe):
                pipe_ids.add(owner.Id.IntegerValue)
    return pipe_ids


def get_connected_connector_count(fitting):
    connected_count = 0
    for conn in get_connectors(fitting):
        for ref in conn.AllRefs:
            if ref.Owner.Id != fitting.Id:
                connected_count += 1
                break
    return connected_count


def get_pipe_connection_direction_at_fitting(pipe, fitting_id):
    pipe_end_connectors = get_end_connectors(pipe)
    if len(pipe_end_connectors) < 2:
        return None, None

    connector_at_fitting = None
    other_connector = None

    for conn in pipe_end_connectors:
        is_connected_to_fitting = False
        for ref in conn.AllRefs:
            if ref.Owner.Id.IntegerValue == fitting_id:
                is_connected_to_fitting = True
                break

        if is_connected_to_fitting:
            connector_at_fitting = conn
        else:
            other_connector = conn

    if connector_at_fitting is None or other_connector is None:
        return None, None

    direction = other_connector.Origin - connector_at_fitting.Origin
    if direction.GetLength() < 1e-6:
        return None, None

    return connector_at_fitting.Origin, direction.Normalize()


def pipes_on_same_axis_at_fitting(pipe_a, pipe_b, fitting_id):
    origin_a, dir_a = get_pipe_connection_direction_at_fitting(pipe_a, fitting_id)
    origin_b, dir_b = get_pipe_connection_direction_at_fitting(pipe_b, fitting_id)
    if origin_a is None or origin_b is None or dir_a is None or dir_b is None:
        return False

    if dir_a.CrossProduct(dir_b).GetLength() > 1e-3:
        return False

    offset = origin_b - origin_a
    if offset.CrossProduct(dir_a).GetLength() > 1e-4:
        return False

    return True


def get_fitting_connector_connected_to_pipe(fitting, pipe_id):
    for conn in get_connectors(fitting):
        for ref in conn.AllRefs:
            if ref.Owner.Id.IntegerValue == pipe_id:
                return conn
    return None


def parse_length_inches(family_name):
    match = re.search(r'(\d+_5|\d+(?:\.\d+)?)', family_name or '')
    if not match:
        return None

    token = match.group(1)
    if token.endswith('_5'):
        whole = token.split('_5')[0]
        try:
            return float(whole) + 0.5
        except Exception:
            return None

    try:
        return float(token)
    except Exception:
        return None


def get_family_name_from_symbol(symbol):
    if symbol is None:
        return ''

    family = getattr(symbol, 'Family', None)
    if family is not None and family.Name:
        return family.Name

    family_name = getattr(symbol, 'FamilyName', None)
    if family_name:
        return family_name

    return ''


def get_nipple_choices():
    fittings = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_PipeFitting)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    sample_by_type = {}
    count_by_type = {}
    for fitting in fittings:
        if not isinstance(fitting, FamilyInstance):
            continue
        type_id = fitting.GetTypeId().IntegerValue
        count_by_type[type_id] = count_by_type.get(type_id, 0) + 1
        if type_id not in sample_by_type:
            sample_by_type[type_id] = fitting.Id

    fitting_types = (
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_PipeFitting)
        .WhereElementIsElementType()
        .ToElements()
    )

    by_symbol = {}
    for symbol in fitting_types:
        family_name = get_family_name_from_symbol(symbol)
        if 'nipple' not in (family_name or '').lower():
            continue

        length_in = parse_length_inches(family_name)
        if length_in is None:
            continue

        symbol_id = symbol.Id.IntegerValue
        if symbol_id in by_symbol:
            continue

        placed_count = count_by_type.get(symbol_id, 0)
        placement_label = 'placed: {}'.format(placed_count) if placed_count > 0 else 'unplaced'

        by_symbol[symbol_id] = {
            'display': '{} | length: {} in | {}'.format(
                family_name,
                length_in,
                placement_label,
            ),
            'symbol_id': symbol.Id,
            'sample_instance_id': sample_by_type.get(symbol_id),
            'family_name': family_name,
            'length_in': length_in,
            'placed_count': placed_count,
        }

    choices = [NippleChoice(v) for v in by_symbol.values()]
    choices.sort(key=lambda c: (c.item['family_name'].lower(), c.item['length_in'], c.item['placed_count']))
    return choices


def get_pipe_diameter(pipe):
    param = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
    if param and param.HasValue:
        return param.AsDouble()

    param = pipe.LookupParameter('Diameter')
    if param and param.HasValue:
        return param.AsDouble()

    return None


def get_farthest_connector_pair(connectors):
    if len(connectors) < 2:
        return None, None

    best_a = None
    best_b = None
    best_distance = -1.0
    for idx, conn_a in enumerate(connectors):
        for conn_b in connectors[idx + 1 :]:
            dist = conn_a.Origin.DistanceTo(conn_b.Origin)
            if dist > best_distance:
                best_distance = dist
                best_a = conn_a
                best_b = conn_b

    return best_a, best_b


def get_connector_near_point(elem, point, only_open=False):
    nearest = None
    nearest_distance = None
    for conn in get_connectors(elem):
        if only_open and conn.IsConnected:
            continue
        dist = conn.Origin.DistanceTo(point)
        if nearest is None or dist < nearest_distance:
            nearest = conn
            nearest_distance = dist
    return nearest


def get_connector_by_owner_and_point(owner_id, point):
    owner = doc.GetElement(owner_id)
    if owner is None:
        return None
    return get_connector_near_point(owner, point, only_open=False)


def connect_if_needed(conn_a, conn_b):
    if conn_a is None or conn_b is None:
        return

    for ref in conn_a.AllRefs:
        if ref.Owner.Id == conn_b.Owner.Id and ref.Origin.DistanceTo(conn_b.Origin) < 1e-6:
            return

    conn_a.ConnectTo(conn_b)


def align_connector_to_target(element, source_connector, target_connector):
    source_direction = source_connector.CoordinateSystem.BasisZ
    target_direction = target_connector.CoordinateSystem.BasisZ
    angle = source_direction.AngleTo(target_direction)

    if abs(angle - pi) > 1e-6:
        if abs(angle) < 1e-6:
            vector = source_connector.CoordinateSystem.BasisY
        else:
            vector = source_direction.CrossProduct(target_direction)

        try:
            line = Line.CreateBound(source_connector.Origin, source_connector.Origin + vector)
            element.Location.Rotate(line, angle - pi)
        except Exceptions.ArgumentsInconsistentException:
            logger.debug('Rotate skipped. Vector: {} Angle: {}'.format(vector, angle))


def place_and_orient_nipple(nipple, start_point, end_point):
    conn_a, conn_b = get_farthest_connector_pair(get_connectors(nipple))
    if conn_a is None or conn_b is None:
        raise Exception('Nipple fitting must have at least 2 connectors.')

    current_axis = conn_b.Origin - conn_a.Origin
    desired_axis = end_point - start_point

    if current_axis.GetLength() < 1e-6 or desired_axis.GetLength() < 1e-6:
        raise Exception('Could not determine orientation axis for nipple placement.')

    current_axis = current_axis.Normalize()
    desired_axis = desired_axis.Normalize()

    angle = current_axis.AngleTo(desired_axis)
    if angle > 1e-6:
        rot_axis = current_axis.CrossProduct(desired_axis)
        if rot_axis.GetLength() < 1e-6:
            rot_axis = conn_a.CoordinateSystem.BasisY

        line = Line.CreateBound(conn_a.Origin, conn_a.Origin + rot_axis)
        nipple.Location.Rotate(line, angle)

    conn_a = get_connector_near_point(nipple, conn_a.Origin)
    conn_b = get_connector_near_point(nipple, conn_b.Origin)

    if conn_a.Origin.DistanceTo(start_point) > conn_b.Origin.DistanceTo(start_point):
        conn_a, conn_b = conn_b, conn_a

    move_vec = start_point - conn_a.Origin
    nipple.Location.Move(move_vec)

    placed_start = get_connector_near_point(nipple, start_point)
    placed_end = None
    for conn in get_connectors(nipple):
        if conn.Origin.DistanceTo(placed_start.Origin) > 1e-6:
            placed_end = conn
            break

    if placed_end is None:
        raise Exception('Could not find second nipple connector after placement.')

    return placed_start, placed_end


def create_nipple_instance(nipple_choice, insertion_point):
    choice_data = get_choice_data(nipple_choice)
    symbol = doc.GetElement(choice_data['symbol_id'])
    if symbol is None:
        raise Exception('Selected nipple symbol could not be found.')

    sample_instance_id = choice_data.get('sample_instance_id')
    if sample_instance_id is not None:
        sample_instance = doc.GetElement(sample_instance_id)
        if sample_instance is not None:
            copied_ids = ElementTransformUtils.CopyElement(doc, sample_instance.Id, XYZ(0, 0, 0))
            if copied_ids is None or copied_ids.Count == 0:
                raise Exception('Failed to copy selected nipple fitting.')

            nipple_instance = doc.GetElement(copied_ids[0])
            nipple_instance.ChangeTypeId(symbol.Id)
            return nipple_instance

    try:
        if hasattr(symbol, 'IsActive') and (not symbol.IsActive):
            symbol.Activate()
            doc.Regenerate()

        return doc.Create.NewFamilyInstance(insertion_point, symbol, StructuralType.NonStructural)
    except Exception as exc:
        raise Exception(
            'Selected nipple type has no placed instance and could not be created automatically. '
            'Place one instance and retry. Details: {}'.format(exc)
        )


def main():
    try:
        with forms.WarningBar(title='Select pipe to replace with nipple'):
            pipe_ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                PipeSelectionFilter(),
                'Select pipe to replace',
            )
    except Exceptions.OperationCanceledException:
        return

    pipe_to_replace = doc.GetElement(pipe_ref.ElementId)

    try:
        with forms.WarningBar(title='Select fitting to move'):
            fitting_ref = uidoc.Selection.PickObject(
                ObjectType.Element,
                PipeFittingSelectionFilter(),
                'Select fitting to move',
            )
    except Exceptions.OperationCanceledException:
        return

    fitting_to_move = doc.GetElement(fitting_ref.ElementId)
    connected_pipe_ids = get_connected_pipe_ids(fitting_to_move)
    if len(connected_pipe_ids) < 2:
        forms.alert(
            'Selected fitting must be connected to at least 2 pipes.\nFound {}.'.format(len(connected_pipe_ids)),
            title='Selection Error',
        )
        return

    if pipe_to_replace.Id.IntegerValue not in connected_pipe_ids:
        forms.alert(
            'Selected fitting is not connected to the selected pipe.',
            title='Selection Error',
        )
        return

    nipple_choices = get_nipple_choices()
    if not nipple_choices:
        forms.alert(
            'No nipple fittings were found with a parseable length in the family name.',
            title='Nipple Not Found',
        )
        return

    nipple_choices = sorted(
        nipple_choices,
        key=lambda c: (c.item['family_name'].lower(), c.item['length_in'], c.item['placed_count']),
    )

    nipple_choice = forms.SelectFromList.show(
        nipple_choices,
        title='Select Nipple Type',
        button_name='Use Selected Nipple',
        multiselect=False,
    )
    if not nipple_choice:
        return

    fitting_pipe_connector = get_fitting_connector_connected_to_pipe(
        fitting_to_move,
        pipe_to_replace.Id.IntegerValue,
    )
    if fitting_pipe_connector is None:
        forms.alert('Failed to locate fitting connector connected to selected pipe.', title='Connection Error')
        return

    pipe_end_connectors = get_end_connectors(pipe_to_replace)
    if len(pipe_end_connectors) != 2:
        forms.alert('Selected pipe must have exactly 2 end connectors.', title='Pipe Error')
        return

    pipe_connector_at_fitting = None
    for conn in pipe_end_connectors:
        for ref in conn.AllRefs:
            if ref.Owner.Id == fitting_to_move.Id:
                pipe_connector_at_fitting = conn
                break
        if pipe_connector_at_fitting:
            break

    if pipe_connector_at_fitting is None:
        forms.alert('Selected pipe is not directly connected to selected fitting.', title='Connection Error')
        return

    remote_pipe_connector = None
    for conn in pipe_end_connectors:
        if conn.Origin.DistanceTo(pipe_connector_at_fitting.Origin) > 1e-6:
            remote_pipe_connector = conn
            break

    if remote_pipe_connector is None:
        forms.alert('Could not determine remote end of selected pipe.', title='Pipe Error')
        return

    remote_other_connector = get_other_owner_connector(remote_pipe_connector)
    if remote_other_connector is None:
        forms.alert(
            'The selected pipe remote end is not connected. A connected endpoint is required.',
            title='Connection Error',
        )
        return

    pipe_diameter = get_pipe_diameter(pipe_to_replace)
    if pipe_diameter is None or pipe_diameter <= 0:
        forms.alert('Could not read Diameter from selected pipe.', title='Parameter Error')
        return

    target_radius = pipe_diameter / 2.0

    connected_connector_count = get_connected_connector_count(fitting_to_move)
    should_move_fitting = True
    move_skip_reason = None

    if connected_connector_count > 2:
        should_move_fitting = False
        move_skip_reason = 'Fitting was not moved because it has more than 2 connections (example: tee).'
    elif len(connected_pipe_ids) == 2:
        connected_pipe_elems = [doc.GetElement(ElementId(pid)) for pid in connected_pipe_ids]
        connected_pipe_elems = [p for p in connected_pipe_elems if p is not None and isinstance(p, Pipe)]
        if len(connected_pipe_elems) == 2:
            if not pipes_on_same_axis_at_fitting(
                connected_pipe_elems[0],
                connected_pipe_elems[1],
                fitting_to_move.Id.IntegerValue,
            ):
                should_move_fitting = False
                move_skip_reason = 'Fitting was not moved because the two connected pipes are not on the same axis.'

    fitting_open_point = fitting_pipe_connector.Origin
    fixed_start_point = remote_pipe_connector.Origin
    fixed_end_direction_point = pipe_connector_at_fitting.Origin
    remote_owner_id = remote_other_connector.Owner.Id
    remote_owner_point = remote_other_connector.Origin

    with revit.Transaction('Change Pipe To Nipple'):
        nipple_instance = create_nipple_instance(nipple_choice, fixed_start_point)

        for pname in ('Nom Radius1', 'Nom Radius2'):
            p = nipple_instance.LookupParameter(pname)
            if p and (not p.IsReadOnly):
                p.Set(target_radius)

        # Delete original pipe before reconnecting so the fitting has an open connector.
        doc.Delete(pipe_to_replace.Id)

        updated_remote_connector = get_connector_by_owner_and_point(remote_owner_id, remote_owner_point)
        if updated_remote_connector is None:
            raise Exception('Could not find connector at fixed end after deleting pipe.')

        start_connector, end_connector = place_and_orient_nipple(
            nipple_instance,
            fixed_start_point,
            fixed_end_direction_point,
        )

        connect_if_needed(start_connector, updated_remote_connector)

        fitting_after_delete = doc.GetElement(fitting_to_move.Id)
        if fitting_after_delete is None:
            raise Exception('Selected fitting was deleted during operation.')

        fitting_open_connector = get_connector_near_point(
            fitting_after_delete,
            fitting_open_point,
            only_open=True,
        )
        if fitting_open_connector is None:
            fitting_open_connector = get_connector_near_point(
                fitting_after_delete,
                end_connector.Origin,
                only_open=True,
            )
        if fitting_open_connector is None:
            raise Exception('Could not find open connector on selected fitting after deletion.')

        if should_move_fitting:
            align_connector_to_target(fitting_after_delete, fitting_open_connector, end_connector)

            fitting_open_connector = get_connector_near_point(
                fitting_after_delete,
                fitting_open_point,
                only_open=True,
            )
            if fitting_open_connector is None:
                fitting_open_connector = get_connector_near_point(
                    fitting_after_delete,
                    end_connector.Origin,
                    only_open=True,
                )

            if fitting_open_connector is None:
                raise Exception('Failed to resolve open fitting connector for reconnection.')

            move_vec = end_connector.Origin - fitting_open_connector.Origin
            fitting_after_delete.Location.Move(move_vec)

            fitting_open_connector = get_connector_near_point(
                fitting_after_delete,
                end_connector.Origin,
                only_open=True,
            )
            if fitting_open_connector is None:
                raise Exception('Open connector not found at nipple end after moving fitting.')

            connect_if_needed(fitting_open_connector, end_connector)
        elif fitting_open_connector.Origin.DistanceTo(end_connector.Origin) < 1e-4:
            connect_if_needed(fitting_open_connector, end_connector)

    if move_skip_reason:
        forms.alert(
            'Pipe replaced with selected nipple successfully.\n\n{}'.format(move_skip_reason),
            title='Change to Nipple',
        )
    else:
        forms.alert('Pipe replaced with selected nipple successfully.', title='Change to Nipple')


if __name__ == '__main__':
    try:
        main()
    except Exceptions.OperationCanceledException:
        pass
    except Exception as exc:
        forms.alert(str(exc), title='Change to Nipple Error')
