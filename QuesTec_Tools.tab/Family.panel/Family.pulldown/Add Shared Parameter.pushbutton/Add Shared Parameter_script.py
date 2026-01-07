from pyrevit import revit, DB, forms

class FamilyLoadOptions(DB.IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, overwriteParameterValues):
        overwriteParameterValues = True
        return True

def prompt_for_shared_parameter():
    """Prompt user to select a shared parameter"""
    shared_params_file = revit.doc.Application.OpenSharedParameterFile()
    if not shared_params_file:
        forms.alert("No shared parameters file found.")
        return None
    
    param_dict = {}
    for group in shared_params_file.Groups:
        for param in group.Definitions:
            param_dict[param.Name] = param
    
    selected_param = forms.SelectFromList.show(
        sorted(param_dict.keys()),
        title="Select Shared Parameter",
        multiselect=False
    )
    
    if selected_param:
        return param_dict[selected_param]
    return None

def prompt_for_string_value():
    """Prompt user to enter a string value"""
    return forms.ask_for_string(
        prompt="Enter the value for the shared parameter:",
        title="Shared Parameter Value"
    )

def prompt_for_family_instance():
    """Prompt user to select a family instance in the active view"""
    selected_element = revit.pick_element(message="Select a family instance in the active view")
    if selected_element and isinstance(selected_element, DB.FamilyInstance):
        return selected_element.Symbol.Family
    return None

def get_parameter_value(definition):
    """Prompt user for parameter value based on parameter type"""
    storage_type = definition.GetDataType()
    
    if storage_type == DB.StorageType.String:
        return forms.ask_for_string(
            prompt="Enter the text value for the parameter:",
            title="Parameter Value"
        )
    elif storage_type == DB.StorageType.Integer:
        value = forms.ask_for_string(
            prompt="Enter the integer value:",
            title="Parameter Value"
        )
        try:
            return int(value)
        except (ValueError, TypeError):
            forms.alert("Invalid integer value entered.")
            return None
    elif storage_type == DB.StorageType.Double:
        value = forms.ask_for_string(
            prompt="Enter the numeric value:",
            title="Parameter Value"
        )
        try:
            return float(value)
        except (ValueError, TypeError):
            forms.alert("Invalid numeric value entered.")
            return None
    elif storage_type == DB.StorageType.ElementId:
        forms.alert("ElementId parameter type is not supported for direct value assignment.")
        return None
    else:
        forms.alert("Parameter type not supported for value assignment.")
        return None

def prompt_for_parameter_group():
    """Prompt user to select a parameter group"""
    param_groups = [
        ("PG_ANALYSIS_RESULTS", "Analysis Results"),
        ("PG_DATA", "Data"),
        ("PG_GEOMETRY", "Geometry"),
        ("PG_CONSTRUCTION", "Construction"),
        ("PG_GRAPHICS", "Graphics"),
        ("PG_IDENTITY_DATA", "Identity Data"),
        ("PG_MATERIALS", "Materials"),
        ("PG_MECHANICAL", "Mechanical"),
        ("PG_ELECTRICAL", "Electrical"),
        ("PG_PLUMBING", "Plumbing"),
        ("PG_STRUCTURAL", "Structural"),
        ("PG_TEXT", "Text"),
        ("PG_OTHER", "Other")
    ]
    
    selected = forms.SelectFromList.show(
        [group[1] for group in param_groups],
        title="Select Parameter Group",
        multiselect=False
    )
    
    if selected:
        # Find the matching BuiltInParameterGroup
        group_name = next(group[0] for group in param_groups if group[1] == selected)
        return getattr(DB.BuiltInParameterGroup, group_name)
    return None

def prompt_for_instance_or_type():
    """Prompt user to choose between instance and type parameter"""
    result = forms.alert("Select parameter binding type:", 
                        options=["Instance", "Type"])
    return result == "Instance"

def add_or_update_shared_parameter(family_doc, shared_param, param_group, is_instance, value=None):
    """Add shared parameter to family and set its value if provided"""
    family_manager = family_doc.FamilyManager
    existing_param = family_manager.get_Parameter(shared_param.GUID)
    
    if existing_param:
        # Parameter already exists
        if value is not None:
            family_manager.Set(existing_param, value)
    else:
        # Add new shared parameter
        family_param = family_manager.AddParameter(
            shared_param,
            param_group,
            is_instance
        )
        
        if family_param and value is not None:
            family_manager.Set(family_param, value)

def main():
    shared_param = prompt_for_shared_parameter()
    if not shared_param:
        return
    
    # Debug the storage type of the shared parameter
    storage_type = shared_param.GetDataType()
    forms.alert("Selected parameter storage type: {}".format(storage_type))
    
    param_group = prompt_for_parameter_group()
    if not param_group:
        return
        
    is_instance = prompt_for_instance_or_type()
    
    family = prompt_for_family_instance()
    if not family:
        return
    
    family_doc = revit.doc.EditFamily(family)
    if not family_doc:
        forms.alert("Failed to open family document.")
        return
    
    t = DB.Transaction(family_doc, "Add Shared Parameter")
    try:
        t.Start()
        # Add parameter with selected group and binding
        add_or_update_shared_parameter(family_doc, shared_param, param_group, is_instance)
        
        # Then prompt for value based on parameter type
        value = get_parameter_value(shared_param)
        if value is not None:
            add_or_update_shared_parameter(family_doc, shared_param, param_group, is_instance, value)
            
        t.Commit()
        
        # Add debug to check the added parameter
        added_param = family_doc.FamilyManager.get_Parameter(shared_param.GUID)
        if added_param:
            forms.alert("Added parameter definition name: {}\nStorage type: {}".format(
                added_param.Definition.Name,
                added_param.StorageType
            ))
        
        # Prompt user to save
        should_save = forms.alert("Do you want to save the changes?", options=["Yes", "No"]) == "Yes"
        if should_save:
            # Save the family document and get the file path
            family_path = family_doc.PathName
            family_doc.Save()
            family_doc.Close(False)  # Close the document after saving
            
            # Create new transaction in the project document
            with DB.Transaction(revit.doc, "Load Modified Family") as t2:
                t2.Start()
                load_options = FamilyLoadOptions()
                if revit.doc.LoadFamily(family_path, load_options):
                    forms.alert("Shared parameter added, family saved, and reloaded successfully.")
                else:
                    forms.alert("Failed to reload the family into the project.")
                t2.Commit()
        else:
            forms.alert("Changes were not saved.")
            family_doc.Close(False)  # Close without saving if user chose not to save
            
    except Exception as ex:
        if t.HasStarted():
            t.RollBack()
        forms.alert("Failed to add shared parameter: {}".format(str(ex)))
        if family_doc:  # Close the document if it's still open after an error
            family_doc.Close(False)

if __name__ == "__main__":
    main()