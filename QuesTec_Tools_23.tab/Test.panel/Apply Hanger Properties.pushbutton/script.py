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

# Function to get pipe properties
def get_pipe_properties(pipe):
    size = pipe.LookupParameter('Size').AsString()
    system_type = pipe.LookupParameter('System Type').AsString()
    return size, system_type

# Function to get pipe data at hanger location
def get_pipe_data_at_hanger(pipe, hanger_xy_location):
    # Get pipe curve
    pipe_line = pipe.Location.Curve
    
    # Get start and end points
    start_point = pipe_line.GetEndPoint(0)
    end_point = pipe_line.GetEndPoint(1)
    
    # Get lower end elevation from pipe parameter
    lower_elevation = pipe.LookupParameter('Lower End Bottom Elevation').AsDouble()
    
    # Project hanger point onto pipe line
    point_on_pipe = pipe_line.Project(hanger_xy_location).XYZPoint
    
    # Calculate slope using pipe endpoints
    pipe_length = pipe_line.Length
    elevation_change = end_point.Z - start_point.Z
    slope = elevation_change / pipe_length
    
    # Calculate distance along pipe from start to projected point
    vector_to_point = XYZ.Subtract(point_on_pipe, start_point)
    distance_along_pipe = vector_to_point.DotProduct(pipe_line.Direction)
    
    # Calculate BOP at hanger location using slope
    bop = lower_elevation + (slope * distance_along_pipe)
    
    # Get pipe diameter and insulation thickness
    pipe_diameter = pipe.LookupParameter('Diameter').AsDouble()
    insulation_thickness = pipe.LookupParameter('Insulation Thickness').AsDouble()
    
    boi = bop - insulation_thickness
    
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
    
    # Find conflicting pipes
    conflicting_pipes = []
    
    for pipe in collector_pipes:
        pipe_line = pipe.Location.Curve
        # Get closest point on pipe to hanger
        closest_point = pipe_line.Project(hanger_location).XYZPoint
        
        if is_point_in_sphere(closest_point, hanger_location, nom_radius):
            conflicting_pipes.append(pipe)
    
    # Add this inside your hanger processing loop after checking sphere intersection
    #print("Hanger ID: {} found {} conflicting pipes".format(
    #    hanger.Id.IntegerValue,
    #    len(conflicting_pipes)
    #))
    
    # Process results
    if not conflicting_pipes:
        hangers_no_pipes.append(hanger)
    elif len(conflicting_pipes) == 1:
        hangers_with_pipes.append((hanger, conflicting_pipes[0]))
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
            hangers_with_pipes.append((hanger, first_pipe))
        else:
            hangers_multiple_systems.append((hanger, conflicting_pipes))

def set_parameter_safely(element, param_name, value):
    param = element.LookupParameter(param_name)
    if param:
        param.Set(value)
    else:
        print("Warning: Parameter '{}' not found on element {}".format(param_name, element.Id))
        element.LookupParameter('QTC Error').Set("Parameter {} not found".format(param_name))  # Fixed quotes

# Modify the transaction section
with revit.Transaction('Update Hanger Parameters'):
    # First handle successful matches
    for hanger, pipe in hangers_with_pipes:
        # Get hanger XY location
        hanger_location = hanger.Location.Point
        
        # Get pipe data at hanger location
        pipe_data = get_pipe_data_at_hanger(pipe, hanger_location)
        
        # Update hanger parameters safely
        set_parameter_safely(hanger, 'BOP', pipe_data['bop'])
        set_parameter_safely(hanger, 'BOI', pipe_data['boi'])
        set_parameter_safely(hanger, 'QTC Pipe Size', pipe_data['pipe_size'])
        set_parameter_safely(hanger, 'QTC Insulation Thickness', pipe_data['insulation_thickness'])
        set_parameter_safely(hanger, 'QTC Pipe ID', pipe_data['pipe_id'])
        set_parameter_safely(hanger, 'Support Discipline', pipe_data['system_abbr'])
        
        # Add error message if this was from multiple same-system pipes
        if len(conflicting_pipes) > 1:
            set_parameter_safely(hanger, 'QTC Error', 'Multiple pipes same system')

    # Handle hangers with no pipes
    for hanger in hangers_no_pipes:
        set_parameter_safely(hanger, 'QTC Error', 'No pipe found')
    
    # Handle hangers with multiple systems
    for hanger, pipes in hangers_multiple_systems:
        set_parameter_safely(hanger, 'QTC Error', 'Multiple systems found')

# Update results message to include parameter updates
results_message = '''Results:
{0} hangers successfully matched and updated
{1} hangers with no pipes
{2} hangers with conflicting pipes'''.format(
    len(hangers_with_pipes),
    len(hangers_no_pipes),
    len(hangers_multiple_systems)
)
forms.alert(results_message)