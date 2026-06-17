import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import revit, DB, forms
from System.Collections.Generic import List
import math

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
active_view = doc.ActiveView

def get_qtc_error_parameter(element, require_writable):
    matching = list(element.GetParameters('QTC Error'))
    if len(matching) == 0:
        return None, 'QTC Error not found on element'

    string_params = [p for p in matching if p.StorageType == StorageType.String]
    if len(string_params) == 0:
        return None, 'QTC Error exists but is not a text parameter'

    if not require_writable:
        return string_params[0], None

    writable = [p for p in string_params if not p.IsReadOnly]
    if len(writable) == 0:
        return None, 'QTC Error text parameter is read-only on this element'

    return writable[0], None

# Lists to store results
hangers_with_pipes = []  # Successful matches
hangers_no_pipes = []    # Hangers with no pipes nearby
hangers_multiple_systems = []  # Hangers with conflicting pipes
error_hanger_ids = set()
error_pipe_ids = set()

def track_error_elements(hanger, related_pipes=None):
    error_hanger_ids.add(hanger.Id.IntegerValue)
    if related_pipes:
        for pipe in related_pipes:
            error_pipe_ids.add(pipe.Id.IntegerValue)

# Get all pipes and pipe accessories in active view
collector_pipes = FilteredElementCollector(doc, active_view.Id)\
    .OfCategory(BuiltInCategory.OST_PipeCurves)\
    .WhereElementIsNotElementType()\
    .ToElements()

# Add this after the pipe collector
print("Number of pipes found: {}".format(len(list(collector_pipes))))

collector_accessories = FilteredElementCollector(doc, active_view.Id)\
    .OfCategory(BuiltInCategory.OST_PipeAccessory)\
    .WhereElementIsNotElementType()\
    .ToElements()

# Filter accessories to only those with BOP parameter
visible_hangers = []
for acc in collector_accessories:
    if acc.LookupParameter('BOP'):
        visible_hangers.append(acc)

visible_hanger_count = len(visible_hangers)
if visible_hanger_count == 0:
    forms.alert('No hangers were found in the active view.', exitscript=True)

selected_ids = set(uidoc.Selection.GetElementIds())
hangers = [hanger for hanger in visible_hangers if hanger.Id in selected_ids]

if len(hangers) == 0:
    process_all = forms.alert(
        'No hangers are selected.\n\nDo you want to process all {} hangers in the active view?'.format(visible_hanger_count),
        yes=True,
        no=True,
        exitscript=False
    )
    if process_all:
        hangers = visible_hangers
    else:
        forms.alert('No hangers selected. Script cancelled.', exitscript=True)

# Function to check if point is within sphere
def is_point_in_sphere(point_to_check, sphere_center, radius):
    distance = point_to_check.DistanceTo(sphere_center)
    return distance <= radius

def round_to_nearest_eighth_inch(value_in_feet):
    step = 1.0 / 96.0  # 1/8 in in Revit internal feet
    return round(value_in_feet / step) * step

def get_matching_pipes_for_radius(hanger_location, pipes, radius):
    matches = []
    for pipe in pipes:
        pipe_line = pipe.Location.Curve
        closest_point = pipe_line.Project(hanger_location).XYZPoint
        if is_point_in_sphere(closest_point, hanger_location, radius):
            matches.append(pipe)
    return matches

# Function to get pipe properties
def get_pipe_properties(pipe):
    size = pipe.LookupParameter('Size').AsString()
    system_type = pipe.LookupParameter('System Type').AsString()
    return size, system_type

