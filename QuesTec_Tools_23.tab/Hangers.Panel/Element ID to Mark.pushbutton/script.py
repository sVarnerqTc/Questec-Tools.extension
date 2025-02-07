from Autodesk.Revit.DB import *
from pyrevit import revit, DB

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# Get selected elements
selection = [doc.GetElement(id) for id in uidoc.Selection.GetElementIds()]

# Check if anything is selected
if not selection:
    print("Please select at least one element.")
    exit()

# Start transaction
t = Transaction(doc, 'Set Element ID to Mark')
t.Start()

try:
    for element in selection:
        # Get element ID as string (remove the 'Id' prefix)
        element_id = str(element.Id.IntegerValue)
        
        # Get Mark parameter
        mark_param = element.LookupParameter('Mark')
        
        if mark_param:
            # Set the Mark parameter
            mark_param.Set(element_id)
        else:
            print("Could not set Mark parameter for element {}".format(element_id))
    
    t.Commit()
    print("Successfully updated Mark parameter for {} elements".format(len(selection)))

except Exception as e:
    t.RollBack()
    print("Error occurred: ", str(e))