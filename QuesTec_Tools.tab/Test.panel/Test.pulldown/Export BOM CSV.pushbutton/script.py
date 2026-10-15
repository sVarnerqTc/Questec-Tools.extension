# -*- coding: utf-8 -*-
"""Export a Bill of Materials CSV (Stratus-style) for selected pipes,
pipe fittings, pipe accessories, mechanical equipment and plumbing equipment.

Uses the current selection; if nothing valid is selected the user is prompted
to pick elements. Rows are grouped by Sort / Size / Description.

Columns: Quantity, Stock, Size, Description, Total Length, Stock Code,
         Back Order, Vendor, ETA, Sort
"""

import codecs
import os
import re

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, Element, StorageType
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import forms, script


uidoc = __revit__.ActiveUIDocument
doc = uidoc.Document
logger = script.get_logger()


# ---------------------------------------------------------------------------
# Categories / sort groups
# ---------------------------------------------------------------------------

def _bic_value(name):
    """Return the integer id of a BuiltInCategory, or None if this Revit
    version doesn't have it (e.g. OST_PlumbingEquipment before 2024)."""
    bic = getattr(BuiltInCategory, name, None)
    if bic is None:
        return None
    return int(bic)


SORT_PIPE = '1'
SORT_FITTING = '2'
SORT_ACCESSORY = '3'
SORT_EQUIPMENT = '4'

CATEGORY_SORT = {}
for _name, _sort in [
    ('OST_PipeCurves', SORT_PIPE),
    ('OST_PipeFitting', SORT_FITTING),
    ('OST_PipeAccessory', SORT_ACCESSORY),
    ('OST_MechanicalEquipment', SORT_EQUIPMENT),
    ('OST_PlumbingEquipment', SORT_EQUIPMENT),
]:
    _val = _bic_value(_name)
    if _val is not None:
        CATEGORY_SORT[_val] = _sort

PIPE_CAT_ID = _bic_value('OST_PipeCurves')


def id_value(element_id):
    """ElementId -> int (works on Revit 2024+ .Value and older .IntegerValue)."""
    if hasattr(element_id, 'Value'):
        return element_id.Value
    return element_id.IntegerValue


def get_category_id(element):
    cat = element.Category
    if cat is None:
        return None
    return id_value(cat.Id)


def is_supported(element):
    return get_category_id(element) in CATEGORY_SORT


class BOMSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            return is_supported(element)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return False


# ---------------------------------------------------------------------------
# Parameter helpers
# ---------------------------------------------------------------------------

def _param_string(param):
    """Return a trimmed string value for a parameter, or '' if blank."""
    if param is None or not param.HasValue:
        return ''
    value = None
    if param.StorageType == StorageType.String:
        value = param.AsString()
    else:
        value = param.AsValueString()
    if value is None:
        return ''
    return value.strip()


def get_type_element(element):
    type_id = element.GetTypeId()
    if type_id is None or id_value(type_id) == -1:
        return None
    return doc.GetElement(type_id)


def get_param(element, name):
    """Instance value first, then type value. Returns '' if blank/missing."""
    value = _param_string(element.LookupParameter(name))
    if value:
        return value
    type_el = get_type_element(element)
    if type_el is not None:
        return _param_string(type_el.LookupParameter(name))
    return ''


def get_type_name(element):
    type_el = get_type_element(element)
    if type_el is None:
        return ''
    try:
        return Element.Name.__get__(type_el) or ''
    except Exception:
        p = type_el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return _param_string(p)


def get_family_name(element):
    symbol = getattr(element, 'Symbol', None)
    if symbol is not None:
        family = getattr(symbol, 'Family', None)
        if family is not None and family.Name:
            return family.Name
        if getattr(symbol, 'FamilyName', None):
            return symbol.FamilyName
    type_el = get_type_element(element)
    if type_el is not None:
        p = type_el.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
        val = _param_string(p)
        if val:
            return val
        if getattr(type_el, 'FamilyName', None):
            return type_el.FamilyName
    return ''


# ---------------------------------------------------------------------------
# Field formulas
# ---------------------------------------------------------------------------

