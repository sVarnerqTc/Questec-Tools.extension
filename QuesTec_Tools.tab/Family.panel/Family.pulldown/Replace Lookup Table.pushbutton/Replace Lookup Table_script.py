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
import shutil
import tempfile


class AlwaysOverwriteFamilyLoadOptions(IFamilyLoadOptions):
    """Force reload to overwrite family and parameter values in project."""
    def OnFamilyFound(self, family_in_use, overwrite_parameter_values):
        overwrite_parameter_values.Value = True
        return True

    def OnSharedFamilyFound(self, shared_family, family_in_use, source, overwrite_parameter_values):
        source.Value = FamilySource.Family
        overwrite_parameter_values.Value = True
        return True

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

def get_table_name_from_file(filename, family_name):
    """Extract table name from CSV filename"""
    table_name = os.path.splitext(filename)[0]

    # Support either raw or sanitized family-name prefixes.
    prefixes = [
        family_name + "_",
        sanitize_filename(family_name) + "_"
    ]
    for prefix in prefixes:
        if table_name.startswith(prefix):
            table_name = table_name[len(prefix):]
            break

    # Backward compatibility with older naming patterns.
    if table_name.endswith("_Lookup_Table"):
        table_name = table_name[:-13]

    return table_name

def import_size_table_with_target_name(size_table_mgr, family_doc, table_name, csv_path, error_info):
    """Import table using explicit table name where possible.

    Some Revit API versions only expose filename-based import overloads.
    In that case, import via a temporary CSV whose basename matches table_name.
    """
    # Preferred overload in many Revit versions.
    try:
        return size_table_mgr.ImportSizeTable(table_name, csv_path, error_info), "ImportSizeTable(table_name, csv_path, error_info)"
    except TypeError:
        pass

    # Alternate overload used by some environments.
    try:
        return size_table_mgr.ImportSizeTable(family_doc, table_name, csv_path, error_info), "ImportSizeTable(doc, table_name, csv_path, error_info)"
    except TypeError:
        pass

    # Filename-based fallback: ensure filename equals target table name.
    temp_dir = None
    import_path = csv_path
    try:
        csv_base_name = os.path.splitext(os.path.basename(csv_path))[0]
        if csv_base_name != table_name:
            safe_table_name = sanitize_filename(table_name)
            if safe_table_name != table_name:
                raise Exception(
                    "This Revit version requires filename-based lookup table import, "
                    "but table name '{}' cannot be represented exactly as a filename.".format(table_name)
                )

            temp_dir = tempfile.mkdtemp(prefix="qt_lookup_")
            import_path = os.path.join(temp_dir, "{}.csv".format(table_name))
            shutil.copyfile(csv_path, import_path)

        # Most common implicit-name overload.
        try:
            return size_table_mgr.ImportSizeTable(family_doc, import_path, error_info), "ImportSizeTable(doc, csv_path, error_info)"
        except TypeError:
            # Some versions omit the document parameter.
            return size_table_mgr.ImportSizeTable(import_path, error_info), "ImportSizeTable(csv_path, error_info)"
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, True)

def safe_close_document(revit_doc, save_changes=False):
    """Close a document only when it is still valid."""
    try:
        if revit_doc and revit_doc.IsValidObject:
            revit_doc.Close(save_changes)
    except Exception as close_error:
        print("Warning: could not close family document cleanly: {}".format(str(close_error)))

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

    family_name = family.Name

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
    if not table_name:
        print("Could not determine lookup table name from filename: {}".format(filename))
        script.exit()
    
    # Open family document for editing
    family_doc = doc.EditFamily(family)
    
    if not family_doc:
        print("Could not open family document: {}".format(family_name))
        script.exit()
    
    try:
        # Create size table manager within family document context
        size_table_mgr = FamilySizeTableManager.GetFamilySizeTableManager(family_doc, family_doc.OwnerFamily.Id)
        
        if not size_table_mgr:
            print("Could not get size table manager")
            safe_close_document(family_doc, False)
            script.exit()

        existing_table_names = list(size_table_mgr.GetAllSizeTableNames())
        if not existing_table_names:
            print("No lookup tables found in family: {}".format(family_name))
            safe_close_document(family_doc, False)
            script.exit()

        if table_name not in existing_table_names:
            print("Filename-derived table '{}' was not found in family.".format(table_name))
            if len(existing_table_names) == 1:
                table_name = existing_table_names[0]
                print("Using only existing table in family: {}".format(table_name))
            else:
                selected_table = forms.SelectFromList.show(
                    sorted(existing_table_names),
                    title="Select Lookup Table to Replace",
                    button_name="Replace Table",
                    multiselect=False
                )
                if not selected_table:
                    print("No lookup table selected. Operation canceled.")
                    safe_close_document(family_doc, False)
                    script.exit()
                table_name = selected_table
            
        # Create Revit error-info object required by ImportSizeTable.
        error_info = FamilySizeTableErrorInfo()
        
        success, import_method = import_size_table_with_target_name(
            size_table_mgr,
            family_doc,
            table_name,
            csv_path,
            error_info
        )
        
        if not success:
            print("Failed to import table: {}".format(error_info))
            safe_close_document(family_doc, False)
            script.exit()

        post_import_table_names = list(size_table_mgr.GetAllSizeTableNames())
        if table_name not in post_import_table_names:
            print("Import completed but target table '{}' was not found afterward.".format(table_name))
            print("Existing tables now: {}".format(", ".join(sorted(post_import_table_names))))
            safe_close_document(family_doc, False)
            script.exit()
            
        print("Successfully imported table: {}".format(table_name))
        print("Import overload used: {}".format(import_method))

        # Persist the imported table to the family file before optional reload.
        family_doc.Save()

        reload_family = forms.alert(
            "Lookup table imported successfully. Reload this family into the current project now?",
            yes=True,
            no=True,
            exitscript=False
        )

        if reload_family:
            load_options = AlwaysOverwriteFamilyLoadOptions()
            loaded_family = family_doc.LoadFamily(doc, load_options)
            if loaded_family:
                print("Family reloaded into project: {}".format(family_name))
            else:
                print("Family reload was not completed.")
        else:
            print("Family was not reloaded into project.")
        
        # Already saved above; close without another save attempt.
        safe_close_document(family_doc, False)
        
    except Exception as e:
        print("Error during import: {}".format(str(e)))
        safe_close_document(family_doc, False)
        script.exit()

except Exception as e:
    print("Error: {}".format(str(e)))
    script.exit()