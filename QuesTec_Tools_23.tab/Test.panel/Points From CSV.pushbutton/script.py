import csv
import math
from Autodesk.Revit.DB import *
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
        return XYZ(x, y, 0)
    
    # Get project location and position
    project_location = doc.ActiveProjectLocation
    project_position = project_location.GetProjectPosition(XYZ(0, 0, 0))
    
    # Get survey point and its position
    survey_point = FilteredElementCollector(doc).OfCategory(
        BuiltInCategory.OST_SharedBasePoint).FirstElement()
    
    # Get true north rotation
    angle = project_position.Angle
    
    # Get survey point coordinates
    east = project_position.EastWest
    north = project_position.NorthSouth
    
    # Debug prints
    #print("Project Position Angle (radians): {}".format(angle))
    #print("Project Position East Offset (feet): {}".format(east))
    #print("Project Position North Offset (feet): {}".format(north))
    #print("Input coordinates - X: {}, Y: {}".format(x, y))
    
    # Apply rotation and translation
    rotated_x = x * math.cos(angle) - y * math.sin(angle)
    rotated_y = x * math.sin(angle) + y * math.cos(angle)
    
    # Apply survey point offset
    final_x = rotated_x - east
    final_y = rotated_y - north

    #print("Output coordinates - X: {}, Y: {}".format(final_x, final_y))
    
    return XYZ(final_x, final_y, 0)
    
    print("Output coordinates - X: {}, Y: {}".format(final_x, final_y))

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
                    point, family_symbol, level, Structure.StructuralType.NonStructural)
                
                 # Set Mark parameter
                mark_param = instance.LookupParameter('Mark')
                if mark_param:
                    mark_param.Set(str(row[0]))
                else:
                  print("Could not set Mark parameter for point {}".format(row['pointNumber']))

                if override_text:
                    instance.get_Parameter(
                        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(override_text)  

                else:
                    instance.get_Parameter(
                        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(row[4]) # Description from 5th column
            
            t.Commit()
    
    
    

if __name__ == '__main__':
    main()