def _has(text, *needles):
    """IndexOf(needle, text) > -1 for every needle (case-sensitive)."""
    for n in needles:
        if text.find(n) < 0:
            return False
    return True


# Ordered exactly as the STRATUS.Field.Material Pipe formula.
MATERIAL_PIPE_RULES = [
    (('Copper', 'Type L', 'ACR'), '*Pipe, ACR/MED Copper Tubing, Type L, Nitrogenized Capped & Clean'),
    (('Copper', 'Type L'), '*Pipe, Type L Copper'),
    (('Copper', 'Type K'), '*Pipe, Type K Copper'),
    (('CI', 'No-Hub'), '*Pipe, CI No Hub'),
    (('Sch 40', 'A53', 'Type E'), '*Pipe, Sch 40, A53 B Type E'),
    (('Sch 40', 'A53', 'Type F'), '*Pipe, Sch 40, A53 B Type F'),
    (('Sch 40', 'A106', 'Seamless'), '*Pipe, Sch 40, A106 B Seamless'),
    (('Sch 80', 'A53', 'Type E'), '*Pipe, Sch 80, A53 B Type E'),
    (('Sch 80', 'A53', 'Type F'), '*Pipe, Sch 80, A53 B Type F'),
    (('Sch 80', 'A106', 'Seamless'), '*Pipe, Sch 80, A106 B Seamless'),
    (('DWV', ' PVC', 'Schedule 40'), '*Pipe, PVC Sch 40 DWV'),
    (('DWV', ' PVC', 'Sch 40'), '*Pipe, PVC Sch 40 DWV'),
    (('DWV', 'CPVC', 'LabWaste'), '*Pipe, CPVC LabWaste DWV'),
    (('Spigot',), '*Pipe, Hub and Spigot, CI'),
    (('Poly Pro', 'Sch 40'), '*Pipe, Poly Pro Sch 40'),
    (('Sch 10', '304', 'ERW'), '*Pipe, Sch 10S, 304 Stainless Type E'),
    (('Sch 40', '304', 'ERW'), '*Pipe, Sch 40S, 304 Stainless Type E'),
    (('Sch 40', '304'), '*Pipe, Sch 40S, 304 Stainless'),
    (('Spears Low',), '*Pipe, Spears Low Extractable'),
    (('Pex',), '*Pipe, PEX'),
    (('Cardinal UHP',), '*Pipe, Cardinal SS316L T50'),
]


def material_pipe(element):
    """STRATUS.Field.Material Pipe (and '... with Connectors New').
    Blank for anything that isn't in the Pipes category."""
    if get_category_id(element) != PIPE_CAT_ID:
        return ''
    type_name = get_type_name(element)
    for needles, result in MATERIAL_PIPE_RULES:
        if _has(type_name, *needles):
            return result
    return '*' + type_name


def get_size(element):
    for name in ('QTC Alt Size', 'Size', 'Diameter'):
        value = get_param(element, name)
        if value:
            return value
    return get_param(element, 'Type Mark')


def get_description(element):
    if material_pipe(element):
        # "with Connectors New" uses the same logic as Material Pipe.
        return material_pipe(element)
    for name in ('QTC BOM Description', 'Alternate Description II'):
        value = get_param(element, name)
        if value:
            return value
    return get_family_name(element)


def get_stock_code(element):
    return get_param(element, 'QTC Stock Code')


def get_length_ft(element):
    p = element.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
    if p is None or not p.HasValue:
        return 0.0
    return p.AsDouble()


# ---------------------------------------------------------------------------
# Formatting / sorting
# ---------------------------------------------------------------------------

