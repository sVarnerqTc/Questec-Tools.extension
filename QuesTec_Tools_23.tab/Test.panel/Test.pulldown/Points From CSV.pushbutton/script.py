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
        # For shared coordinates, we need to transform from survey coordinates to project coordinates
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
        
        # Transform from shared coordinates to project coordinates
        # Step 1: Apply rotation (counter-clockwise rotation by negative angle)
        cos_angle = math.cos(-angle)
        sin_angle = math.sin(-angle)
        rotated_x = x * cos_angle - y * sin_angle
        rotated_y = x * sin_angle + y * cos_angle
        
        # Step 2: Apply translation (subtract the offsets to convert to project coordinates)
        final_x = rotated_x - east_offset
        final_y = rotated_y - north_offset
        
        print("After rotation - X: {}, Y: {}".format(rotated_x, rotated_y))
        print("Final project coordinates - X: {}, Y: {}".format(final_x, final_y))
        
        return XYZ(final_x, final_y, 0)
        
    except Exception as e:
        print("Error in coordinate transformation: {}".format(str(e)))
        print("Falling back to project internal coordinates")
        return XYZ(x, y, 0)

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
    
    with open(csv_path) as csvfile:
        reader = csv.reader(csvfile)  # Changed from DictReader to reader
        next(reader)  # Skip header row
        
        with Transaction(doc, "Place Control Points") as t:
            t.Start()
            
            for row in reader:
                point = transform_point(
                    float(row[1]),  # X value from 2nd column
                    float(row[2]),  # Y value from 3rd column
                    use_shared
                )
                point = XYZ(point.X, point.Y, level.Elevation)
                
                instance = doc.Create.NewFamilyInstance(
                    point, family_symbol, level, StructuralType.NonStructural)
                
                 # Set Mark parameter
                mark_param = instance.LookupParameter('Mark')
                if mark_param:
                    mark_param.Set(str(row[0]))  # Point number from 1st column
                else:
                    print("Could not set Mark parameter for point {}".format(row[0]))

                if override_text:
                    instance.get_Parameter(
                        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(override_text)  

                else:
                    instance.get_Parameter(
                        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(row[4]) # Description from 5th column
            
            t.Commit()

if __name__ == '__main__':
    main()