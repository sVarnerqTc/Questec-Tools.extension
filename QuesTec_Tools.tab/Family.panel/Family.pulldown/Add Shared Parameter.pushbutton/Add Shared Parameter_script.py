import os
import tempfile
from datetime import datetime
from System.Collections.Generic import List

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

def get_existing_parameter_state(family_doc, family_param):
    """Return a human-readable description of current formula/value for a family parameter"""
    family_manager = family_doc.FamilyManager
    try:
        formula = family_param.Formula
    except Exception:
        formula = None
    if formula:
        return "Formula: {}".format(formula)

    current_type = family_manager.CurrentType
    if not current_type:
        return "Value: <no current family type available>"

    storage_type = family_param.StorageType
    if storage_type == DB.StorageType.String:
        value = current_type.AsString(family_param)
    elif storage_type == DB.StorageType.Integer:
        value = current_type.AsInteger(family_param)
    elif storage_type == DB.StorageType.Double:
        value = current_type.AsDouble(family_param)
    elif storage_type == DB.StorageType.ElementId:
        value = current_type.AsElementId(family_param)
        value = value.IntegerValue if value else None
    else:
        value = None

    return "Value: {}".format("<not set>" if value is None else value)

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

def get_preferred_fallback_dir():
    """Prefer the user's Downloads folder; fall back to temp if needed."""
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        downloads_dir = os.path.join(user_profile, "Downloads")
        if os.path.isdir(downloads_dir):
            return downloads_dir
    return tempfile.gettempdir()

def format_path_for_alert(path, max_segment_len=45):
    """Split a long path into shorter lines so dialogs can show the full value."""
    if not path:
        return ""

    parts = path.split(os.sep)
    formatted_parts = []
    for part in parts:
        if len(part) <= max_segment_len:
            formatted_parts.append(part)
            continue

        start = 0
        while start < len(part):
            formatted_parts.append(part[start:start + max_segment_len])
            start += max_segment_len

    return (os.sep + "\n").join(formatted_parts)

def ensure_family_editable_for_reload(project_doc, family):
    """Ensure the family element can be edited in a workshared project before reload."""
    if not project_doc.IsWorkshared:
        return True, None

    checkout_status = DB.WorksharingUtils.GetCheckoutStatus(project_doc, family.Id)
    if checkout_status == DB.CheckoutStatus.OwnedByCurrentUser:
        return True, None

    owner = None
    try:
        tooltip_info = DB.WorksharingUtils.GetWorksharingTooltipInfo(project_doc, family.Id)
        owner = tooltip_info.Owner if tooltip_info else None
    except Exception:
        owner = None

    status_label = str(checkout_status)
    owner_line = "\nCurrent owner: {}".format(owner) if owner else ""
    should_checkout = forms.alert(
        "This project is workshared and the family is not currently editable for reload."
        "\nStatus: {}{}\n\nDo you want to check it out now?".format(status_label, owner_line),
        yes=True,
        no=True,
        exitscript=False
    )

    if not should_checkout:
        return False, "Family reload cancelled: family was not checked out."

    try:
        element_ids = List[DB.ElementId]()
        element_ids.Add(family.Id)
        DB.WorksharingUtils.CheckoutElements(project_doc, element_ids)
    except Exception as ex:
        return False, "Failed to check out family for reload: {}".format(str(ex))

    updated_status = DB.WorksharingUtils.GetCheckoutStatus(project_doc, family.Id)
    if updated_status == DB.CheckoutStatus.OwnedByCurrentUser:
        return True, None

    return False, "Family is still not editable after checkout attempt. Status: {}".format(str(updated_status))

def try_save_with_fallback(family_doc, family_name):
    """Try Save first, then SaveAs to temp if needed."""
    save_note = None
    saved_path = None
    used_fallback = False

    try:
        saved_path = family_doc.PathName
        family_doc.Save()
        return True, saved_path, save_note, used_fallback
    except Exception as save_ex:
        # Fall back to a writable temporary location if the original path is locked/read-only.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in ("_", "-", " ") else "_" for c in family_name).strip()
        if not safe_name:
            safe_name = "Family"
        fallback_filename = "{}_{}.rfa".format(safe_name, timestamp)
        fallback_dir = get_preferred_fallback_dir()
        fallback_path = os.path.join(fallback_dir, fallback_filename)

        try:
            save_as_options = DB.SaveAsOptions()
            save_as_options.OverwriteExistingFile = True
            family_doc.SaveAs(fallback_path, save_as_options)
            display_path = format_path_for_alert(fallback_path)
            save_note = (
                "Could not save to original location. Saved a fallback copy to:\n{}\n\n"
                "Original save error: {}"
            ).format(display_path, str(save_ex))
            used_fallback = True
            return True, fallback_path, save_note, used_fallback
        except Exception as save_as_ex:
            save_note = (
                "Unable to save the family file.\n"
                "Save failed: {}\n"
                "Save As fallback failed: {}"
            ).format(str(save_ex), str(save_as_ex))
            return False, None, save_note, used_fallback

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
            current_state = get_existing_parameter_state(family_doc, existing_param)
            forms.alert(
                "Parameter '{}' already exists in this family as a {} parameter.\n{}".format(
                    existing_param.Definition.Name,
                    binding_label,
                    current_state
                )
            )

            should_modify = ask_yes_no(
                "Do you want to modify this parameter?"
            )
            if should_modify:
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
        
        save_note = None
        saved_path = None
        used_fallback = False
        should_save = forms.alert("Do you want to save the changes?", options=["Yes", "No"]) == "Yes"
        if should_save:
            _, saved_path, save_note, used_fallback = try_save_with_fallback(family_doc, family.Name)
        else:
            save_note = "Changes were not saved to disk (by user choice)."

        load_success = False
        load_error = None
        try:
            can_reload, checkout_error = ensure_family_editable_for_reload(revit.doc, family)
            if not can_reload:
                load_error = checkout_error
            else:
                # Reload directly from the edited family document so project updates even if disk save fails.
                load_options = FamilyLoadOptions()
                load_success = family_doc.LoadFamily(revit.doc, load_options)
        except Exception as load_ex:
            load_error = str(load_ex)
        finally:
            family_doc.Close(False)

        if load_success:
            if save_note:
                message = "Family reloaded successfully.\n\n{}".format(save_note)
                if used_fallback and saved_path:
                    message += "\n\nTemp save path:\n{}".format(format_path_for_alert(saved_path))
                forms.alert(message)
            else:
                forms.alert("Shared parameter added, family saved, and reloaded successfully.")
        else:
            message = "Failed to reload the modified family into the project."
            if load_error:
                message += "\n\nReload error: {}".format(load_error)
            if save_note:
                message += "\n\n{}".format(save_note)
            if used_fallback and saved_path:
                message += "\n\nTemp save path:\n{}".format(format_path_for_alert(saved_path))
            forms.alert(message)
            
    except Exception as ex:
        if t.HasStarted():
            t.RollBack()
        forms.alert("Failed to add shared parameter: {}".format(str(ex)))
        if family_doc:  # Close the document if it's still open after an error
            family_doc.Close(False)

if __name__ == "__main__":
    main()