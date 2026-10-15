# -*- coding: utf-8 -*-
"""Split Couplings

Split selected pipes into pieces of a set length and join them with a
coupling chosen from the pipe fittings loaded in the project.

- Uses the current selection, or prompts you to pick pipes.
- Asks for the piece length (e.g. 20', 21'-0", 10.5) and which end to
  measure from.
- Lists coupling / union fitting types in the project to choose from.
- Measures the coupling takeout (gap between its connectors) so each piece
  comes out at the requested length, then checks and corrects the final
  length of every piece and reports it.
"""
from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB.Plumbing import Pipe, PlumbingUtils
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

__title__ = 'Split\nCouplings'
__author__ = 'QuesTec BIM'

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

LEN_TOL = 1.0 / 64.0 / 12.0      # 1/64" - pieces within this are "on length"
CONN_TOL = 1e-4
MAX_PIECES = 200


# ----------------------------------------------------------------- helpers
def type_name(elem):
    if elem is None:
        return ''
    for bip in (DB.BuiltInParameter.SYMBOL_NAME_PARAM, DB.BuiltInParameter.ALL_MODEL_TYPE_NAME):
        p = elem.get_Parameter(bip)
        if p and p.HasValue and p.AsString():
            return p.AsString()
    return ''


def fmt_len(ft):
    try:
        return DB.UnitFormatUtils.Format(doc.GetUnits(), DB.SpecTypeId.Length, ft, False)
    except Exception:
        return '{:.4f} ft'.format(ft)


def parse_len(text):
    text = (text or '').strip()
    if not text:
        return None
    try:
        ok, val = DB.UnitFormatUtils.TryParse(doc.GetUnits(), DB.SpecTypeId.Length, text)
        if ok and val > 0:
            return val
    except Exception:
        pass
    try:
        val = float(text)          # plain number = feet
        return val if val > 0 else None
    except Exception:
        return None


def pipe_len(p):
    return p.Location.Curve.Length


def end_conns(p):
    return [c for c in p.ConnectorManager.Connectors if c.ConnectorType == DB.ConnectorType.End]


def conn_near(p, pt):
    best = None
    for c in end_conns(p):
        d = c.Origin.DistanceTo(pt)
        if best is None or d < best[0]:
            best = (d, c)
    return best[1] if best else None


class PipeFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, Pipe)

    def AllowReference(self, r, p):
        return False


# --------------------------------------------------------------- 1. pipes
pipes = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
pipes = [p for p in pipes if isinstance(p, Pipe)]
if not pipes:
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, PipeFilter(), 'Select pipes to split, then click Finish')
        pipes = [doc.GetElement(r.ElementId) for r in refs]
    except Exception:
        script.exit()
pipes = [p for p in pipes if isinstance(p.Location, DB.LocationCurve) and isinstance(p.Location.Curve, DB.Line)]
if not pipes:
    forms.alert('No straight pipes selected.', exitscript=True)

# -------------------------------------------------------------- 2. length
txt = forms.ask_for_string(default="20'", prompt='Split pipes into pieces this long\n(e.g. 20\', 21\'-0", 10.5 = feet):',
                           title='Split Couplings - Piece Length')
if txt is None:
    script.exit()
TARGET = parse_len(txt)
if not TARGET:
    forms.alert('Could not read a length from "{}".'.format(txt), exitscript=True)

START_OPTS = ['North / East / Top end', 'South / West / Bottom end', 'Pipe start point (as drawn)']
start_mode = forms.CommandSwitchWindow.show(START_OPTS, message='Measure full-length pieces from which end?\n(the short remainder ends up at the other end)')
if not start_mode:
    script.exit()

# ------------------------------------------------------------ 3. coupling
def is_coupling(sym):
    fam = sym.Family
    try:
        pt = fam.get_Parameter(DB.BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
        if pt and pt.AsInteger() == int(DB.PartType.Union):
            return True
    except Exception:
        pass
    n = (fam.Name + ' ' + type_name(sym)).lower()
    return 'coupl' in n or 'union' in n

syms = [s for s in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_PipeFitting)
        .WhereElementIsElementType() if isinstance(s, DB.FamilySymbol) and is_coupling(s)]
if not syms:
    forms.alert('No coupling or union pipe fittings are loaded in this project.', exitscript=True)
sym_map = {}
for s in syms:
    sym_map['{} : {}'.format(s.Family.Name, type_name(s))] = s
pick = forms.SelectFromList.show(sorted(sym_map.keys()), title='Select Coupling', button_name='Use This Coupling',
                                 multiselect=False, width=700)
if not pick:
    script.exit()
COUPLING = sym_map[pick]


# ---------------------------------------------------------- direction logic
def start_end(curve):
    a, b = curve.GetEndPoint(0), curve.GetEndPoint(1)
    if start_mode == START_OPTS[2]:
        return a, b
    d = b - a
    ax = max((abs(d.X), 'X'), (abs(d.Y), 'Y'), (abs(d.Z), 'Z'))[1]
    av, bv = getattr(a, ax), getattr(b, ax)
    hi_first = (start_mode == START_OPTS[0])
    if (av > bv) == hi_first:
        return a, b
    return b, a


def along(pt, origin, dirv):
    return (pt - origin).DotProduct(dirv)


