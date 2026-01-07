# -*- coding: utf-8 -*-
"""Export selected elements to CSV with coordinates and parameters"""

__title__ = "CSV Export"
__author__ = "QuesTec Tools"

import csv
import os
from pyrevit import revit, DB, UI, forms
from pyrevit.framework import List


def get_element_location(element):
    """Get the X, Y coordinates of an element in feet based on project internal origin"""
    location = element.Location
    
    if hasattr(location, 'Point'):
        # For point-based elements (coordinates are already in project internal origin)
        point = location.Point
        return point.X, point.Y
    elif hasattr(location, 'Curve'):
        # For curve-based elements, get midpoint
        curve = location.Curve
        midpoint = curve.Evaluate(0.5, True)
        return midpoint.X, midpoint.Y
    else:
        # For other elements, try to get bounding box center using project internal origin
        # Use None as view parameter to get coordinates in project coordinate system
        bbox = element.get_BoundingBox(None)
        if bbox:
            center_x = (bbox.Min.X + bbox.Max.X) / 2
            center_y = (bbox.Min.Y + bbox.Max.Y) / 2
            return center_x, center_y
    
    return 0.0, 0.0


def get_parameter_value(element, param_name):
    """Get parameter value from element"""
    param = element.LookupParameter(param_name)
    if param and param.HasValue:
        if param.StorageType == DB.StorageType.String:
            return param.AsString() or ""
        elif param.StorageType == DB.StorageType.Integer:
            return str(param.AsInteger())
        elif param.StorageType == DB.StorageType.Double:
            return str(param.AsDouble())
        elif param.StorageType == DB.StorageType.ElementId:
            return str(param.AsElementId().IntegerValue)
    return ""


def main():
    # Get current selection
    selection = revit.get_selection()
    
    # If no selection, prompt user to select elements
    if not selection.elements:
        try:
            reference_list = revit.pick_objects()
            if not reference_list:
                forms.alert("No elements selected. Operation cancelled.", exitscript=True)
            
            # Get elements from references
            elements = []
            for ref in reference_list:
                element = revit.doc.GetElement(ref.ElementId)
                if element:
                    elements.append(element)
        except:
            forms.alert("Selection cancelled.", exitscript=True)
    else:
        elements = selection.elements
    
    if not elements:
        forms.alert("No valid elements found.", exitscript=True)
    
    # Prompt for file path and name
    folder_path = forms.pick_folder()
    if not folder_path:
        forms.alert("No folder selected. Operation cancelled.", exitscript=True)
    
    file_name = forms.ask_for_string(
        default="export",
        prompt="Enter the export file name (without .csv extension):",
        title="Export File Name"
    )
    
    if not file_name:
        forms.alert("No file name provided. Operation cancelled.", exitscript=True)
    
    # Ensure .csv extension
    if not file_name.lower().endswith('.csv'):
        file_name = file_name + '.csv'
    
    # Create full file path
    full_path = os.path.join(folder_path, file_name)
    
    # Prepare CSV data
    csv_data = []
    
    # Add header row
    csv_data.append(['Name', 'X', 'Y', 'Z', 'Desc'])
    
    # Process each element
    for element in elements:
        # Get Mark parameter
        mark = get_parameter_value(element, 'Mark')
        
        # Get coordinates in feet
        x_coord, y_coord = get_element_location(element)
        
        # Z column is always 0
        z_coord = 0
        
        # Get Comments parameter
        comments = get_parameter_value(element, 'Comments')
        
        # Add row to CSV data
        csv_data.append([mark, str(x_coord), str(y_coord), str(z_coord), comments])
    
    # Write CSV file
    try:
        with open(full_path, 'wb') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerows(csv_data)
        
        forms.alert("CSV file exported successfully to: {}".format(full_path), title="Export Complete")
        
    except Exception as e:
        forms.alert("Error writing CSV file: {}".format(str(e)), title="Export Error")


if __name__ == '__main__':
    main()