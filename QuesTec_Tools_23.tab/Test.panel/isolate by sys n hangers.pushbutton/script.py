from pyrevit import revit, DB, forms
from System.Collections.Generic import List

# Get current selection
selection = revit.get_selection()

if not selection:
    forms.alert('Please select at least one element.', exitscript=True)

# Get all PipingSystemTypes in the project
piping_system_types = DB.FilteredElementCollector(revit.doc)\
                       .OfClass(DB.Plumbing.PipingSystemType)\
                       .ToElements()

# Lists to collect elements to isolate
elements_to_isolate = set()
system_types_found = set()
support_disciplines_found = set()

# Process selected elements
for element in selection:
    if isinstance(element, (DB.Plumbing.Pipe, DB.FamilyInstance)):
        # Get System Type parameter for pipes and accessories
        system_type_param = element.get_Parameter(DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
        if system_type_param:
            system_type_id = system_type_param.AsElementId()
            if system_type_id and not system_type_id.IntegerValue == -1:
                system_type = revit.doc.GetElement(system_type_id)
                system_types_found.add(system_type)
        
        # Also check for support discipline if it's a family instance
        if isinstance(element, DB.FamilyInstance):
            support_discipline_param = element.get_Parameter(DB.BuiltInParameter.SUPPORT_DISCIPLINE)
            if support_discipline_param:
                support_discipline = support_discipline_param.AsString()
                support_disciplines_found.add(support_discipline)

# Get all pipes and accessories in the active view
view_elements = DB.FilteredElementCollector(revit.doc, revit.active_view.Id)\
                 .WhereElementIsNotElementType()\
                 .ToElements()

# Filter elements based on system types and support disciplines
for element in view_elements:
    if isinstance(element, (DB.Plumbing.Pipe, DB.PlumbingUtils.Fitting, DB.FamilyInstance)):
        system_type_param = element.get_Parameter(DB.BuiltInParameter.RBS_PIPING_SYSTEM_TYPE_PARAM)
        if system_type_param:
            system_type_id = system_type_param.AsElementId()
            if system_type_id and not system_type_id.IntegerValue == -1:
                system_type = revit.doc.GetElement(system_type_id)
                if system_type in system_types_found:
                    elements_to_isolate.add(element.Id)
        
        # Check support discipline for family instances
        if isinstance(element, DB.FamilyInstance):
            support_discipline_param = element.get_Parameter(DB.BuiltInParameter.SUPPORT_DISCIPLINE)
            if support_discipline_param:
                support_discipline = support_discipline_param.AsString()
                if support_discipline in support_disciplines_found:
                    for sys_type in piping_system_types:
                        abbrev_param = sys_type.get_Parameter(DB.BuiltInParameter.SYMBOL_ABBREV_PARAM)
                        if abbrev_param and abbrev_param.AsString() == support_discipline:
                            elements_to_isolate.add(element.Id)
                            break

# Convert set to List for Revit API
elements_to_isolate_list = List[DB.ElementId](elements_to_isolate)

# Isolate elements in the active view
if elements_to_isolate:
    try:
        revit.active_view.IsolateElementsTemporary(elements_to_isolate_list)
        forms.alert('Successfully isolated {} elements.'.format(len(elements_to_isolate)))
    except Exception as ex:
        forms.alert('Error isolating elements: {}'.format(str(ex)))
else:
    forms.alert('No matching elements found to isolate.')