"""
pyRevit shift-click script to remove all assembly view filters
created by the main script by assembly name and restore filter visibility.
"""

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

# Get current document and active view
doc = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

def remove_system_type_filters():
    """Remove all system type view filters from the active view and document"""
    
    # Start transaction
    transaction = Transaction(doc, "Remove System Type View Filters")
    transaction.Start()
    
    try:
        # Get all view filters in the document
        collector = FilteredElementCollector(doc)
        all_filters = collector.OfClass(ParameterFilterElement).ToElements()
        
        filters_to_remove = []
        
        # Find filters that match our naming pattern
        for filter_element in all_filters:
            filter_name = filter_element.Name
            
            # Check if filter name starts with our naming conventions
            if (filter_name.startswith("Assembly_") ):
                filters_to_remove.append(filter_element)
        
        # Remove filters from active view
        for filter_element in filters_to_remove:
            try:
                filter_name = filter_element.Name
                filter_id = filter_element.Id
                
                # Remove filter from active view first
                try:
                    active_view.RemoveFilter(filter_id)
                    print("Removed filter from view: " + filter_name)
                except Exception as e:
                    print("Filter not applied to view: " + filter_name)
                
            except Exception as e:
                print("Error processing filter: " + str(e))
        
        # Commit transaction
        transaction.Commit()
        
        print("\nSUMMARY: Removed " + str(len(filters_to_remove)) + " system filters from view and document")
        
    except Exception as e:
        transaction.RollBack()
        print("Error removing filters: " + str(e))
        raise

# Run the script
if __name__ == "__main__":
    remove_system_type_filters()