def get_centerline_elevation_at_hanger_xy(pipe_line, hanger_location):
    start_point = pipe_line.GetEndPoint(0)
    end_point = pipe_line.GetEndPoint(1)

    dx = end_point.X - start_point.X
    dy = end_point.Y - start_point.Y
    plan_length_sq = (dx * dx) + (dy * dy)

    if plan_length_sq > 1e-12:
        # Project hanger XY onto the pipe XY vector to get station along the segment.
        hx = hanger_location.X - start_point.X
        hy = hanger_location.Y - start_point.Y
        t = ((hx * dx) + (hy * dy)) / plan_length_sq
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
    else:
        # Vertical-in-plan edge case: use 3D closest point as fallback.
        point_on_pipe = pipe_line.Project(hanger_location).XYZPoint
        pipe_vector = XYZ.Subtract(end_point, start_point)
        pipe_length_sq = pipe_vector.DotProduct(pipe_vector)
        if pipe_length_sq <= 1e-12:
            t = 0.0
        else:
            to_point = XYZ.Subtract(point_on_pipe, start_point)
            t = to_point.DotProduct(pipe_vector) / pipe_length_sq
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0

    return start_point.Z + (t * (end_point.Z - start_point.Z))

# Function to get pipe data at hanger location
def get_pipe_data_at_hanger(pipe, hanger_xy_location):
    # Get pipe curve
    pipe_line = pipe.Location.Curve
    
    # Get start and end points
    start_point = pipe_line.GetEndPoint(0)
    end_point = pipe_line.GetEndPoint(1)
    
    # Get lower-end BOP and derive centerline-to-BOP offset from actual endpoint geometry.
    lower_elevation = pipe.LookupParameter('Lower End Bottom Elevation').AsDouble()
    lower_endpoint = start_point if start_point.Z <= end_point.Z else end_point
    centerline_to_bop = lower_endpoint.Z - lower_elevation

    # Calculate centerline elevation at hanger XY, independent of hanger Z.
    centerline_z_at_hanger = get_centerline_elevation_at_hanger_xy(pipe_line, hanger_xy_location)

    # Convert centerline elevation to BOP using the derived offset.
    bop_raw = centerline_z_at_hanger - centerline_to_bop
    
    # Get pipe diameter and insulation thickness
    pipe_diameter = pipe.LookupParameter('Diameter').AsDouble()
    insulation_thickness = pipe.LookupParameter('Insulation Thickness').AsDouble()
    
    boi_raw = bop_raw - insulation_thickness
    bop = round_to_nearest_eighth_inch(bop_raw)
    boi = round_to_nearest_eighth_inch(boi_raw)
    
    # Get system abbreviation
    system_abbr = pipe.LookupParameter('System Abbreviation').AsString()
    
    return {
        'bop': bop,
        'boi': boi,
        'pipe_size': pipe_diameter,
        'insulation_thickness': insulation_thickness,
        'pipe_id': float(pipe.Id.IntegerValue),  # Convert to float
        'system_abbr': system_abbr  # Add system abbreviation
    }

# Process each hanger
for hanger in hangers:
    # Get hanger location and nominal radius
    hanger_location = hanger.Location.Point
    nom_radius = hanger.LookupParameter('Nom Radius').AsDouble()

    # Find initial matches using nominal radius.
    conflicting_pipes = get_matching_pipes_for_radius(hanger_location, collector_pipes, nom_radius)

    # If multiple pipes match, tighten search diameter by 0.5 in each pass.
    radius_step = (0.5 / 12.0) / 2.0  # 0.5 in diameter = 0.25 in radius (internal feet)
    current_radius = nom_radius
    while len(conflicting_pipes) > 1 and (current_radius - radius_step) > 0:
        current_radius -= radius_step
        conflicting_pipes = get_matching_pipes_for_radius(hanger_location, collector_pipes, current_radius)

    # If nothing matches, expand search diameter by 0.5 in each pass up to 4 in total.
    if not conflicting_pipes:
        max_diameter_increase = 4.0 / 12.0
        diameter_step = 0.5 / 12.0
        current_radius = nom_radius
        radius_limit = nom_radius + (max_diameter_increase / 2.0)

        while not conflicting_pipes and current_radius < radius_limit:
            next_radius = current_radius + (diameter_step / 2.0)
            if next_radius > radius_limit:
                next_radius = radius_limit
            current_radius = next_radius
            conflicting_pipes = get_matching_pipes_for_radius(hanger_location, collector_pipes, current_radius)
    
    # Add this inside your hanger processing loop after checking sphere intersection
    #print("Hanger ID: {} found {} conflicting pipes".format(
    #    hanger.Id.IntegerValue,
    #    len(conflicting_pipes)
    #))
    
    # Process results
    if not conflicting_pipes:
        hangers_no_pipes.append(hanger)
    elif len(conflicting_pipes) == 1:
        hangers_with_pipes.append((hanger, conflicting_pipes[0], False, conflicting_pipes))
    else:
        # Check if all conflicting pipes have same properties
        first_pipe = conflicting_pipes[0]
        first_size, first_system = get_pipe_properties(first_pipe)
        
        all_same = True
        for pipe in conflicting_pipes[1:]:
            size, system = get_pipe_properties(pipe)
            if size != first_size or system != first_system:
                all_same = False
                break
        
        if all_same:
            hangers_with_pipes.append((hanger, first_pipe, True, conflicting_pipes))
        else:
            hangers_multiple_systems.append((hanger, conflicting_pipes))

