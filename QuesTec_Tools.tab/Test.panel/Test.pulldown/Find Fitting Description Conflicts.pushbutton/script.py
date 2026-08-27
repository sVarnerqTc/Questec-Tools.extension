import clr
import re

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import BuiltInCategory, FilteredElementCollector

from pyrevit import forms, script


doc = __revit__.ActiveUIDocument.Document
output = script.get_output()


MATERIAL_RULES = [
    ('MI CLASS 150', [r'\bMI\s*CLASS\s*150\b', r'\bMI\s*CL(?:ASS)?\s*150\b']),
    ('CS SCHSTD', [r'\bCS\s*SCH\s*STD\b', r'\bCS\s*SCHSTD\b']),
    ('FS 3000', [r'\bFS\s*CLASS\s*3000\b', r'\bFS\s*CL(?:ASS)?\s*3000\b', r'\bFS\s*3000\b']),
    ('SS-304', [r'\bSS\s*[- ]?304\b', r'\b304\s*SS\b']),
    ('CI NH', [r'\bCI\s*NH\b', r'\bCI\s*[-_]?NH\b', r'\bNO[\s-]*HUB\b']),
    ('BW SS', [r'\bBW\s*SS\b', r'\bSS\s*BW\b']),
    ('BW', [r'\bBW\b']),
    ('THD', [r'\bTHD\b', r'\bTHREADED\b']),
    ('COPPER', [r'\bCOPPER\b', r'\bCU\b']),
    ('PVC', [r'\bPVC\b'])
]

ELBOW_ANGLE_RULES = [
    ('1/16', [r'\b1\s*/\s*16\b', r'\b1-16\b', r'\bSIXTEENTH\b', r'\bONE[\s-]*SIXTEENTH\b']),
    ('1/8', [r'\b1\s*/\s*8\b', r'\b1-8\b', r'\bEIGHTH\b', r'\bONE[\s-]*EIGHTH\b']),
    ('1/4', [r'\b1\s*/\s*4\b', r'\b1-4\b', r'\bQUARTER\b', r'\bONE[\s-]*QUARTER\b', r'\bFOURTH\b', r'\bONE[\s-]*FOURTH\b']),
    ('22', [r'\b22(?:\.5)?\b']),
    ('45', [r'\b45\b']),
    ('90', [r'\b90\b'])
]



def get_non_empty_param_string(element, param_name):
    param = element.LookupParameter(param_name)
    if param is None:
        return None

    value = param.AsString()
    if value is None:
        value = param.AsValueString()

    if value is None:
        return None

    value = value.strip()
    return value if value else None


def get_non_empty_param_string_instance_then_type(element, param_name):
    instance_value = get_non_empty_param_string(element, param_name)
    if instance_value:
        return instance_value, 'instance'

    type_id = element.GetTypeId()
    if type_id and type_id.IntegerValue != -1:
        type_element = doc.GetElement(type_id)
        if type_element is not None:
            type_value = get_non_empty_param_string(type_element, param_name)
            if type_value:
                return type_value, 'type'

    return None, None



def get_best_description(fitting):
    desc, scope = get_non_empty_param_string_instance_then_type(fitting, 'QTC BOM Description')
    if desc:
        return desc, 'QTC BOM Description ({})'.format(scope)

    desc, scope = get_non_empty_param_string_instance_then_type(fitting, 'Alternate Description II')
    if desc:
        return desc, 'Alternate Description II ({})'.format(scope)

    symbol = getattr(fitting, 'Symbol', None)
    if symbol is None:
        return 'Unknown Family', 'Fallback'

    family = getattr(symbol, 'Family', None)
    if family is not None and family.Name:
        return family.Name, 'Family name'

    family_name = getattr(symbol, 'FamilyName', None)
    if family_name:
        return family_name, 'Family name'

    return 'Unknown Family', 'Fallback'


def get_family_name(fitting):
    symbol = getattr(fitting, 'Symbol', None)
    if symbol is None:
        return 'Unknown Family'

    family = getattr(symbol, 'Family', None)
    if family is not None and family.Name:
        return family.Name

    family_name = getattr(symbol, 'FamilyName', None)
    if family_name:
        return family_name

    return 'Unknown Family'



def get_size(fitting):
    size_value, _scope = get_non_empty_param_string_instance_then_type(fitting, 'Size')
    if size_value:
        return size_value

    return '(no size)'



def parse_material(description):
    for material, patterns in MATERIAL_RULES:
        for pattern in patterns:
            if re.search(pattern, description, re.IGNORECASE):
                return material

    return 'UNKNOWN'



