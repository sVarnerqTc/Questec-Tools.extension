from pyrevit import revit, DB, forms

class FamilyLoadOptions(DB.IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        source.Value = DB.FamilySource.Family
        overwriteParameterValues.Value = True
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
            display_name = "{} ({})".format(param.Name, group.Name)
            param_dict[display_name] = param
    
    selected_param = forms.SelectFromList.show(
        sorted(param_dict.keys()),
        title="Select Shared Parameter",
        multiselect=False
    )
    
    if selected_param:
        return param_dict[selected_param]
    return None

def prompt_for_family_instance():
    """Prompt user to select a family instance in the active view"""
    selected_element = revit.pick_element(message="Select a family instance in the active view")
    if selected_element and isinstance(selected_element, DB.FamilyInstance):
        return selected_element.Symbol.Family
    return None

def get_parameter_value(family_parameter, string_prompt=None):
    """Prompt user for parameter value based on parameter type"""
    storage_type = family_parameter.StorageType
    
    if storage_type == DB.StorageType.String:
        prompt_text = string_prompt or "Enter the text value for the parameter:"
        return forms.ask_for_string(
            prompt=prompt_text,
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

def ask_yes_no(message):
    """Ask a yes/no question and return True for yes"""
    return forms.alert(message, yes=True, no=True, exitscript=False)

def prompt_for_assignment_mode():
    """Prompt user for parameter assignment mode"""
    return forms.alert(
        "Select how to assign the parameter:",
        options=["Single Value", "Equation", "Lookup Table"]
    )

def prompt_for_equation_value():
    """Prompt user to enter an equation/formula"""
    return forms.ask_for_string(
        prompt="Enter equation for this parameter:",
        title="Parameter Equation"
    )

def format_formula_literal(value, storage_type):
    """Convert python value to a formula-safe literal"""
    if storage_type == DB.StorageType.String:
        escaped = str(value).replace('"', '\\"')
        return '"{}"'.format(escaped)
    if storage_type == DB.StorageType.Integer:
        return str(int(value))
    if storage_type == DB.StorageType.Double:
        return str(float(value))
    return str(value)

def select_lookup_table_name(family_doc):
    """Select a lookup table from the current family, or auto-pick if only one exists"""
    owner_family = family_doc.OwnerFamily
    if not owner_family:
        forms.alert("Could not access the owner family for lookup tables.")
        return None

    size_table_mgr = DB.FamilySizeTableManager.GetFamilySizeTableManager(family_doc, owner_family.Id)
    if not size_table_mgr:
        forms.alert("Could not access lookup tables for this family.")
        return None

    table_names = list(size_table_mgr.GetAllSizeTableNames())
    if not table_names:
        forms.alert("No lookup tables found in this family.")
        return None

    if len(table_names) == 1:
        return table_names[0]

    selected_table = forms.SelectFromList.show(
        sorted(table_names),
        title="Select Lookup Table",
        button_name="Use Selected Table",
        multiselect=False
    )
    return selected_table

def build_lookup_table_formula(family_doc, family_parameter):
    """Build a size_lookup formula using a matching column name"""
    table_name = select_lookup_table_name(family_doc)
    if not table_name:
        return None

    default_value = get_parameter_value(
        family_parameter,
        string_prompt="Enter the default value if not found:"
    )
    if default_value is None:
        return None

    column_name = family_parameter.Definition.Name
    key_expression = family_parameter.Definition.Name
    default_literal = format_formula_literal(default_value, family_parameter.StorageType)
    escaped_table_name = table_name.replace('"', '\\"')
    escaped_column_name = column_name.replace('"', '\\"')

    return 'size_lookup("{}", "{}", {}, {})'.format(
        escaped_table_name,
        escaped_column_name,
        default_literal,
        key_expression
    )

def ensure_current_type(family_manager):
    """Ensure the family has a current type before setting parameter values"""
    if family_manager.CurrentType:
        return True

    base_name = "Type 1"
    type_name = base_name
    suffix = 1
    while family_manager.get_Type(type_name):
        suffix += 1
        type_name = "{} {}".format(base_name, suffix)

    created_type = family_manager.NewType(type_name)
    return created_type is not None

def set_parameter_value(family_manager, family_parameter, value):
    """Set a family parameter value safely"""
    if not ensure_current_type(family_manager):
        forms.alert("Could not create or access a family type to assign parameter values.")
        return False

    family_manager.Set(family_parameter, value)
    return True

def set_parameter_formula(family_manager, family_parameter, formula):
    """Assign a family parameter formula safely"""
    if not ensure_current_type(family_manager):
        forms.alert("Could not create or access a family type to assign formulas.")
        return False

    family_manager.SetFormula(family_parameter, formula)
    return True

def make_parameter_instance(family_manager, family_parameter):
    """Convert a type parameter to an instance parameter"""
    try:
        family_manager.MakeInstance(family_parameter)
        return family_parameter.IsInstance
    except Exception as ex:
        forms.alert("Failed to convert parameter to instance: {}".format(str(ex)))
        return False

def apply_assignment_mode(family_doc, family_param):
    """Apply selected assignment mode to the given family parameter"""
    assignment_mode = prompt_for_assignment_mode()
    if assignment_mode == "Single Value":
        value = get_parameter_value(family_param)
        if value is not None:
            return set_parameter_value(family_doc.FamilyManager, family_param, value)
    elif assignment_mode == "Equation":
        equation = prompt_for_equation_value()
        if equation:
            return set_parameter_formula(family_doc.FamilyManager, family_param, equation)
    elif assignment_mode == "Lookup Table":
        lookup_formula = build_lookup_table_formula(family_doc, family_param)
        if lookup_formula:
            forms.alert("Generated lookup formula:\n{}".format(lookup_formula))
            return set_parameter_formula(family_doc.FamilyManager, family_param, lookup_formula)

    return False

def add_or_update_shared_parameter(family_doc, shared_param, param_group, is_instance, value=None):
    """Add shared parameter to family and set its value if provided"""
    family_manager = family_doc.FamilyManager
    existing_param = family_manager.get_Parameter(shared_param.GUID)
    
    if existing_param:
        # Parameter already exists
        if value is not None:
            set_parameter_value(family_manager, existing_param, value)
        return existing_param
    else:
        # Add new shared parameter
        family_param = family_manager.AddParameter(
            shared_param,
            param_group,
            is_instance
        )
        
        if family_param and value is not None:
            set_parameter_value(family_manager, family_param, value)
        return family_param

def main():
    family = prompt_for_family_instance()
    if not family:
        return
    
    family_doc = revit.doc.EditFamily(family)
    if not family_doc:
        forms.alert("Failed to open family document.")
        return

    shared_param = prompt_for_shared_parameter()
    if not shared_param:
        family_doc.Close(False)
        return

    family_manager = family_doc.FamilyManager
    existing_param = family_manager.get_Parameter(shared_param.GUID)
    changes_made = False

    t = DB.Transaction(family_doc, "Add Shared Parameter")
    try:
        if existing_param:
            binding_label = "Instance" if existing_param.IsInstance else "Type"
            forms.alert(
                "Parameter '{}' already exists in this family as a {} parameter.".format(
                    existing_param.Definition.Name,
                    binding_label
                )
            )

            if existing_param.IsInstance:
                should_change = ask_yes_no("Do you want to change the value/formula for this existing instance parameter?")
                if should_change:
                    t.Start()
                    changes_made = apply_assignment_mode(family_doc, existing_param)
            else:
                should_convert = ask_yes_no("This parameter is currently Type. Do you want to change it to Instance?")
                if should_convert:
                    t.Start()
                    converted = make_parameter_instance(family_manager, existing_param)
                    if converted:
                        changes_made = True
                        should_change = ask_yes_no("Parameter changed to Instance. Do you want to set value/formula now?")
                        if should_change:
                            changes_made = apply_assignment_mode(family_doc, existing_param) or changes_made
                else:
                    should_change_type = ask_yes_no("Do you want to change the value/formula for this existing Type parameter?")
                    if should_change_type:
                        t.Start()
                        changes_made = apply_assignment_mode(family_doc, existing_param)
        else:
            param_group = prompt_for_parameter_group()
            if not param_group:
                family_doc.Close(False)
                return

            is_instance = prompt_for_instance_or_type()

            t.Start()
            family_param = add_or_update_shared_parameter(family_doc, shared_param, param_group, is_instance)
            if family_param:
                changes_made = True
                changes_made = apply_assignment_mode(family_doc, family_param) or changes_made

        if t.HasStarted():
            if changes_made:
                t.Commit()
            else:
                t.RollBack()

        if not changes_made:
            forms.alert("No changes were made.")
            family_doc.Close(False)
            return
        
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