from pyrevit import revit, DB, UI
from pyrevit import script
from System.Collections.Generic import List

# Get current document and active view
doc = revit.doc
uidoc = revit.uidoc
active_view = doc.ActiveView

# Get current selection
selection = revit.get_selection()

if not selection:
    UI.TaskDialog.Show("Error", "Please select elements first.")
    script.exit()

# Get system abbreviations from selected elements
system_abbreviations = set()

for element in selection:
    # Try to get system abbreviation parameter
    sys_abbrev_param = element.LookupParameter("System Abbreviation")
    if sys_abbrev_param and sys_abbrev_param.HasValue:
        abbrev = sys_abbrev_param.AsString()
        if abbrev:
            system_abbreviations.add(abbrev)

if not system_abbreviations:
    UI.TaskDialog.Show("Error", "No system abbreviations found in selected elements.")
    script.exit()

# Create collectors for different element types
pipe_collector = DB.FilteredElementCollector(doc, active_view.Id) \
    .OfCategory(DB.BuiltInCategory.OST_PipeCurves) \
    .WhereElementIsNotElementType()

pipe_fitting_collector = DB.FilteredElementCollector(doc, active_view.Id) \
    .OfCategory(DB.BuiltInCategory.OST_PipeFitting) \
    .WhereElementIsNotElementType()

pipe_accessory_collector = DB.FilteredElementCollector(doc, active_view.Id) \
    .OfCategory(DB.BuiltInCategory.OST_PipeAccessory) \
    .WhereElementIsNotElementType()

# Additional collectors for support elements that might be in different categories
mechanical_equipment_collector = DB.FilteredElementCollector(doc, active_view.Id) \
    .OfCategory(DB.BuiltInCategory.OST_MechanicalEquipment) \
    .WhereElementIsNotElementType()

generic_model_collector = DB.FilteredElementCollector(doc, active_view.Id) \
    .OfCategory(DB.BuiltInCategory.OST_GenericModel) \
    .WhereElementIsNotElementType()

specialty_equipment_collector = DB.FilteredElementCollector(doc, active_view.Id) \
    .OfCategory(DB.BuiltInCategory.OST_SpecialityEquipment) \
    .WhereElementIsNotElementType()

# Collect elements to isolate
elements_to_isolate = []

# Function to check system abbreviation and support discipline
def check_element_parameters(element):
    sys_abbrev_param = element.LookupParameter("System Abbreviation")
    support_discipline_param = element.LookupParameter("Support Discipline")
    
    # Check system abbreviation match
    if sys_abbrev_param and sys_abbrev_param.HasValue:
        abbrev = sys_abbrev_param.AsString()
        if abbrev in system_abbreviations:
            return True
    
    # Check support discipline match
    if support_discipline_param and support_discipline_param.HasValue:
        support_discipline = support_discipline_param.AsString()
        if support_discipline in system_abbreviations:
            return True
    
    return False

# Check pipes
for pipe in pipe_collector:
    if check_element_parameters(pipe):
        elements_to_isolate.append(pipe.Id)

# Check pipe fittings
for fitting in pipe_fitting_collector:
    if check_element_parameters(fitting):
        elements_to_isolate.append(fitting.Id)

# Check pipe accessories
for accessory in pipe_accessory_collector:
    if check_element_parameters(accessory):
        elements_to_isolate.append(accessory.Id)

# Check mechanical equipment (some hangers might be categorized here)
for equipment in mechanical_equipment_collector:
    if check_element_parameters(equipment):
        elements_to_isolate.append(equipment.Id)

# Check generic models (some custom hangers might be categorized here)
for model in generic_model_collector:
    if check_element_parameters(model):
        elements_to_isolate.append(model.Id)

# Check specialty equipment (some hangers might be categorized here)
for specialty in specialty_equipment_collector:
    if check_element_parameters(specialty):
        elements_to_isolate.append(specialty.Id)

if not elements_to_isolate:
    UI.TaskDialog.Show("No Elements", "No elements found with matching system abbreviations.")
    script.exit()

# Convert to .NET List for Revit API
element_ids = List[DB.ElementId](elements_to_isolate)

# Perform temporary isolate
try:
    with revit.Transaction("Isolate by System and Hangers"):
        active_view.IsolateElementsTemporary(element_ids)
    
    message = "Isolated {} elements with system abbreviations: {}".format(
        len(elements_to_isolate), 
        ", ".join(system_abbreviations)
    )
    print(message)
    
except Exception as e:
    UI.TaskDialog.Show("Error", "Failed to isolate elements: {}".format(str(e)))