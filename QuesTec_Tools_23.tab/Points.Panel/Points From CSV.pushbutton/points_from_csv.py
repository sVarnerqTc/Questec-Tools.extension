import csv
import os
from pyrevit import forms
from Autodesk.Revit.DB import FilteredElementCollector, FamilyInstance, XYZ, Transaction, BuiltInCategory

# Prompt user to select a CSV file
file_path = forms.pick_file(file_ext='csv', files_filter="CSV files (*.csv)|*.csv", multi_file=False)
if not file_path or not os.path.exists(file_path):
    forms.alert('No file selected or file does not exist.', exitscript=True)

# Read data from CSV file (mark, x, y, z, comments)
data = []
with open(file_path, 'r') as csvfile:
    csvreader = csv.reader(csvfile)
    for row in csvreader:
        try:
            # Expecting the format: mark, X, Y, Z, comments
            mark = row[0]
            x = float(row[1])
            y = float(row[2])
            z = float(row[3])
            comments = row[4]
            # Store the data as a tuple with mark, XYZ object, and comments
            data.append((mark, x, y, z, comments))
        except (ValueError, IndexError):
            forms.alert('Invalid CSV format. Ensure it contains mark, X, Y, Z, and comments.', exitscript=True)

# Get current Revit document
doc = __revit__.ActiveUIDocument.Document

# Collect all loaded pipe accessories from the project
pipe_accessory_collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_PipeAccessory).WhereElementIsElementType()

# Create a dictionary of pipe accessory types for user selection
pipe_accessories = {}
for fam_symbol in pipe_accessory_collector:
    pipe_accessories[fam_symbol.FamilyName] = fam_symbol

if not pipe_accessories:
    forms.alert("No pipe accessories found in the project.", exitscript=True)

# Prompt user to select a pipe accessory type
selected_accessory_name = forms.SelectFromList.show(list(pipe_accessories.keys()), title='Select Pipe Accessory', button_name='Select')
if not selected_accessory_name:
    forms.alert('No pipe accessory selected.', exitscript=True)

selected_accessory_type = pipe_accessories[selected_accessory_name]

# Ensure that the family symbol is activated
if not selected_accessory_type.IsActive:
    t_activate = Transaction(doc, 'Activate Family Symbol')
    t_activate.Start()
    selected_accessory_type.Activate()
    t_activate.Commit()

# Start transaction to place instances of pipe accessory at each coordinate and set mark and comments
t = Transaction(doc, 'Place Pipe Accessories from CSV')
t.Start()

try:
    for mark, x, y, z, comments in data:
        # Create the XYZ object from x, y, z coordinates
        coord = XYZ(x, y, z)
        
        # Place the pipe accessory at the given coordinate (XYZ object)
        accessory_instance = doc.Create.NewFamilyInstance(coord, selected_accessory_type, doc.ActiveView)
        
        # Set the "Mark" and "Comments" parameters
        mark_param = accessory_instance.LookupParameter('Mark')
        comments_param = accessory_instance.LookupParameter('Comments')
        
        if mark_param and mark:
            mark_param.Set(mark)
        
        if comments_param and comments:
            comments_param.Set(comments)
    
    t.Commit()
    forms.alert('Pipe accessories placed successfully with Mark and Comments!')

except Exception as e:
    t.RollBack()
    forms.alert('Error placing pipe accessories: {}'.format(str(e)), exitscript=True)