def set_parameter_safely(element, param_name, value):
    param = element.LookupParameter(param_name)
    if param:
        try:
            param.Set(value)
            return True
        except Exception as ex:
            print("Warning: Failed to set parameter '{}' on element {}: {}".format(param_name, element.Id, str(ex)))
            if param_name != 'QTC Error':
                set_error_message(element, "Parameter {} set failed".format(param_name))
            return False
    else:
        print("Warning: Parameter '{}' not found on element {}".format(param_name, element.Id))
        if param_name != 'QTC Error':
            if not set_error_message(element, "Parameter {} not found".format(param_name)):
                print("Warning: Parameter 'QTC Error' not found or not writable on element {}".format(element.Id))
        return False

def set_error_message(element, message):
    error_param, reason = get_qtc_error_parameter(element, require_writable=True)
    if error_param is None:
        print("Warning: {} on element {}".format(reason, element.Id))
        return False

    try:
        error_param.Set(message)
        return True
    except Exception as ex:
        print("Warning: Failed writing QTC Error on element {}: {}".format(element.Id, str(ex)))
        return False

def is_script_error_message(message):
    if not message:
        return False

    static_messages = set([
        'Hanger elevation does not match pipe centerline',
        'Hanger size too small for pipe + insulation',
        'Rod diameter does not match standards table',
        'Pipe size exceeds standards table',
        'Multiple pipes same system',
        'No pipe found',
        'Multiple systems found'
    ])

    if message in static_messages:
        return True

    if message.startswith('Parameter ') and (
        message.endswith(' set failed') or message.endswith(' not found')
    ):
        return True

    return False

def clear_script_error_message_if_present(element):
    error_param, reason = get_qtc_error_parameter(element, require_writable=True)
    if error_param is None:
        print("Warning: {} on element {}".format(reason, element.Id))
        return False

    current_message = error_param.AsString()
    if is_script_error_message(current_message):
        try:
            error_param.Set('')
            return True
        except Exception as ex:
            print("Warning: Failed clearing QTC Error on element {}: {}".format(element.Id, str(ex)))
            return False

    return True

def get_expected_rod_diameter(pipe_size_feet):
    pipe_size_inches = pipe_size_feet * 12.0
    size_tolerance_inches = 1e-4

    if pipe_size_inches > (12.0 + size_tolerance_inches):
        return None, 'Pipe size exceeds standards table'

    if pipe_size_inches <= (4.0 + size_tolerance_inches):
        return 0.375 / 12.0, None

    if (pipe_size_inches >= (5.0 - size_tolerance_inches)) and (pipe_size_inches <= (8.0 + size_tolerance_inches)):
        return 0.5 / 12.0, None

    if abs(pipe_size_inches - 10.0) <= size_tolerance_inches:
        return 0.625 / 12.0, None

    if abs(pipe_size_inches - 12.0) <= size_tolerance_inches:
        return 0.75 / 12.0, None

    return None, None

