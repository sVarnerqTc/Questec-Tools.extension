import os
import csv

from pyrevit import forms
from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    GlobalParameter,
    StorageType,
    Transaction,
)
from Autodesk.Revit.DB.Plumbing import PipeInsulation, PipeInsulationType

INSULATION_SCHEDULE_PARAM_NAME = "Insulation Schedule Path"


def find_global_parameter(doc, parameter_name):
    global_parameters = FilteredElementCollector(doc).OfClass(GlobalParameter).ToElements()
    for gp in global_parameters:
        if gp.Name == parameter_name:
            return gp
    return None


def get_global_parameter_value(doc, parameter_name):
    gp = find_global_parameter(doc, parameter_name)
    if not gp:
        return None

    try:
        gp_value = gp.GetValue()
        if gp_value:
            return gp_value.Value
    except Exception:
        return None

    return None


def parse_inches(value):
    text = (value or '').strip()
    if not text:
        return 0.0

    cleaned = text.lower().replace('in.', '').replace('in', '').replace('"', '').strip()
    if not cleaned:
        return 0.0

    try:
        return float(cleaned)
    except Exception:
        pass

    try:
        if ' ' in cleaned:
            whole, fraction = cleaned.split(' ', 1)
            if '/' in fraction:
                num, den = fraction.split('/', 1)
                return float(whole) + (float(num) / float(den))
        elif '/' in cleaned:
            num, den = cleaned.split('/', 1)
            return float(num) / float(den)
    except Exception:
        return 0.0

    return 0.0


def inches_to_feet(value):
    return parse_inches(value) / 12.0


def read_insulation_schedule(csv_path):
    schedule = {}

    with open(csv_path, 'rb') as csv_file:
        reader = csv.reader(csv_file)
        next(reader, None)  # Skip header row

        for row in reader:
            if len(row) < 6:
                continue

            system_abbrev = (row[0] or '').strip()
            if not system_abbrev:
                continue

            schedule[system_abbrev] = {
                'ins1': inches_to_feet(row[1]),
                'break1': inches_to_feet(row[2]),
                'ins2': inches_to_feet(row[3]),
                'break2': inches_to_feet(row[4]),
                'ins3': inches_to_feet(row[5]),
            }

    return schedule


def get_system_abbreviation(element):
    try:
        param = element.get_Parameter(BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM)
        if param and param.HasValue:
            value = param.AsString() or param.AsValueString()
            if value and value.strip():
                return value.strip()
    except Exception:
        pass

    for pname in ['System Abbreviation', 'Abbreviation']:
        try:
            param = element.LookupParameter(pname)
            if param and param.HasValue:
                value = param.AsString() or param.AsValueString()
                if value and value.strip():
                    return value.strip()
        except Exception:
            continue

    return None


def _read_double_parameter(param):
    if not param or not param.HasValue:
        return None

    try:
        if param.StorageType == StorageType.Double:
            return param.AsDouble()

        value_string = param.AsValueString() or param.AsString()
        if value_string:
            return inches_to_feet(value_string)
    except Exception:
        return None

    return None


def get_pipe_size_feet(pipe):
    try:
        bip_param = pipe.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
        size = _read_double_parameter(bip_param)
        if size is not None:
            return size
    except Exception:
        pass

    for pname in ['Diameter', 'Size', 'Nominal Diameter']:
        size = _read_double_parameter(pipe.LookupParameter(pname))
        if size is not None:
            return size

    return None


def get_fitting_size_feet(fitting):
    for pname in ['Diameter1', 'Diameter', 'Size', 'Nominal Diameter']:
        size = _read_double_parameter(fitting.LookupParameter(pname))
        if size is not None:
            return size

    return None


def get_target_insulation(rule, size_feet):
    break1 = rule['break1']
    break2 = rule['break2']

    if break1 <= 0 or size_feet < break1:
        return rule['ins1']

    if break2 <= 0 or size_feet < break2:
        return rule['ins2']

    return rule['ins3']


