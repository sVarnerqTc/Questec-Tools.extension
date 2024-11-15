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

def add_or_update_shared_parameter(family_doc, shared_param, value):
    """Add shared parameter to family and set its value, or update if already present"""
    family_manager = family_doc.FamilyManager
    existing_param = family_manager.get_Parameter(shared_param.GUID)
    
    if existing_param:
        # Parameter already exists, update its value
        family_manager.Set(existing_param, value)
    else:
        # Add new shared parameter
        param_binding = DB.InstanceBinding(DB.CategorySet())
        param_binding.Categories.Insert(DB.Category.GetCategory(family_doc, DB.BuiltInCategory.OST_GenericModel))
        
        family_param = family_manager.AddParameter(
            shared_param,
            DB.BuiltInParameterGroup.PG_DATA,
            False
        )
        
        if family_param:
            family_manager.Set(family_param, value)

def main():
    shared_param = prompt_for_shared_parameter()
    if not shared_param:
        return
    
    value = prompt_for_string_value()
    if value is None:
        return
    
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
        add_or_update_shared_parameter(family_doc, shared_param, value)
        t.Commit()
        family_doc.Save()
        
        # Reload the family into the active project and overwrite with parameter values
        load_options = FamilyLoadOptions()
        if revit.doc.LoadFamily(family_doc.PathName, load_options):
            forms.alert("Shared parameter added, family saved, and reloaded successfully.")
        else:
            forms.alert("Failed to reload the family into the project.")
    except Exception as ex:
        if t.HasStarted():
            t.RollBack()
        forms.alert("Failed to add shared parameter: {}".format(str(ex)))
    finally:
        family_doc.Close(False)

if __name__ == "__main__":
    main()