"""Turns off 'Use Annotation Scale' parameter for all families in the active view."""

__title__ = "Turn Off\nAnnotation Scale"
__author__ = "QuesTec"
__doc__ = "Finds all families in the active view with 'Use Annotation Scale' parameter and turns it off."

from Autodesk.Revit.DB import *
from pyrevit import revit, DB, forms

# Get the active document and view
doc = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

# Create collector for all family instances in the active view
collector = FilteredElementCollector(doc, active_view.Id).OfClass(FamilyInstance)

# Track results
modified_elements = []
elements_without_param = []
errors = []

# Begin transaction
with revit.Transaction("Turn Off Annotation Scale"):
    # Process each family instance
    for element in collector:
        try:
            # Get the "Use Annotation Scale" parameter
            param = element.LookupParameter("Use Annotation Scale")
            
            # Check if parameter exists
            if param:
                # Check if parameter is set to True (1)
                if param.AsInteger() == 1:
                    # Set parameter to False (0)
                    param.Set(0)
                    modified_elements.append(element)
            else:
                elements_without_param.append(element)
        except Exception as e:
            errors.append("Error processing element {}: {}".format(element.Id, str(e)))

# Prepare result message
result_msg = "{} elements modified.\n".format(len(modified_elements))
if elements_without_param:
    result_msg += "{} elements didn't have the parameter.\n".format(len(elements_without_param))
if errors:
    result_msg += "{} errors occurred.\n".format(len(errors))

# Show results
forms.alert(
    result_msg,
    title="Annotation Scale Parameter Turned Off",
    sub_msg="All visible elements with 'Use Annotation Scale' parameter have been updated."
)