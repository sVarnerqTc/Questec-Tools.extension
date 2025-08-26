import csv
import math
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons
from pyrevit import forms
import os
from rpw.ui.forms import SelectFromList

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

def get_csv_path():
    return forms.pick_file(file_ext='csv')

def get_levels():
    return FilteredElementCollector(doc).OfClass(Level).ToElements()

def get_control_point_family():
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
    for item in collector:
        if item.FamilyName == "SSW Control Point":
            return item
    return None

def transform_point(x, y, use_shared):
    if not use_shared:
        # For project internal coordinates, use coordinates as-is
        print("Using project internal coordinates - X: {}, Y: {}".format(x, y))
        return XYZ(x, y, 0)
    
    try:
        # For shared coordinates, use Revit's built-in transformation
        project_location = doc.ActiveProjectLocation
        
        # Create a point in shared coordinates
        shared_point = XYZ(x, y, 0)
        
        # Transform from shared coordinates to project coordinates
        # This uses Revit's internal transformation logic
        project_point = project_location.SharedToProject(shared_point)
        
        print("Input shared coordinates - X: {}, Y: {}".format(x, y))
        print("Transformed project coordinates - X: {}, Y: {}".format(project_point.X, project_point.Y))
        
        return XYZ(project_point.X, project_point.Y, 0)
        
    except Exception as e:
        print("Error in coordinate transformation: {}".format(str(e)))
        print("Falling back to manual transformation")
        
        # Fallback to manual transformation if built-in method fails
        project_location = doc.ActiveProjectLocation
        project_position = project_location.GetProjectPosition(XYZ(0, 0, 0))
        
        # Get survey point (shared base point)
        survey_point = FilteredElementCollector(doc).OfCategory(
            BuiltInCategory.OST_SharedBasePoint).FirstElement()
        
        if not survey_point:
            print("Warning: Survey point not found, using coordinates as project internal")
            return XYZ(x, y, 0)
        
        # Get the transformation parameters
        angle = project_position.Angle  # True north rotation angle
        east_offset = project_position.EastWest  # Project base point offset from survey point (East)
        north_offset = project_position.NorthSouth  # Project base point offset from survey point (North)
        
        # Get survey point position in project coordinates
        survey_point_pos = survey_point.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM).AsDouble()
        survey_point_north = survey_point.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM).AsDouble()
        
        # Debug prints
        print("Project Position Angle (radians): {}".format(angle))
        print("Project Position East Offset (feet): {}".format(east_offset))
        print("Project Position North Offset (feet): {}".format(north_offset))
        print("Survey Point East (feet): {}".format(survey_point_pos))
        print("Survey Point North (feet): {}".format(survey_point_north))
        print("Input shared coordinates - X: {}, Y: {}".format(x, y))
        
        # Apply rotation transformation (inverse of true north rotation)
        cos_angle = math.cos(-angle)
        sin_angle = math.sin(-angle)
        rotated_x = x * cos_angle - y * sin_angle
        rotated_y = x * sin_angle + y * cos_angle
        
        # Apply the correct transformation formula for offsets
        # For the x offset: -PPE*cos(a) - PPN*sin(a)
        # For the y offset: -PPN*cos(a) + PPE*sin(a)
        # where PPE = east_offset, PPN = north_offset, a = angle
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        
        x_offset = -east_offset * cos_a - north_offset * sin_a
        y_offset = -north_offset * cos_a + east_offset * sin_a
        
        final_x = rotated_x + x_offset
        final_y = rotated_y + y_offset
        
        print("After rotation - X: {}, Y: {}".format(rotated_x, rotated_y))
        print("Calculated offsets - X: {}, Y: {}".format(x_offset, y_offset))
        print("Final project coordinates - X: {}, Y: {}".format(final_x, final_y))
        
        return XYZ(final_x, final_y, 0)

def verify_csv_headers(headers):
    required = ['pointNumber', 'X', 'Y', 'Z', 'Description', 'Layer']
    missing = [h for h in required if h not in headers]
    if missing:
        TaskDialog.Show("Error", "Missing required columns: " + ", ".join(missing))
        return False
    return True

def main():

    # Check for 2D view
    active_view = doc.ActiveView
    if not isinstance(active_view, ViewPlan):
        TaskDialog.Show("Error", "Please activate a 2D view before running this script.")
        return
    
    csv_path = get_csv_path()
    if not csv_path:
        return
    
    active_view = doc.ActiveView
    if isinstance(active_view, ViewPlan):
        level = active_view.GenLevel
    else:
        levels = get_levels()
        level = SelectFromList('Select Level', levels, lambda x: x.Name)
        if not level:
            return
    
    use_shared = forms.alert('Use Shared Coordinates?', 
                           options=["Yes", "No"]) == "Yes"
    
    family_symbol = get_control_point_family()
    if not family_symbol:
        TaskDialog.Show("Error", "SSW Control Point family not found")
        return
        
    if not family_symbol.IsActive:
        with Transaction(doc, "Activate Family Symbol") as t:
            t.Start()
            family_symbol.Activate()
            t.Commit()

    override_text = forms.ask_for_string(
        prompt='Enter text to override Comments (leave empty to keep original)',
        title='Overwrite Comments?'
    )
    
    with open(csv_path, 'rb') as csvfile:
        # Read the file and handle line endings
        content = csvfile.read().replace('\r\n', '\n').replace('\r', '\n')
        lines = content.strip().split('\n')
        
        with Transaction(doc, "Place Control Points") as t:
            t.Start()
            
            for row_num, line in enumerate(lines, 1):
                # Skip empty lines
                if not line.strip():
                    continue
                
                # Split the line by comma
                row = [field.strip() for field in line.split(',')]
                
                # Skip rows with insufficient data
                if len(row) < 3:
                    print("Skipping row {}: insufficient data - {}".format(row_num, row))
                    continue
                
                try:
                    # Extract coordinates, handling potential extra/missing columns
                    point_number = str(row[0]).strip()
                    x_coord = float(row[1])
                    y_coord = float(row[2])
                    
                    # Z coordinate (optional, default to 0)
                    z_coord = float(row[3]) if len(row) > 3 and row[3].strip() else 0
                    
                    # Description (optional, default to empty)
                    description = str(row[4]).strip() if len(row) > 4 and row[4].strip() else ""
                    
                    print("Processing point: {} at ({}, {})".format(point_number, x_coord, y_coord))
                    
                    point = transform_point(x_coord, y_coord, use_shared)
                    point = XYZ(point.X, point.Y, level.Elevation)
                    
                    instance = doc.Create.NewFamilyInstance(
                        point, family_symbol, level, StructuralType.NonStructural)
                    
                    # Set Mark parameter
                    mark_param = instance.LookupParameter('Mark')
                    if mark_param:
                        mark_param.Set(point_number)
                    else:
                        print("Could not set Mark parameter for point {}".format(point_number))

                    if override_text:
                        instance.get_Parameter(
                            BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(override_text)  
                    else:
                        instance.get_Parameter(
                            BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(description)
                            
                except (ValueError, IndexError) as e:
                    print("Error processing row {}: {} - Data: {}".format(row_num, str(e), row))
                    continue
            
            t.Commit()

if __name__ == '__main__':
    main()