def collect_active_view_targets(doc, view_id):
    pipes = list(
        FilteredElementCollector(doc, view_id)
        .OfCategory(BuiltInCategory.OST_PipeCurves)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    fittings = list(
        FilteredElementCollector(doc, view_id)
        .OfCategory(BuiltInCategory.OST_PipeFitting)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    return pipes, fittings


def get_default_pipe_insulation_type_id(doc):
    type_id = (
        FilteredElementCollector(doc)
        .OfClass(PipeInsulationType)
        .WhereElementIsElementType()
        .FirstElementId()
    )

    if type_id == ElementId.InvalidElementId:
        return None

    return type_id


def collect_existing_pipe_insulation(doc):
    existing = {}

    for insulation in FilteredElementCollector(doc).OfClass(PipeInsulation).WhereElementIsNotElementType().ToElements():
        try:
            host_id = insulation.HostElementId
            if host_id and host_id != ElementId.InvalidElementId:
                existing[host_id.IntegerValue] = insulation
        except Exception:
            continue

    return existing


def get_host_workset_id(element):
    try:
        workset_id = element.WorksetId
        if workset_id and workset_id != ElementId.InvalidElementId:
            return workset_id
    except Exception:
        pass

    return None


def resolve_element(doc, element_or_id):
    if element_or_id is None:
        return None

    if isinstance(element_or_id, ElementId):
        return doc.GetElement(element_or_id)

    try:
        return doc.GetElement(ElementId(int(element_or_id)))
    except Exception:
        return element_or_id


def get_element_workset_value(element):
    if not element:
        return None

    try:
        partition_param = element.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if partition_param and partition_param.HasValue:
            return partition_param.AsInteger()
    except Exception:
        pass

    try:
        workset_id = element.WorksetId
        if workset_id:
            return workset_id.IntegerValue
    except Exception:
        pass

    return None


def create_insulation_on_workset(doc, workset_table, host_element_id, insulation_type_id, thickness_feet, target_workset_id):
    original_workset_id = None

    try:
        original_workset_id = workset_table.GetActiveWorksetId()
    except Exception:
        original_workset_id = None

    try:
        if target_workset_id and original_workset_id != target_workset_id:
            workset_table.SetActiveWorksetId(target_workset_id)

        created = PipeInsulation.Create(doc, host_element_id, insulation_type_id, thickness_feet)
        return resolve_element(doc, created)
    finally:
        try:
            if original_workset_id and original_workset_id != workset_table.GetActiveWorksetId():
                workset_table.SetActiveWorksetId(original_workset_id)
        except Exception:
            pass


def ensure_insulation_on_host_workset(doc, workset_table, host_element, existing_insulation, insulation_type_id, thickness_feet):
    host_workset_id = get_host_workset_id(host_element)
    host_workset_value = get_element_workset_value(host_element)

    if existing_insulation:
        existing_workset_value = get_element_workset_value(existing_insulation)
        existing_insulation.Thickness = thickness_feet

        if host_workset_value is None or existing_workset_value == host_workset_value:
            return existing_insulation, True, False

        doc.Delete(existing_insulation.Id)
        recreated = create_insulation_on_workset(
            doc,
            workset_table,
            host_element.Id,
            insulation_type_id,
            thickness_feet,
            host_workset_id,
        )
        return recreated, recreated is not None, True

    created = create_insulation_on_workset(
        doc,
        workset_table,
        host_element.Id,
        insulation_type_id,
        thickness_feet,
        host_workset_id,
    )
    return created, created is not None, False


def run_insulation(doc, view_id, schedule):
    insulation_type_id = get_default_pipe_insulation_type_id(doc)
    if not insulation_type_id:
        forms.alert('No Pipe Insulation Type found in this project.', exitscript=True)
        return

    workset_table = doc.GetWorksetTable()
    pipes, fittings = collect_active_view_targets(doc, view_id)
    existing_by_host = collect_existing_pipe_insulation(doc)

    total_targets = len(pipes) + len(fittings)
    matched_schedule = 0
    insulated_created = 0
    insulated_updated = 0
    skipped_no_schedule = 0
    skipped_no_size = 0
    skipped_zero_thickness = 0
    workset_assigned = 0
    workset_recreated = 0
    workset_failed = 0
    failed = 0

    with Transaction(doc, 'Insulate Pipes and Fittings from Schedule') as tx:
        tx.Start()

        for pipe in pipes:
            system_abbrev = get_system_abbreviation(pipe)
            rule = schedule.get(system_abbrev)
            if not rule:
                skipped_no_schedule += 1
                continue

            size_feet = get_pipe_size_feet(pipe)
            if size_feet is None:
                skipped_no_size += 1
                continue

            matched_schedule += 1
            thickness_feet = get_target_insulation(rule, size_feet)
            if thickness_feet <= 0:
                skipped_zero_thickness += 1
                continue

            existing = existing_by_host.get(pipe.Id.IntegerValue)
            try:
                insulation, success, recreated = ensure_insulation_on_host_workset(
                    doc,
                    workset_table,
                    pipe,
                    existing,
                    insulation_type_id,
                    thickness_feet,
                )

                if success and insulation:
                    if get_element_workset_value(insulation) == get_element_workset_value(pipe):
                        workset_assigned += 1
                    else:
                        workset_failed += 1
                        failed += 1

                    if recreated:
                        workset_recreated += 1

                else:
                    workset_failed += 1
                    failed += 1

                if existing and not recreated:
                    insulated_updated += 1
                else:
                    insulated_created += 1
            except Exception:
                failed += 1

        for fitting in fittings:
            system_abbrev = get_system_abbreviation(fitting)
            rule = schedule.get(system_abbrev)
            if not rule:
                skipped_no_schedule += 1
                continue

            size_feet = get_fitting_size_feet(fitting)
            if size_feet is None:
                skipped_no_size += 1
                continue

            matched_schedule += 1
            thickness_feet = get_target_insulation(rule, size_feet)
            if thickness_feet <= 0:
                skipped_zero_thickness += 1
                continue

            existing = existing_by_host.get(fitting.Id.IntegerValue)
            try:
                insulation, success, recreated = ensure_insulation_on_host_workset(
                    doc,
                    workset_table,
                    fitting,
                    existing,
                    insulation_type_id,
                    thickness_feet,
                )

                if success and insulation:
                    if get_element_workset_value(insulation) == get_element_workset_value(fitting):
                        workset_assigned += 1
                    else:
                        workset_failed += 1
                        failed += 1

                    if recreated:
                        workset_recreated += 1

                else:
                    workset_failed += 1
                    failed += 1

                if existing and not recreated:
                    insulated_updated += 1
                else:
                    insulated_created += 1
            except Exception:
                failed += 1

        tx.Commit()

    # Keep successful runs quiet; only report details when errors occur.
    if failed > 0:
        print('Insulation run completed with errors in active view:')
        print('  Targets in active view: {0}'.format(total_targets))
        print('  Matched schedule rows: {0}'.format(matched_schedule))
        print('  Insulation created: {0}'.format(insulated_created))
        print('  Insulation updated: {0}'.format(insulated_updated))
        print('  Workset assignments applied: {0}'.format(workset_assigned))
        print('  Insulation recreated for workset: {0}'.format(workset_recreated))
        print('  Workset assignments failed: {0}'.format(workset_failed))
        print('  Skipped (no schedule match): {0}'.format(skipped_no_schedule))
        print('  Skipped (size not found): {0}'.format(skipped_no_size))
        print('  Skipped (target thickness is 0): {0}'.format(skipped_zero_thickness))
        print('  Failed: {0}'.format(failed))


def main():
    doc = __revit__.ActiveUIDocument.Document
    view = doc.ActiveView

    csv_path = get_global_parameter_value(doc, INSULATION_SCHEDULE_PARAM_NAME)
    if not csv_path or not os.path.exists(csv_path):
        forms.alert(
            'Insulation schedule path is not set or file does not exist.\n\n'
            'Use Shift+Click on this button to set the CSV path.',
            exitscript=True,
        )
        return

    try:
        schedule = read_insulation_schedule(csv_path)
    except Exception as ex:
        forms.alert('Failed reading CSV: {0}'.format(str(ex)), exitscript=True)
        return

    if not schedule:
        forms.alert('The insulation schedule CSV has no usable rows.', exitscript=True)
        return

    run_insulation(doc, view.Id, schedule)


main()
