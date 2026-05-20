"""
Create view filters for all STRATUS Package Names in the active view.
Searches the active view for all elements with the STRATUS Package Name parameter
and creates/applies a filter for each unique package name found.
Shift-click to remove package filters from the view (but not from the project).
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from System.Collections.Generic import List

# Get current document and active view
doc = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView
uidoc = __revit__.ActiveUIDocument

PACKAGE_PARAM_NAME = "STRATUS Package Name"

def to_element_id_list(element_ids):
    """Convert a Python sequence of ElementId values to a .NET List[ElementId]."""
    element_id_list = List[ElementId]()
    for element_id in element_ids:
        element_id_list.Add(element_id)
    return element_id_list

def build_string_equals_filter(parameter_id, value):
    """Build an equals filter for a string parameter value."""
    provider = ParameterValueProvider(parameter_id)
    evaluator = FilterStringEquals()

    # Revit API signatures differ by version (3 args vs 4 args with case-sensitivity).
    try:
        rule = FilterStringRule(provider, evaluator, value, False)
    except Exception:
        rule = FilterStringRule(provider, evaluator, value)

    return ElementParameterFilter(rule)

def collect_package_data_from_view():
    """Collect package names, categories, and a valid STRATUS package parameter id from the active view."""
    package_names = set()
    category_ids_with_param = set()
    package_param_id = None

    collector = FilteredElementCollector(doc, active_view.Id)
    elements = collector.WhereElementIsNotElementType().ToElements()

    for element in elements:
        try:
            package_param = element.LookupParameter(PACKAGE_PARAM_NAME)
            if not package_param:
                continue

            if package_param_id is None:
                package_param_id = package_param.Id

            if element.Category:
                category_ids_with_param.add(element.Category.Id)

            package_value = ""
            if package_param.StorageType == StorageType.String and package_param.HasValue:
                package_value = package_param.AsString() or ""

            package_value = package_value.strip()
            if package_value:
                package_names.add(package_value)

        except Exception:
            continue

    return sorted(list(package_names)), list(category_ids_with_param), package_param_id

def upsert_package_filter(filter_name, package_value, category_ids, package_param_id, existing_filters):
    """Create or update a package filter to match the current categories and package value."""
    categories = to_element_id_list(category_ids)
    param_filter = build_string_equals_filter(package_param_id, package_value)

    if filter_name in existing_filters:
        view_filter = existing_filters[filter_name]
        view_filter.SetCategories(categories)
        view_filter.SetElementFilter(param_filter)
        return view_filter

    return ParameterFilterElement.Create(doc, filter_name, categories, param_filter)

def main():
    """Main function to create filters and apply to active view"""
    
    # Start transaction
    transaction = Transaction(doc, "Create Package Name View Filters")
    transaction.Start()
    
    try:
        # Discover package data only from elements that actually expose the STRATUS Package Name parameter.
        package_names, category_ids, package_param_id = collect_package_data_from_view()

        if not category_ids or package_param_id is None:
            transaction.RollBack()
            return
        
        created_filters = []
        
        # Get existing filters in the document
        existing_filters = {}
        collector = FilteredElementCollector(doc)
        all_filters = collector.OfClass(ParameterFilterElement).ToElements()
        for filter_element in all_filters:
            existing_filters[filter_element.Name] = filter_element
        
        # Create or find filters for each package name
        for package_name in package_names:
            filter_name = "Package_" + package_name
            try:
                view_filter = upsert_package_filter(filter_name, package_name, category_ids, package_param_id, existing_filters)
                
                if view_filter:
                    created_filters.append((view_filter, package_name))
            except Exception:
                pass
        
        # Create filter for blank package names
        blank_filter_name = "Package_(Blank)"
        try:
            view_filter = upsert_package_filter(blank_filter_name, "", category_ids, package_param_id, existing_filters)
            
            if view_filter:
                created_filters.append((view_filter, "(Blank)"))
        except Exception:
            pass
        
        # Apply all filters to the active view
        for view_filter, package_name in created_filters:
            try:
                # Check if filter is already applied to avoid errors
                try:
                    active_view.AddFilter(view_filter.Id)
                except Exception:
                    pass
                
                # Set filter visibility to True (show all package filters)
                active_view.SetFilterVisibility(view_filter.Id, True)
                    
            except Exception:
                pass
        
        # Commit transaction
        transaction.Commit()
        
    except Exception:
        transaction.RollBack()
        raise

# Run the script
if __name__ == "__main__":
    main()