def parse_fitting_type(description):
    if re.search(r'\bTEE\b', description, re.IGNORECASE):
        return 'tee'

    if re.search(r'\b(?:COMBO|COMBINATION)\b', description, re.IGNORECASE):
        return 'combo'

    if re.search(r'\bCOUPL(?:ING)?\b', description, re.IGNORECASE):
        return 'coupling'

    if re.search(r'\bCAP\b', description, re.IGNORECASE):
        return 'cap'

    if re.search(r'\bWYE\b', description, re.IGNORECASE):
        return 'wye'

    if re.search(r'\b(?:ELB(?:OW)?|BEND)\b', description, re.IGNORECASE):
        is_street = re.search(r'\bST(?:REET)?\b', description, re.IGNORECASE) is not None

        for angle_label, angle_patterns in ELBOW_ANGLE_RULES:
            for pattern in angle_patterns:
                if re.search(pattern, description, re.IGNORECASE):
                    if is_street:
                        return 'elbow {} street'.format(angle_label)
                    return 'elbow {}'.format(angle_label)

        if is_street:
            return 'elbow street'

        return 'elbow'

    if re.search(r'\bP[\s-]*TRAP\b', description, re.IGNORECASE):
        return 'p-trap'

    if re.search(r'\bRED(?:UCER|UCING)?\b', description, re.IGNORECASE):
        return 'reducer'

    return 'other'


fittings = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_PipeFitting)
    .WhereElementIsNotElementType()
    .ToElements()
)

if len(fittings) == 0:
    forms.alert('No pipe fittings were found in this project.', exitscript=True)

# Key: (material, fitting_type, size), value: dict(desc -> {'ids': [], 'families': set()})
classified = {}

for fitting in fittings:
    description, description_source = get_best_description(fitting)
    family_name = get_family_name(fitting)
    size = get_size(fitting)
    classification_text = '{} {}'.format(description, family_name)
    material = parse_material(classification_text)
    fitting_type = parse_fitting_type(classification_text)

    key = (material, fitting_type, size)
    if key not in classified:
        classified[key] = {}

    if description not in classified[key]:
        classified[key][description] = {'ids': [], 'families': set(), 'sources': set()}

    classified[key][description]['ids'].append(fitting.Id.IntegerValue)
    classified[key][description]['families'].add(family_name)
    classified[key][description]['sources'].add(description_source)

conflicts = []
for key, description_map in classified.items():
    if len(description_map.keys()) > 1:
        conflicts.append((key, description_map))

conflicts.sort(key=lambda item: (item[0][0], item[0][1], item[0][2]))

collapsed_conflicts = {}
for (material, fitting_type, _size), description_map in conflicts:
    report_key = (material, fitting_type)
    if report_key not in collapsed_conflicts:
        collapsed_conflicts[report_key] = {}

    for desc, entry in description_map.items():
        if desc not in collapsed_conflicts[report_key]:
            collapsed_conflicts[report_key][desc] = {'ids': set(), 'families': set(), 'sources': set()}

        collapsed_conflicts[report_key][desc]['ids'].update(entry['ids'])
        collapsed_conflicts[report_key][desc]['families'].update(entry['families'])
        collapsed_conflicts[report_key][desc]['sources'].update(entry['sources'])

if len(conflicts) == 0:
    forms.alert(
        'No description conflicts found.\n\nAll matching material/type/size groups have a single description.'
    )
else:
    output.print_md('## Pipe Fitting Description Conflicts')
    output.print_md('Found **{}** material/type group(s) with size-based conflicts.'.format(len(collapsed_conflicts)))

    for material_type in sorted(collapsed_conflicts.keys(), key=lambda item: (item[0], item[1])):
        material, fitting_type = material_type
        description_map = collapsed_conflicts[material_type]
        output.print_md('### Material: {} | Type: {}'.format(material, fitting_type))
        for desc in sorted(description_map.keys(), key=lambda s: s.lower()):
            entry = description_map[desc]
            ids = entry['ids']
            families = sorted(entry['families'], key=lambda s: s.lower())
            sources = sorted(entry['sources'], key=lambda s: s.lower())
            family_display = ', '.join(families)
            source_display = ', '.join(sources)
            output.print_md('- {} | {} [source: {}] ({} fittings)'.format(family_display, desc, source_display, len(ids)))

    forms.alert(
        'Found {} material/type groups with size-based conflicts.\n\nSee the pyRevit output window for details.'.format(len(collapsed_conflicts))
    )
