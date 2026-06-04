import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import revit, DB, forms
import math

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
active_view = doc.ActiveView

# Lists to store results
hangers_with_pipes = []  # Successful matches
hangers_no_pipes = []    # Hangers with no pipes nearby
hangers_multiple_systems = []  # Hangers with conflicting pipes

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
hangers = []
for acc in collector_accessories:
    if acc.LookupParameter('BOP'):
        hangers.append(acc)

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
        hangers_with_pipes.append((hanger, conflicting_pipes[0], False))
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
            hangers_with_pipes.append((hanger, first_pipe, True))
        else:
            hangers_multiple_systems.append((hanger, conflicting_pipes))

def set_parameter_safely(element, param_name, value):
    param = element.LookupParameter(param_name)
    if param:
        param.Set(value)
    else:
        print("Warning: Parameter '{}' not found on element {}".format(param_name, element.Id))
        error_param = element.LookupParameter('QTC Error')
        if error_param:
            error_param.Set("Parameter {} not found".format(param_name))
        else:
            print("Warning: Parameter 'QTC Error' not found on element {}".format(element.Id))

def set_error_message(element, message):
    error_param = element.LookupParameter('QTC Error')
    if error_param and not error_param.IsReadOnly:
        error_param.Set(message)
        return True

    print("Warning: QTC Error not found or not writable on element {}".format(element.Id))
    return False

elevation_tolerance = 1.0 / 192.0  # 1/16 in in internal feet
mismatched_hanger_targets = {}
for hanger, pipe, multiple_same_systems in hangers_with_pipes:
    hanger_location = hanger.Location.Point
    centerline_z_at_hanger = get_centerline_elevation_at_hanger_xy(pipe.Location.Curve, hanger_location)
    if abs(hanger_location.Z - centerline_z_at_hanger) > elevation_tolerance:
        mismatched_hanger_targets[hanger.Id.IntegerValue] = centerline_z_at_hanger

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

updated_hanger_elevation_count = 0
flagged_hanger_elevation_count = 0

# Modify the transaction section
with revit.Transaction('Update Hanger Parameters'):
    # First handle successful matches
    for hanger, pipe, multiple_same_systems in hangers_with_pipes:
        # Get hanger XY location
        hanger_location = hanger.Location.Point

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
        
        # Get pipe data at hanger location
        pipe_data = get_pipe_data_at_hanger(pipe, hanger_location)
        
        # Update hanger parameters safely
        set_parameter_safely(hanger, 'BOP', pipe_data['bop'])
        set_parameter_safely(hanger, 'BOI', pipe_data['boi'])
        set_parameter_safely(hanger, 'QTC Pipe Size', pipe_data['pipe_size'])
        set_parameter_safely(hanger, 'QTC Insulation Thickness', pipe_data['insulation_thickness'])
        set_parameter_safely(hanger, 'QTC Pipe ID', pipe_data['pipe_id'])
        set_parameter_safely(hanger, 'Support Discipline', pipe_data['system_abbr'])

        if multiple_same_systems:
            set_error_message(hanger, 'Multiple pipes same system')

    # Handle hangers with no pipes
    for hanger in hangers_no_pipes:
        set_error_message(hanger, 'No pipe found')
    
    # Handle hangers with multiple systems
    for hanger, pipes in hangers_multiple_systems:
        set_error_message(hanger, 'Multiple systems found')

# Update results message to include parameter updates
results_message = '''Results:
{0} hangers successfully matched and updated
{1} hangers with no pipes
{2} hangers with conflicting pipes
{3} hanger elevations updated to centerline
{4} hangers flagged for elevation mismatch'''.format(
    len(hangers_with_pipes),
    len(hangers_no_pipes),
    len(hangers_multiple_systems),
    updated_hanger_elevation_count,
    flagged_hanger_elevation_count
)
forms.alert(results_message)