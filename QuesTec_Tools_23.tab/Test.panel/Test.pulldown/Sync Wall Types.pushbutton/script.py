from Autodesk.Revit.DB import FilteredElementCollector, WallType, Transaction, RevitLinkInstance
from Autodesk.Revit.UI import UIApplication

# Access the current document
doc = __revit__.ActiveUIDocument.Document

# Get the linked document
linked_docs = [link.GetLinkDocument() for link in FilteredElementCollector(doc).OfClass(RevitLinkInstance) if link.GetLinkDocument()]
linked_doc = linked_docs[0]  # Assuming only one linked document for simplicity

# Collect wall types from the linked document
linked_wall_types = FilteredElementCollector(linked_doc).OfClass(WallType).ToElements()

# Collect wall types from the current document
host_wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()
host_wall_type_names = {wt.Name: wt for wt in host_wall_types}

# Start a transaction
t = Transaction(doc, "Map Wall Types")
t.Start()

for linked_wall_type in linked_wall_types:
    # Debugging: Print the type of linked_wall_type
    print("Type of linked_wall_type:", type(linked_wall_type))
    
    linked_name = linked_wall_type.Name

    # Check if the wall type already exists in the host document
    if linked_name in host_wall_type_names:
        print("Wall type '{}' already exists in host document.".format(linked_name))
    else:
        # Create a new wall type in the host document
        new_wall_type = host_wall_types[0].Duplicate(linked_name)  # Duplicating an existing type
        new_wall_type.SetCompoundStructure(linked_wall_type.GetCompoundStructure())
        print("Created wall type '{}' in host document.".format(linked_name))

t.Commit()