# -------------------------------------------------- routing pref swap/restore
def push_union_rule(pipe_type, sym_id):
    rpm = pipe_type.RoutingPreferenceManager
    grp = DB.RoutingPreferenceRuleGroupType.Unions
    rpm.AddRule(grp, DB.RoutingPreferenceRule(sym_id, 'Split Couplings (temp)'), 0)
    return rpm


def pop_union_rule(rpm):
    rpm.RemoveRule(DB.RoutingPreferenceRuleGroupType.Unions, 0)


def coupling_takeout(fit):
    pts = [c.Origin for c in fit.MEPModel.ConnectorManager.Connectors]
    if len(pts) < 2:
        return 0.0
    return max(pts[i].DistanceTo(pts[j]) for i in range(len(pts)) for j in range(i + 1, len(pts)))


# ------------------------------------------------------------------ 4. run
results = []
types_done = {}
tg = DB.TransactionGroup(doc, 'Split Couplings')
tg.Start()
t = DB.Transaction(doc, 'Split Couplings')
t.Start()
if not COUPLING.IsActive:
    COUPLING.Activate()
    doc.Regenerate()

for pipe in pipes:
    orig_id = pipe.Id.IntegerValue
    orig_len = pipe_len(pipe)
    if orig_len <= TARGET + LEN_TOL:
        results.append((orig_id, orig_len, [], [], 'Already at or under length - skipped'))
        continue
    pipe_type = doc.GetElement(pipe.GetTypeId())
    st = DB.SubTransaction(doc)
    st.Start()
    rpm = None
    try:
        rpm = push_union_rule(pipe_type, COUPLING.Id)
        s0, e0 = start_end(pipe.Location.Curve)
        dirv = (e0 - s0).Normalize()
        origin = s0
        cur = pipe
        pieces, couplings = [], []
        takeout = None
        guard = 0
        while pipe_len(cur) > TARGET + LEN_TOL and guard < MAX_PIECES:
            guard += 1
            c = cur.Location.Curve
            ends = sorted([c.GetEndPoint(0), c.GetEndPoint(1)], key=lambda p: along(p, origin, dirv))
            near_end = ends[0]
            gap = takeout if takeout is not None else 0.0
            brk = near_end + dirv * (TARGET + gap / 2.0)
            new_id = PlumbingUtils.BreakCurve(doc, cur.Id, brk)
            q = doc.GetElement(new_id)
            def mid(e):
                cc = e.Location.Curve
                return along((cc.GetEndPoint(0) + cc.GetEndPoint(1)) / 2.0, origin, dirv)
            near, far = (cur, q) if mid(cur) < mid(q) else (q, cur)
            c1, c2 = conn_near(near, brk), conn_near(far, brk)
            fit = doc.Create.NewUnionFitting(c1, c2)
            doc.Regenerate()
            if takeout is None:
                takeout = coupling_takeout(fit)
            # final length check / correction
            for _ in range(3):
                err = TARGET - pipe_len(near)
                if abs(err) <= 1e-6:
                    break
                DB.ElementTransformUtils.MoveElement(doc, fit.Id, dirv * err)
                doc.Regenerate()
            pieces.append(near)
            couplings.append(fit)
            cur = far
        pieces.append(cur)
        pop_union_rule(rpm)
        rpm = None
        st.Commit()
        results.append((orig_id, orig_len, pieces, couplings, takeout))
    except Exception as ex:
        if rpm is not None:
            try:
                pop_union_rule(rpm)
            except Exception:
                pass
        st.RollBack()
        results.append((orig_id, orig_len, [], [], 'FAILED: {}'.format(ex)))

t.Commit()
tg.Assimilate()

# --------------------------------------------------------------- 5. report
output.print_md('## Split Couplings')
output.print_md('**Piece length:** {}  |  **Coupling:** {}  |  **Measured from:** {}'.format(fmt_len(TARGET), pick, start_mode))
bad = 0
new_ids = []
for orig_id, orig_len, pieces, couplings, info in results:
    if not pieces:
        output.print_md('- Pipe {} ({}): {}'.format(output.linkify(DB.ElementId(orig_id)), fmt_len(orig_len), info))
        continue
    output.print_md('- Pipe {} ({}) -> {} pieces, {} couplings, coupling takeout {:.3f}"'.format(
        output.linkify(DB.ElementId(orig_id)), fmt_len(orig_len), len(pieces), len(couplings), (info or 0.0) * 12.0))
    for i, p in enumerate(pieces):
        L = pipe_len(p)
        full = i < len(pieces) - 1
        ok = (abs(L - TARGET) <= LEN_TOL) if full else (L <= TARGET + LEN_TOL)
        if not ok:
            bad += 1
        flag = '' if ok else '  **<-- CHECK LENGTH**'
        label = 'piece' if full else 'remainder'
        output.print_md('    - {} {}: {}{}'.format(label, output.linkify(p.Id), fmt_len(L), flag))
        new_ids.append(p.Id)
    new_ids.extend([f.Id for f in couplings])

if bad:
    output.print_md('\n**{} piece(s) did not come out on length - review the items flagged above.**'.format(bad))
else:
    output.print_md('\nAll full pieces checked at {} (+/- 1/64").'.format(fmt_len(TARGET)))

if new_ids:
    from System.Collections.Generic import List
    uidoc.Selection.SetElementIds(List[DB.ElementId](new_ids))