elevation_tolerance = 1.0 / 192.0  # 1/16 in in internal feet
mismatched_hanger_targets = {}
rod_mismatch_targets = {}
pipe_size_exceeds_standards = set()
rod_diameter_tolerance = 1e-6
for hanger, pipe, multiple_same_systems, related_pipes in hangers_with_pipes:
    hanger_location = hanger.Location.Point
    centerline_z_at_hanger = get_centerline_elevation_at_hanger_xy(pipe.Location.Curve, hanger_location)
    if abs(hanger_location.Z - centerline_z_at_hanger) > elevation_tolerance:
        mismatched_hanger_targets[hanger.Id.IntegerValue] = centerline_z_at_hanger

    expected_rod_diameter, standards_warning = get_expected_rod_diameter(pipe.LookupParameter('Diameter').AsDouble())
    if standards_warning == 'Pipe size exceeds standards table':
        pipe_size_exceeds_standards.add(hanger.Id.IntegerValue)
    elif expected_rod_diameter is not None:
        rod_param = hanger.LookupParameter('Rod Diameter')
        if rod_param is None:
            rod_mismatch_targets[hanger.Id.IntegerValue] = expected_rod_diameter
        else:
            actual_rod_diameter = rod_param.AsDouble()
            if abs(actual_rod_diameter - expected_rod_diameter) > rod_diameter_tolerance:
                rod_mismatch_targets[hanger.Id.IntegerValue] = expected_rod_diameter

update_mismatched_hanger_elevations = False
if len(mismatched_hanger_targets) > 0:
    prompt = (
        "{} hangers do not match the pipe centerline elevation at their location.\n\n"
        "Update hanger elevations to match centerline elevation?"
    ).format(len(mismatched_hanger_targets))
    update_mismatched_hanger_elevations = forms.alert(
        prompt,
        title='Hanger Elevation Mismatch',
        yes=True,
        no=True,
        warn_icon=True
    )

update_mismatched_rod_diameters = False
if len(rod_mismatch_targets) > 0:
    rod_prompt = (
        "{} hangers do not match the rod diameter standards for their pipe size.\n\n"
        "Update rod diameters to match standards?"
    ).format(len(rod_mismatch_targets))
    update_mismatched_rod_diameters = forms.alert(
        rod_prompt,
        title='Rod Diameter Mismatch',
        yes=True,
        no=True,
        warn_icon=True
    )

updated_hanger_elevation_count = 0
flagged_hanger_elevation_count = 0
flagged_hanger_size_count = 0
updated_rod_diameter_count = 0
flagged_rod_diameter_count = 0
flagged_pipe_standards_count = 0
one_inch_in_feet = 1.0 / 12.0
three_inches_in_feet = 3.0 / 12.0
insulation_match_tolerance = 1e-6
hanger_size_tolerance = 1e-6

