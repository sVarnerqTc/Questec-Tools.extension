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

def get_package_names_from_view():
    """Get all unique STRATUS Package Name values from elements in the active view"""
    package_names = set()
    
    # Get all elements in the active view
    collector = FilteredElementCollector(doc, active_view.Id)
    elements = collector.WhereElementIsNotElementType().ToElements()
    
    for element in elements:
        try:
            # Try to get STRATUS Package Name parameter
            package_name = None
            
            # Method 1: Try by parameter name
            try:
                for param in element.Parameters:
                    param_name = param.Definition.Name
                    if param_name == "STRATUS Package Name" and param.HasValue:
                        if param.StorageType == StorageType.String:
                            package_name = param.AsString()
                            break
            except Exception as e:
                pass
            
            if package_name and package_name.strip():
                package_names.add(package_name)
                
        except Exception as e:
            continue
    
    return sorted(list(package_names))

def get_all_categories_in_view():
    """Get all categories of elements in the active view"""
    categories = set()
    
    # Get all elements in the active view
    collector = FilteredElementCollector(doc, active_view.Id)
    elements = collector.WhereElementIsNotElementType().ToElements()
    
    for element in elements:
        try:
            if element.Category:
                categories.add(element.Category.Id)
        except Exception as e:
            continue
    
    return list(categories)

def create_package_filter(filter_name, package_name, category_ids):
    """Create a view filter for elements with a specific STRATUS Package Name value"""
    
    # Create filter categories
    categories = List[ElementId]()
    for category_id in category_ids:
        categories.Add(category_id)
    
    # Get a sample element to find the parameter definition for STRATUS Package Name
    collector = FilteredElementCollector(doc, active_view.Id)
    sample_element = collector.WhereElementIsNotElementType().FirstElement()
    
    package_param_def = None
    if sample_element:
        for param in sample_element.Parameters:
            if param.Definition.Name == "STRATUS Package Name":
                package_param_def = param.Definition
                break
    
    if package_param_def:
        provider = ParameterValueProvider(package_param_def.Id)
        evaluator = FilterStringEquals()
        rule_value = package_name
        rule = FilterStringRule(provider, evaluator, rule_value)
        
        param_filter = ElementParameterFilter(rule)
        
        # Create the view filter
        view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
        
        return view_filter
    
    return None

def create_blank_package_filter(filter_name, category_ids):
    """Create a view filter for elements with blank/empty STRATUS Package Name"""
    
    # Create filter categories
    categories = List[ElementId]()
    for category_id in category_ids:
        categories.Add(category_id)
    
    # Get a sample element to find the parameter definition
    collector = FilteredElementCollector(doc, active_view.Id)
    sample_element = collector.WhereElementIsNotElementType().FirstElement()
    
    package_param_def = None
    if sample_element:
        for param in sample_element.Parameters:
            if param.Definition.Name == "STRATUS Package Name":
                package_param_def = param.Definition
                break
    
    if package_param_def:
        provider = ParameterValueProvider(package_param_def.Id)
        evaluator = FilterStringEquals()
        rule_value = ""  # Empty string for blank values
        rule = FilterStringRule(provider, evaluator, rule_value)
        
        param_filter = ElementParameterFilter(rule)
        
        # Create the view filter
        view_filter = ParameterFilterElement.Create(doc, filter_name, categories, param_filter)
        
        return view_filter
    
    return None

def main():
    """Main function to create filters and apply to active view"""
    
    # Start transaction
    transaction = Transaction(doc, "Create Package Name View Filters")
    transaction.Start()
    
    try:
        # Get all unique package names from the active view
        package_names = get_package_names_from_view()
        
        # Get all categories in the view that have elements
        category_ids = get_all_categories_in_view()
        
        if not category_ids:
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
                if filter_name in existing_filters:
                    # Use existing filter
                    view_filter = existing_filters[filter_name]
                else:
                    # Create new filter
                    view_filter = create_package_filter(filter_name, package_name, category_ids)
                
                if view_filter:
                    created_filters.append((view_filter, package_name))
            except Exception as e:
                pass
        
        # Create filter for blank package names
        blank_filter_name = "Package_(Blank)"
        try:
            if blank_filter_name in existing_filters:
                view_filter = existing_filters[blank_filter_name]
            else:
                view_filter = create_blank_package_filter(blank_filter_name, category_ids)
            
            if view_filter:
                created_filters.append((view_filter, "(Blank)"))
        except Exception as e:
            pass
        
        # Apply all filters to the active view
        for view_filter, package_name in created_filters:
            try:
                # Check if filter is already applied to avoid errors
                try:
                    active_view.AddFilter(view_filter.Id)
                except Exception as add_error:
                    pass
                
                # Set filter visibility to True (show all package filters)
                active_view.SetFilterVisibility(view_filter.Id, True)
                    
            except Exception as e:
                pass
        
        # Commit transaction
        transaction.Commit()
        
    except Exception as e:
        transaction.RollBack()
        raise

# Run the script
if __name__ == "__main__":
    main()
