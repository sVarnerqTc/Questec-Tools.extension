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
    return None

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

def select_folder():
    """Prompt user to select a folder for saving files"""
    default_path = os.path.expanduser("~\\Desktop")
    selected_folder = forms.pick_folder(title="Select Folder to Save Lookup Tables", 
                                        default=default_path)
    return selected_folder

# Get current document and UI application
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

try:
    # Get selected families
    families = get_selected_families(uidoc)
    
    if not families:
        # If no selection, prompt user
        family = prompt_for_family_instance()
        if family:
            families = [family]
            
    if not families:
        print("Please select at least one family instance")
        script.exit()
    
    # Prompt user to select a folder
    output_folder = select_folder()
    if not output_folder:
        print("No folder selected. Operation canceled.")
        script.exit()
        
    # Ensure selected folder exists
    ensure_directory_exists(output_folder)
    
    # Process each family
    for family in families:
        try:
            # Get family document
            family_doc = doc.EditFamily(family)
            
            if not family_doc:
                print("Could not open family document: {}".format(family.Name))
                continue
                
            print("Processing family: {}".format(family.Name))
            
            # Create sanitized filename
            safe_filename = sanitize_filename(family.Name)
            
            # Create family size table manager
            size_table_mgr = FamilySizeTableManager.GetFamilySizeTableManager(doc, family.Id)
            
            if not size_table_mgr:
                print("Could not get size table manager for: {}".format(family.Name))
                family_doc.Close(False)
                continue
            
            # Get all table names
            table_names = size_table_mgr.GetAllSizeTableNames()
            
            if not table_names or table_names.Count == 0:
                print("No lookup tables found in family: {}".format(family.Name))
                family_doc.Close(False)
                continue
            
            # Export each size table
            for table_name in table_names:
                table_path = os.path.join(output_folder, "{}_{}.csv".format(
                    safe_filename,
                    sanitize_filename(table_name)
                ))
                size_table_mgr.ExportSizeTable(table_name, table_path)
                print("Exported table '{}' from family '{}'".format(table_name, family.Name))
                
            family_doc.Close(False)
            
        except Exception as e:
            print("Error processing family {}: {}".format(family.Name, str(e)))
            if family_doc:
                family_doc.Close(False)
            continue
            
    print("Processing complete - Files saved to: {}".format(output_folder))
    script.exit()
    
except Exception as e:
    print("Error: {}".format(str(e)))
    script.exit()