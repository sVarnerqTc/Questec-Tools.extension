import clr
from Autodesk.Revit.DB import *
from pyrevit import forms
from System.Collections.Generic import List

doc = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

# Ask user for scope
options = ['Active View Only', 'Entire Model']
selected_scope = forms.CommandSwitchWindow.show(
    options,
    message='Select scope for area assignment:'
)

if not selected_scope:
    forms.alert('No scope selected. Script cancelled.', exitscript=True)

# Collect all scope boxes
scope_boxes = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_VolumeOfInterest).WhereElementIsNotElementType().ToElements()
scope_box_names = [sb.Name for sb in scope_boxes]

# Let user select scope boxes through checkbox UI
selected_boxes = forms.SelectFromList.show(
    scope_box_names,
    title='Select Scope Boxes to Use as Areas',
    button_name='Select',
    multiselect=True
)

if not selected_boxes:
    forms.alert('No scope boxes selected. Script cancelled.', exitscript=True)

# Create dictionary of selected scope boxes and their bounding boxes
box_dict = {sb.Name: sb.get_BoundingBox(None) for sb in scope_boxes if sb.Name in selected_boxes}

# Collect all relevant elements
categories = [
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PlumbingFixtures
]

elements = []
for category in categories:
    if selected_scope == 'Active View Only':
        collector = FilteredElementCollector(doc, active_view.Id)
    else:  # Entire Model
        collector = FilteredElementCollector(doc)
    
    elements.extend(
        collector
        .OfCategory(category)
        .WhereElementIsNotElementType()
        .ToElements()
    )

# Transaction to update parameters
t = Transaction(doc, 'Update QTC Area Parameters')
t.Start()

try:
    for element in elements:
        # Get element location point
        if isinstance(element, FamilyInstance):
            location = element.Location.Point
        else:  # For pipes
            location = element.Location.Curve.Evaluate(0.5, True)  # Get midpoint
        
        # Find which scope box contains this point
        for box_name, bbox in box_dict.items():
            if (bbox.Min.X <= location.X <= bbox.Max.X and
                bbox.Min.Y <= location.Y <= bbox.Max.Y and
                bbox.Min.Z <= location.Z <= bbox.Max.Z):
                
                # Set the QTC Area parameter
                try:
                    param = element.LookupParameter('QTC Area')
                    if param and not param.IsReadOnly:
                        param.Set(box_name)
                except Exception as e:
                    print("Could not set parameter for element {0}: {1}".format(element.Id, str(e)))
                break

    t.Commit()
    forms.alert('Successfully assigned areas to elements!')

except Exception as e:
    t.RollBack()
    forms.alert('Error occurred: {0}'.format(str(e)))