import re
import json
import uuid
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.ExtensibleStorage import *
from pyrevit import forms, revit, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# Define schema for storing mark data
schema_guid = uuid.UUID("B1A37F5E-96E4-40FD-9123-0536D60832C2")  # Consistent GUID

def get_or_create_schema():
    # Try to find existing schema
    schema = Schema.Lookup(schema_guid)
    
    # Create schema if it doesn't exist
    if schema is None:
        schema_builder = SchemaBuilder(schema_guid)
        schema_builder.SetSchemaName("HMarkTrackerSchema")
        schema_builder.SetDocumentation("Stores H-Marks for elements")
        
        # Create field to store the dictionary as serialized string
        field_builder = schema_builder.AddSimpleField("HMarks", str)
        field_builder.SetDocumentation("JSON string of element ID to mark mapping")
        
        # Set read/write access
        schema_builder.SetReadAccessLevel(AccessLevel.Public)
        schema_builder.SetWriteAccessLevel(AccessLevel.Public)
        
        schema = schema_builder.Finish()
    
    return schema

# Load saved marks from project
def load_saved_marks():
    try:
        schema = get_or_create_schema()
        # Store data on Project Information element
        project_info = doc.ProjectInformation
        
        if not Entity.Exists(project_info, schema):
            return {}
            
        entity = project_info.GetEntity(schema)
        json_string = entity.Get[str]("HMarks")
        
        if json_string:
            return json.loads(json_string)
        return {}
    except Exception as e:
        output.print_md(f"**Error loading saved marks: {str(e)}**")
        return {}

# Save marks to project
def save_marks(saved_marks):
    try:
        with revit.Transaction("Save H-Marks"):
            schema = get_or_create_schema()
            
            # Convert dict to JSON string
            json_string = json.dumps(saved_marks)
            
            # Store on Project Information
            project_info = doc.ProjectInformation
            entity = Entity(schema)
            entity.Set("HMarks", json_string)
            project_info.SetEntity(entity)
            
        output.print_md("**Marks saved to Revit project**")
    except Exception as e:
        output.print_md(f"**Error saving marks: {str(e)}**")

# Get selected elements
selected_ids = uidoc.Selection.GetElementIds()
selected_elements = [doc.GetElement(id) for id in selected_ids]

if not selected_elements:
    forms.alert('No elements selected. Please select elements to renumber.', title='No Selection')
    script.exit()

# Check if selected elements have Mark parameter
elements_to_process = []
for elem in selected_elements:
    mark_param = elem.LookupParameter('Mark')
    if mark_param:
        elements_to_process.append((elem, mark_param))

if not elements_to_process:
    forms.alert('None of the selected elements have a Mark parameter.', title='No Mark Parameters')
    script.exit()

# Load existing saved marks
saved_marks = load_saved_marks()

# Check for elements that already have saved marks
elements_with_saved_marks = []
for elem, _ in elements_to_process:
    elem_id_str = str(elem.Id.IntegerValue)
    if elem_id_str in saved_marks:
        elements_with_saved_marks.append(elem)

# If elements with saved marks are found, prompt the user
overwrite_saved = True  # Default
if elements_with_saved_marks:
    msg = "{} selected elements already have saved marks in the tracker. Do you want to overwrite them?".format(len(elements_with_saved_marks))
    overwrite_saved = forms.alert(msg, yes=True, no=True, title='Saved Marks Found')
    if not overwrite_saved:
        # Filter out elements with saved marks
        elements_to_process = [(elem, param) for elem, param in elements_to_process 
                              if str(elem.Id.IntegerValue) not in saved_marks]
        
        if not elements_to_process:
            forms.alert('No elements left to process after filtering out saved marks.', title='Operation Cancelled')
            script.exit()

# Find highest existing H number in project
highest_h_number = 0
all_elements = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()

# Check project elements for H marks
for elem in all_elements:
    mark_param = elem.LookupParameter('Mark')
    if mark_param and mark_param.HasValue:
        mark_value = mark_param.AsString()
        if mark_value and mark_value.startswith('H'):
            # Try to extract the number after 'H'
            match = re.search(r'H(\d+)', mark_value)
            if match:
                number = int(match.group(1))
                highest_h_number = max(highest_h_number, number)

# Also check our saved marks for any higher numbers
for elem_id, mark in saved_marks.items():
    if mark.startswith('H'):
        match = re.search(r'H(\d+)', mark)
        if match:
            number = int(match.group(1))
            highest_h_number = max(highest_h_number, number)

output.print_md("### Found highest H number in project: **H{}**".format(highest_h_number))

# Start transaction for renumbering
with revit.Transaction('Renumber Elements with H Prefix'):
    # Renumber elements
    start_number = highest_h_number + 1
    current_number = start_number
    
    for elem, param in elements_to_process:
        try:
            new_mark = 'H{}'.format(current_number)
            param.Set(new_mark)
            elem_id_str = str(elem.Id.IntegerValue)
            saved_marks[elem_id_str] = new_mark
            output.print_md(f"Set element ID: {elem.Id} to mark: {new_mark}")
            current_number += 1
        except Exception as e:
            output.print_md(f"**Error**: Could not set mark for element ID: {elem.Id} - {str(e)}")

# Save the updated marks
save_marks(saved_marks)

# Create functions to verify and restore marks
def verify_marks():
    """Verify that elements have the correct marks according to saved data."""
    mismatches = []
    for elem_id_str, saved_mark in saved_marks.items():
        try:
            elem_id = ElementId(int(elem_id_str))
            elem = doc.GetElement(elem_id)
            if elem:
                mark_param = elem.LookupParameter('Mark')
                if mark_param and mark_param.HasValue:
                    current_mark = mark_param.AsString()
                    if current_mark != saved_mark:
                        mismatches.append((elem, current_mark, saved_mark))
        except Exception:
            continue
    return mismatches

def restore_marks():
    """Restore marks to their saved values."""
    mismatches = verify_marks()
    if mismatches:
        with revit.Transaction('Restore Saved Marks'):
            for elem, _, saved_mark in mismatches:
                mark_param = elem.LookupParameter('Mark')
                mark_param.Set(saved_mark)
                output.print_md(f"Restored element ID: {elem.Id} to mark: {saved_mark}")
        forms.alert(f'Restored {len(mismatches)} elements to their saved marks.', title='Marks Restored')
    else:
        forms.alert('All marks match their saved values.', title='No Restoration Needed')

# Add button to restore marks
output.print_md("---")
output.print_md("### Additional Tools")
output.add_button("Verify & Restore Marks", restore_marks)

# Report success
forms.alert(f'Successfully renumbered {current_number - start_number} elements from H{start_number} to H{current_number - 1}.\n\nMarks have been saved and can be restored if changed.', title='Renumbering Complete')