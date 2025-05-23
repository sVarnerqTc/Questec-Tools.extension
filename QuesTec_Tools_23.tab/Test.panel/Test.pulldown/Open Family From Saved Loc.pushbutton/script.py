"""Opens the selected family from its saved location on disk."""

import os
import clr
from pyrevit import forms, script
from Autodesk.Revit.DB import FamilyInstance, Family, FamilySymbol, ElementId, ModelPathUtils, ModelPath
from Autodesk.Revit.UI import TaskDialog

# Get the current Revit application and document
app = __revit__.Application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# Get selected elements
selection = [doc.GetElement(elid) for elid in uidoc.Selection.GetElementIds()]

# Initialize output window
output = script.get_output()

def open_family_from_disk(family):
    """Find and open the family from its saved location."""
    
    try:
        # Use EditFamily to get the family document and determine path
        family_doc = doc.EditFamily(family)
        
        # Get the path from the family document
        family_path = family_doc.PathName
        
        if not family_path:
            forms.alert("Could not determine the saved location of this family.", 
                        title="Family Path Not Found")
            return
            
        # Close the family document without saving
        family_doc.Close(False)
        
        # Now open the family directly from disk path
        if os.path.exists(family_path):
            try:
                # Create a ModelPath from the file path - ensure string conversion
                model_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(str(family_path))
                
                # Open and activate the document in the UI
                opened_doc = uidoc.Application.OpenAndActivateDocument(model_path)
                
                if opened_doc:
                    output.print_md("**Family opened from disk:** {}".format(family_path))
                else:
                    forms.alert("Failed to open family file from disk.", 
                                title="Open Failed")
            except Exception as path_error:
                # Alternative approach if ModelPath conversion fails
                output.print_md("Trying alternative open method...")
                try:
                    opened_doc = app.OpenDocumentFile(family_path)
                    output.print_md("**Family opened from disk:** {}".format(family_path))
                except:
                    forms.alert("Failed to open family using both methods.\nError: {}".format(str(path_error)), 
                                title="Open Failed")
        else:
            forms.alert("Family file not found at:\n{}".format(family_path), 
                        title="File Not Found")
        
    except Exception as e:
        forms.alert("Error opening family file:\n{}".format(str(e)), 
                    title="Error Opening Family")

# Main execution
if not selection:
    forms.alert("Please select a family instance first.", title="No Selection")
else:
    # Get the first selected element only
    selected_element = selection[0]
    
    # Check if it's a family instance or symbol
    if isinstance(selected_element, FamilyInstance):
        family = selected_element.Symbol.Family
        open_family_from_disk(family)
    elif isinstance(selected_element, FamilySymbol):
        family = selected_element.Family
        open_family_from_disk(family)
    else:
        forms.alert("Please select a family instance or family symbol.", 
                    title="Invalid Selection")