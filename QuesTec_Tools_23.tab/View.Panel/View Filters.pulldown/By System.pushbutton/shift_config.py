"""
pyRevit shift-click script to remove all system type view filters
created by the main script.
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
        removed_count = 0
        
        # Get all view filters in the document
        collector = FilteredElementCollector(doc)
        all_filters = collector.OfClass(ParameterFilterElement).ToElements()
        
        filters_to_remove = []
        
        # Find filters that match our naming pattern
        for filter_element in all_filters:
            filter_name = filter_element.Name
            
            # Check if filter name starts with "Pipe -" or "Duct -" (our naming convention)
            if filter_name.startswith("Pipe - ") or filter_name.startswith("Duct - "):
                filters_to_remove.append(filter_element)
        
        # Collect filter IDs to delete
        filter_ids_to_delete = []
        
        # Remove filters from active view first
        for filter_element in filters_to_remove:
            try:
                filter_name = filter_element.Name
                filter_id = filter_element.Id
                
                # Remove filter from active view
                try:
                    active_view.RemoveFilter(filter_id)
                    #print("Removed filter from view: " + filter_name)
                except Exception as e:
                    print("Filter not applied to view: " + filter_name)
                
                # Add to deletion list
                filter_ids_to_delete.append(filter_id)
                
            except Exception as e:
                print("Error processing filter: " + str(e))
        
        # Delete all filter elements from the document at once
        #if filter_ids_to_delete:
            #try:
                #deleted_ids = doc.Delete(filter_ids_to_delete)
                #removed_count = len(deleted_ids)
                #print("Deleted " + str(removed_count) + " filters from document")
            #except Exception as e:
                #print("Error deleting filters from document: " + str(e))
        
        # Commit transaction
        transaction.Commit()
        
        #if removed_count > 0:
            #print("Successfully removed " + str(removed_count) + " system type view filters")
        #else:
            #print("No system type view filters found to remove")
        
    except Exception as e:
        transaction.RollBack()
        print("Error removing filters: " + str(e))
        raise

# Run the script
if __name__ == "__main__":
    remove_system_type_filters()