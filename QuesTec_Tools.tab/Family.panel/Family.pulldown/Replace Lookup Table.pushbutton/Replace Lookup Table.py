# -*- coding: utf-8 -*-
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from pyrevit import script
from pyrevit import revit
from pyrevit import forms
import csv
import os
import re

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[<>:"/\\|?*,]', '_', filename)
    # Remove multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    return sanitized.strip('_')

def ensure_directory_exists(path):
    """Ensure directory exists, create if not"""
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError as e:
            print("Error creating directory: {}".format(str(e)))
            script.exit()

def get_current_selection(uidoc):
    """Get currently selected family instance if any"""
    try:
        selected_ids = uidoc.Selection.GetElementIds()
        if (selected_ids.Count == 1):
            element = uidoc.Document.GetElement(selected_ids.First())
            if isinstance(element, FamilyInstance):
                return element.Symbol.Family
    except:
        pass
    return None

def prompt_for_family_instance():
    """Prompt user to select a family instance in the active view"""
    selected_element = revit.pick_element(message="Select a family instance in the active view")
    if selected_element and isinstance(selected_element, FamilyInstance):
        return selected_element.Symbol.Family
    return None\

def get_selected_families(uidoc):
    """Get all selected family instances"""
    families = []
    try:
        selected_ids = uidoc.Selection.GetElementIds()
        if selected_ids.Count > 0:
            for element_id in selected_ids:
                element = uidoc.Document.GetElement(element_id)
                if isinstance(element, FamilyInstance):
                    families.append(element.Symbol.Family)
    except:
        pass
    return families

def get_table_name_from_file(filename, family_name):
    """Extract table name from CSV filename"""
    # Remove family name and underscore from start
    prefix = family_name + "_"
    if filename.startswith(prefix):
        table_name = filename[len(prefix):]
    # Remove _Lookup_Table.csv suffix
    if table_name.endswith("_Lookup_Table.csv"):
        table_name = table_name[:-16]
    return table_name

# Get current document and UI application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

try:
    # First try to get currently selected family
    family = get_current_selection(uidoc)
    
    # If no valid selection, prompt user
    if not family:
        family = prompt_for_family_instance()
        
    if not family:
        print("Please select a valid family instance")
        script.exit()

    # Prompt for CSV file
    csv_path = forms.pick_file(file_ext='csv', 
                              title='Select Lookup Table CSV file',
                              multi_file=False)
    
    if not csv_path:
        print("No CSV file selected")
        script.exit()

    # Get table name from filename
    filename = os.path.basename(csv_path)
    table_name = get_table_name_from_file(filename, family.Name)
    
    # Create size table manager
    size_table_mgr = FamilySizeTableManager.GetFamilySizeTableManager(doc, family.Id)
    
    if not size_table_mgr:
        print("Could not get size table manager")
        script.exit()
        
    # Create error info object for import
    from System import String
    error_info = clr.Reference[String]()
    
    # Import the size table
    success = size_table_mgr.ImportSizeTable(table_name, csv_path, error_info)
    
    if not success:
        print("Failed to import table: {}".format(error_info.Value))
        script.exit()
        
    print("Successfully imported table: {}".format(table_name))

except Exception as e:
    print("Error: {}".format(str(e)))
    script.exit()