# Modify the transaction section
with revit.Transaction('Update Hanger Parameters'):
    # First handle successful matches
    for hanger, pipe, multiple_same_systems, related_pipes in hangers_with_pipes:
        # Get hanger XY location
        hanger_location = hanger.Location.Point
        has_unresolved_elevation_mismatch = False
        has_hanger_size_mismatch = False
        has_rod_diameter_mismatch = False
        has_pipe_size_standards_warning = False

        # Optionally align hanger elevation to pipe centerline at hanger location.
        target_centerline_z = mismatched_hanger_targets.get(hanger.Id.IntegerValue)
        if target_centerline_z is not None:
            if update_mismatched_hanger_elevations:
                z_delta = target_centerline_z - hanger_location.Z
                if abs(z_delta) > elevation_tolerance:
                    ElementTransformUtils.MoveElement(doc, hanger.Id, XYZ(0, 0, z_delta))
                    updated_hanger_elevation_count += 1
                hanger_location = hanger.Location.Point
            else:
                set_error_message(hanger, 'Hanger elevation does not match pipe centerline')
                flagged_hanger_elevation_count += 1
                has_unresolved_elevation_mismatch = True
                track_error_elements(hanger, related_pipes)
        
        # Get pipe data at hanger location
        pipe_data = get_pipe_data_at_hanger(pipe, hanger_location)
        
        # Update hanger parameters safely
        updates_succeeded = True
        updates_succeeded = set_parameter_safely(hanger, 'BOP', pipe_data['bop']) and updates_succeeded
        updates_succeeded = set_parameter_safely(hanger, 'BOI', pipe_data['boi']) and updates_succeeded
        updates_succeeded = set_parameter_safely(hanger, 'QTC Pipe Size', pipe_data['pipe_size']) and updates_succeeded
        updates_succeeded = set_parameter_safely(hanger, 'QTC Insulation Thickness', pipe_data['insulation_thickness']) and updates_succeeded
        updates_succeeded = set_parameter_safely(hanger, 'QTC Pipe ID', pipe_data['pipe_id']) and updates_succeeded
        updates_succeeded = set_parameter_safely(hanger, 'Support Discipline', pipe_data['system_abbr']) and updates_succeeded

        # Hanger size must be >= pipe OD + 2x insulation thickness.
        required_hanger_size = pipe_data['pipe_size'] + (2.0 * pipe_data['insulation_thickness'])
        if abs(pipe_data['insulation_thickness'] - one_inch_in_feet) <= insulation_match_tolerance:
            required_hanger_size = max(required_hanger_size, three_inches_in_feet)
        actual_hanger_size = 2.0 * hanger.LookupParameter('Nom Radius').AsDouble()
        if (actual_hanger_size + hanger_size_tolerance) < required_hanger_size:
            set_error_message(hanger, 'Hanger size too small for pipe + insulation')
            has_hanger_size_mismatch = True
            flagged_hanger_size_count += 1
            track_error_elements(hanger, related_pipes)

        if hanger.Id.IntegerValue in pipe_size_exceeds_standards:
            set_error_message(hanger, 'Pipe size exceeds standards table')
            has_pipe_size_standards_warning = True
            flagged_pipe_standards_count += 1
            track_error_elements(hanger, related_pipes)

        target_rod_diameter = rod_mismatch_targets.get(hanger.Id.IntegerValue)
        if target_rod_diameter is not None:
            if update_mismatched_rod_diameters:
                if set_parameter_safely(hanger, 'Rod Diameter', target_rod_diameter):
                    updated_rod_diameter_count += 1
                else:
                    has_rod_diameter_mismatch = True
                    track_error_elements(hanger, related_pipes)
            else:
                set_error_message(hanger, 'Rod diameter does not match standards table')
                has_rod_diameter_mismatch = True
                flagged_rod_diameter_count += 1
                track_error_elements(hanger, related_pipes)

        if not updates_succeeded:
            track_error_elements(hanger, related_pipes)

        if updates_succeeded and (not multiple_same_systems) and (not has_unresolved_elevation_mismatch) and (not has_hanger_size_mismatch) and (not has_rod_diameter_mismatch) and (not has_pipe_size_standards_warning):
            clear_script_error_message_if_present(hanger)

        if multiple_same_systems:
            set_error_message(hanger, 'Multiple pipes same system')
            track_error_elements(hanger, related_pipes)

    # Handle hangers with no pipes
    for hanger in hangers_no_pipes:
        set_error_message(hanger, 'No pipe found')
        track_error_elements(hanger)
    
    # Handle hangers with multiple systems
    for hanger, pipes in hangers_multiple_systems:
        set_error_message(hanger, 'Multiple systems found')
        track_error_elements(hanger, pipes)

if len(error_hanger_ids) > 0:
    isolate_element_ids = List[ElementId]()
    for element_id in sorted(error_hanger_ids.union(error_pipe_ids)):
        isolate_element_ids.Add(ElementId(element_id))

    with revit.Transaction('Isolate Error Hangers and Pipes'):
        active_view.IsolateElementsTemporary(isolate_element_ids)

# Update results message to include parameter updates
results_message = '''Results:
{0} hangers successfully matched and updated
{1} hangers with no pipes
{2} hangers with conflicting pipes
{3} hanger elevations updated to centerline
{4} hangers flagged for elevation mismatch
{5} hangers flagged for undersized support
{6} rod diameters updated to standards
{7} hangers flagged for rod diameter mismatch
{8} hangers flagged for pipe size above standards table'''.format(
    len(hangers_with_pipes),
    len(hangers_no_pipes),
    len(hangers_multiple_systems),
    updated_hanger_elevation_count,
    flagged_hanger_elevation_count,
    flagged_hanger_size_count,
    updated_rod_diameter_count,
    flagged_rod_diameter_count,
    flagged_pipe_standards_count
)
forms.alert(results_message)