def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def format_feet_inches(feet):
    """73.574 -> 73' 6-7/8"  (rounded to nearest 1/8")."""
    eighths = int(round(feet * 12.0 * 8.0))
    ft, rem = divmod(eighths, 96)
    inches, frac = divmod(rem, 8)
    text = "{}' {}".format(ft, inches)
    if frac:
        g = _gcd(frac, 8)
        text += '-{}/{}'.format(frac // g, 8 // g)
    return text + '"'


_NUM_RE = re.compile(r'(\d+)\s*[- ]\s*(\d+)\s*/\s*(\d+)|(\d+)\s*/\s*(\d+)|(\d+(?:\.\d+)?)')


def _size_part_value(part):
    m = _NUM_RE.search(part)
    if not m:
        return None
    if m.group(1):
        return float(m.group(1)) + float(m.group(2)) / float(m.group(3))
    if m.group(4):
        return float(m.group(4)) / float(m.group(5))
    return float(m.group(6))


def size_sort_key(size):
    values = []
    for part in re.split(r'[xX]', size or ''):
        v = _size_part_value(part)
        values.append(v if v is not None else 1e9)
    return (values, (size or '').lower())


def csv_quote(value):
    return '"' + (value or '').replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def get_elements():
    selected = [doc.GetElement(eid) for eid in uidoc.Selection.GetElementIds()]
    elements = [el for el in selected if el is not None and is_supported(el)]
    if elements:
        return elements

    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element,
            BOMSelectionFilter(),
            'Select pipes, fittings, accessories and equipment, then click Finish'
        )
    except OperationCanceledException:
        return []
    return [doc.GetElement(r.ElementId) for r in refs]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_rows(elements):
    groups = {}
    for el in elements:
        try:
            sort = CATEGORY_SORT[get_category_id(el)]
            size = get_size(el)
            desc = get_description(el)
            stock_code = get_stock_code(el)
            # Stock code is part of the key so items with different codes
            # (or a missing code) don't get merged into one row.
            key = (sort, size, desc, stock_code)
            entry = groups.setdefault(key, {'qty': 0, 'length': 0.0})
            entry['qty'] += 1
            if sort == SORT_PIPE:
                entry['length'] += get_length_ft(el)
        except Exception as ex:
            logger.warning('Skipped element {}: {}'.format(id_value(el.Id), ex))

    keys = sorted(groups.keys(),
                  key=lambda k: (k[0], k[2].lower(), size_sort_key(k[1]), k[3]))
    return [(k, groups[k]) for k in keys]


def write_csv(path, rows):
    header = 'Quantity,Stock,Size,Description,Total Length,Stock Code,Back Order,Vendor,ETA,Sort'
    lines = [header]
    total_qty = 0
    total_len = 0.0
    for (sort, size, desc, stock_code), entry in rows:
        total_qty += entry['qty']
        total_len += entry['length']
        length_txt = format_feet_inches(entry['length']) if sort == SORT_PIPE else ''
        lines.append(','.join([
            str(entry['qty']),
            csv_quote(''),            # Stock
            csv_quote(size),
            csv_quote(desc),
            csv_quote(length_txt),
            csv_quote(stock_code),    # Stock Code
            csv_quote(''),            # Back Order
            csv_quote(''),            # Vendor
            csv_quote(''),            # ETA
            csv_quote(sort),
        ]))
    total_len_txt = csv_quote(format_feet_inches(total_len)) if total_len else ''
    lines.append('{},,,,{},,,,,'.format(total_qty, total_len_txt))

    with codecs.open(path, 'w', 'utf-8-sig') as f:
        f.write(u'\r\n'.join(lines))


def default_file_name():
    info = doc.ProjectInformation
    number = ''
    if info is not None:
        number = _param_string(info.get_Parameter(BuiltInParameter.PROJECT_NUMBER))
    title = doc.Title or 'Model'
    name = '{} - {} - BOM'.format(number, title) if number else '{} - BOM'.format(title)
    return re.sub(r'[\\/:*?"<>|]', '_', name)


def main():
    elements = get_elements()
    if not elements:
        forms.alert('No pipes, fittings, accessories or equipment were selected.', title='Export BOM CSV')
        return

    path = forms.save_file(file_ext='csv', default_name=default_file_name(), title='Save BOM CSV')
    if not path:
        return
    if not path.lower().endswith('.csv'):
        path += '.csv'

    rows = build_rows(elements)

    try:
        write_csv(path, rows)
    except IOError as ex:
        forms.alert('Could not write the file (is it open in Excel?)\n\n{}'.format(ex), title='Export BOM CSV')
        return

    forms.alert('Exported {} rows ({} elements) to:\n\n{}'.format(len(rows), len(elements), path),
                title='Export BOM CSV')


main()
