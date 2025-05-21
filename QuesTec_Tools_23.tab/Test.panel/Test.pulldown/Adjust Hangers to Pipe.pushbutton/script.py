# coding: utf-8
import clr
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import Transaction, ElementTransformUtils, XYZ
from Autodesk.Revit.UI.Selection import ObjectType
import sys

# Get the active document
doc = revit.doc
uidoc = revit.uidoc

# Set up logger
logger = script.get_logger()

# Function to get the Z position of an element
def get_element_elevation(element):
    """Get the vertical elevation of a Revit element"""
    # Try to get location directly
    loc = element.Location
    if loc and hasattr(loc, 'Point'):
        return loc.Point.Z
    
    # If that doesn't work, try to get bounding box
    try:
        bbox = element.get_BoundingBox(None)
        if bbox:
            return (bbox.Min.Z + bbox.Max.Z) / 2.0
    except:
        pass
        
    # If all else fails
    return None

# Ask user to select hangers
forms.alert('Select Hangers', title='Hangers Selection')
try:
    hanger_refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select hangers and click Finish")
    hangers = [doc.GetElement(ref.ElementId) for ref in hanger_refs]
except:
    forms.alert("No hangers selected. Script terminated.", title="Error")
    sys.exit()

# Check if any hangers were selected
if not hangers:
    forms.alert("No hangers selected. Script terminated.", title="Error")
    sys.exit()

# Ask user to select pipe
forms.alert('Select Pipe at Elevation', title='Pipe Selection')
try:
    pipe_ref = uidoc.Selection.PickObject(ObjectType.Element, "Select a pipe")
    pipe = doc.GetElement(pipe_ref.ElementId)
except:
    forms.alert("No pipe selected. Script terminated.", title="Error")
    sys.exit()

# Start transaction
t = Transaction(doc, "Adjust Hangers to Pipe Elevation")
t.Start()

try:
    # Get pipe elevation
    pipe_elevation = get_element_elevation(pipe)
    if not pipe_elevation:
        forms.alert("Could not determine pipe elevation. Script terminated.", title="Error")
        t.RollBack()
        sys.exit()
    
    # Track hangers with issues
    error_hangers = []
    successfully_moved = 0
    successfully_adjusted = 0
    
    # Process each hanger
    for hanger in hangers:
        # Get hanger elevation
        hanger_elevation = get_element_elevation(hanger)
        if not hanger_elevation:
            error_hangers.append(hanger.Id)
            continue
        
        # Calculate elevation difference in feet (Revit internal units)
        elevation_difference = pipe_elevation - hanger_elevation
        
        # If there's virtually no difference, skip this hanger
        if abs(elevation_difference) < 0.00001:  # Tolerance for floating-point precision
            successfully_moved += 1
            continue
            
        # Move the hanger to new elevation
        move_vector = XYZ(0, 0, elevation_difference)
        ElementTransformUtils.MoveElement(doc, hanger.Id, move_vector)
        successfully_moved += 1
        
        # Try to adjust the "Rod Extn Above" parameter
        # Convert elevation difference to inches for reporting
        difference_inches = elevation_difference * 12
        
        # Get the "Rod Extn Above" parameter
        rod_param = hanger.LookupParameter("Rod Extn Above")
        if rod_param and rod_param.StorageType == DB.StorageType.Double:
            current_value = rod_param.AsDouble()  # This is already in feet
            
            # Calculate new value (still in feet)
            new_value = current_value - elevation_difference
            
            # Check if new value would be negative
            if new_value >= 0:
                rod_param.Set(new_value)
                successfully_adjusted += 1
            else:
                # Add to error list
                error_hangers.append(hanger.Id)
        else:
            # Parameter not found or wrong type, add to error list
            error_hangers.append(hanger.Id)
    
    t.Commit()
    
    # Report results
    message = "Results:\n"
    message += "- Successfully moved: {} hangers\n".format(successfully_moved)
    message += "- Successfully adjusted rod extensions: {} hangers\n".format(successfully_adjusted)
    
    if error_hangers:
        error_ids = list(set([id.IntegerValue for id in error_hangers]))  # Remove duplicates
        message += "\nCould not adjust rod for {} hanger(s) with ID(s): \n".format(len(error_ids))
        message += "\n".join([str(id) for id in error_ids])
        forms.alert(message, title="Operation Complete with Issues")
    else:
        forms.alert(message + "\nAll hangers adjusted successfully!", title="Success")
        
except Exception as e:
    t.RollBack()
    logger.error(str(e))
    forms.alert("Error: " + str(e), title="Script Error")