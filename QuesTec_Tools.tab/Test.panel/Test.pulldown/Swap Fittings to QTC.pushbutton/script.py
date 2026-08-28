# -*- coding: utf-8 -*-
"""Swap selected MEP fittings to their best matching QTC family type."""

import re

from Autodesk.Revit.DB import BuiltInCategory, FamilySymbol, FilteredElementCollector
from pyrevit import forms, revit, script


QTC_MARKER = "qtc"
MIN_MATCH_SCORE = 0.75
NOMINAL_RADIUS_PARAM_NAMES = ("Nom Radius1", "Nom Radius2", "Nom Radius3")
FALLBACK_RADIUS_PARAM_NAME = "Nom Radius"
RADIUS_TOLERANCE = 1e-6
SKIP_FITTING_OPTION = "< Do Not Change This Fitting >"
SWAPPABLE_CATEGORY_IDS = (
    int(BuiltInCategory.OST_PipeFitting),
    int(BuiltInCategory.OST_PipeAccessory),
)


def tokenize(name):
    """Lowercase, strip the QTC marker, and split into word tokens."""
    name = name.lower().replace(QTC_MARKER, "")
    return set(token for token in re.split(r"[^a-z0-9]+", name) if token)


def jaccard(left_tokens, right_tokens):
    """Return token-set similarity from 0 through 1."""
    if not left_tokens or not right_tokens:
        return 0.0
    union = len(left_tokens | right_tokens)
    return float(len(left_tokens & right_tokens)) / union if union else 0.0


def get_nominal_radii(element_or_symbol):
    """Return available nominal radii using Revit's internal length units."""
    radii = {}
    for parameter_name in NOMINAL_RADIUS_PARAM_NAMES:
        parameter = element_or_symbol.LookupParameter(parameter_name)
        if parameter:
            try:
                radii[parameter_name] = parameter.AsDouble()
            except Exception:
                pass
    if not radii:
        parameter = element_or_symbol.LookupParameter(FALLBACK_RADIUS_PARAM_NAME)
        if parameter:
            try:
                radii[FALLBACK_RADIUS_PARAM_NAME] = parameter.AsDouble()
            except Exception:
                pass
    return radii


def nominal_radii_match(source_radii, candidate_radii):
    """Return whether candidate type radii match the source fitting radii."""
    if not source_radii or set(source_radii) != set(candidate_radii):
        return False
    for parameter_name, source_value in source_radii.items():
        if abs(candidate_radii[parameter_name] - source_value) > RADIUS_TOLERANCE:
            return False
    return True


def apply_nominal_radii(element, source_radii):
    """Copy source nominal radii to every writable replacement-fitting parameter."""
    skipped_parameters = []
    for parameter_name, source_value in source_radii.items():
        parameter = element.LookupParameter(parameter_name)
        if parameter is None or parameter.IsReadOnly:
            skipped_parameters.append(parameter_name)
            continue
        try:
            if not parameter.Set(source_value):
                skipped_parameters.append(parameter_name)
        except Exception:
            skipped_parameters.append(parameter_name)
    return skipped_parameters


def find_qtc_family_symbols(doc, category_id):
    """Group QTC family symbols in the supplied category by family name."""
    families = {}
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategoryId(category_id)
    for symbol in collector:
        family_name = symbol.Family.Name
        if QTC_MARKER in family_name.lower():
            families.setdefault(family_name, []).append(symbol)
    return families


def best_qtc_match(source_family_name, qtc_family_map):
    """Return the highest-scoring QTC family name and its score."""
    source_tokens = tokenize(source_family_name)
    best_name = None
    best_score = 0.0
    for family_name in qtc_family_map:
        score = jaccard(source_tokens, tokenize(family_name))
        if score > best_score:
            best_name = family_name
            best_score = score
    return best_name, best_score


def choose_qtc_family(source_family_name, qtc_family_map, best_score):
    """Let the user select a QTC family when fuzzy matching is inconclusive."""
    if not qtc_family_map:
        return None
    choices = [SKIP_FITTING_OPTION]
    choices.extend(sorted(qtc_family_map.keys(), key=lambda name: name.lower()))
    title = "Choose QTC Family (best score {:.2f})\n{}".format(
        best_score, source_family_name
    )
    return forms.SelectFromList.show(
        choices,
        title=title,
        button_name="Use Selected Family",
        multiselect=False
    )


def pick_type_for_size(symbols, source_radii):
    """Choose a symbol whose nominal-radius signature matches the source."""
    if len(symbols) == 1:
        return symbols[0], bool(source_radii)
    if source_radii:
        for symbol in symbols:
            if nominal_radii_match(source_radii, get_nominal_radii(symbol)):
                return symbol, True
    # No type-level radius data means size is instance-driven and will be set after swapping.
    if not any(get_nominal_radii(symbol) for symbol in symbols):
        return symbols[0], True
    return symbols[0], False


def get_connectors(element):
    """Return the element's MEP connectors, regardless of where exposed."""
    mep_model = getattr(element, "MEPModel", None)
    connector_manager = getattr(mep_model, "ConnectorManager", None)
    if connector_manager is None:
        connector_manager = getattr(element, "ConnectorManager", None)
    return list(connector_manager.Connectors) if connector_manager else []


def get_external_connection_count(element):
    """Count connections to other elements, excluding internal connector references."""
    count = 0
    for connector in get_connectors(element):
        for reference in connector.AllRefs:
            if reference.Owner.Id != element.Id:
                count += 1
    return count


def disconnect_external_connectors(element):
    """Disconnect and return external connections with their original locations."""
    connections = []
    for connector in get_connectors(element):
        for reference in list(connector.AllRefs):
            if reference.Owner.Id == element.Id:
                continue
            connections.append((connector.Origin, reference))
            connector.DisconnectFrom(reference)
    return connections


def reconnect_external_connectors(element, connections):
    """Reconnect each saved external connector to its nearest new connector."""
    new_connectors = get_connectors(element)
    failures = 0
    for original_origin, external_connector in connections:
        available = [
            connector for connector in new_connectors
            if not connector.IsConnected
        ]
        if not available:
            failures += 1
            continue
        target_connector = min(
            available,
            key=lambda connector: connector.Origin.DistanceTo(original_origin)
        )
        try:
            target_connector.ConnectTo(external_connector)
        except Exception:
            failures += 1
    return failures


def get_fitting_ids_in_active_view(doc):
    """Return all placed pipe fitting and accessory ids visible in the active view."""
    collector = (
        FilteredElementCollector(doc, doc.ActiveView.Id)
        .WhereElementIsNotElementType()
    )
    return [
        element.Id for element in collector
        if element.Category and element.Category.Id.IntegerValue in SWAPPABLE_CATEGORY_IDS
    ]


def main():
    doc = revit.doc
    uidoc = revit.uidoc
    output = script.get_output()
    output.set_title("Swap Fittings to QTC")

    selected_ids = list(uidoc.Selection.GetElementIds())
    if not selected_ids:
        should_process_view = forms.alert(
            "No elements are selected. Process all pipe fittings and accessories in the active view?",
            title="Swap Fittings to QTC",
            yes=True,
            no=True
        )
        if not should_process_view:
            return
        selected_ids = get_fitting_ids_in_active_view(doc)
        if not selected_ids:
            forms.alert(
                "No pipe fittings or accessories were found in the active view.",
                title="Swap Fittings to QTC"
            )
            return

    report = []
    qtc_families_by_category = {}
    with revit.Transaction("Swap fittings to QTC type"):
        for element_id in selected_ids:
            element = doc.GetElement(element_id)
            if element is None or element.Category is None:
                continue
            if element.Category.Id.IntegerValue not in SWAPPABLE_CATEGORY_IDS:
                report.append((
                    element_id.IntegerValue,
                    element.Name,
                    "SKIPPED",
                    "selected element is not a pipe fitting or accessory"
                ))
                continue

            source_symbol = doc.GetElement(element.GetTypeId())
            if not isinstance(source_symbol, FamilySymbol):
                report.append((
                    element_id.IntegerValue,
                    element.Name,
                    "SKIPPED",
                    "selected element does not use a loadable family type"
                ))
                continue

            source_family_name = source_symbol.Family.Name
            if QTC_MARKER in source_family_name.lower():
                report.append((element_id.IntegerValue, source_family_name, "SKIPPED", "already a QTC fitting"))
                continue

            category_key = element.Category.Id.IntegerValue
            if category_key not in qtc_families_by_category:
                qtc_families_by_category[category_key] = find_qtc_family_symbols(
                    doc, element.Category.Id
                )
            qtc_family_map = qtc_families_by_category[category_key]
            match_name, score = best_qtc_match(source_family_name, qtc_family_map)
            if not match_name or score < MIN_MATCH_SCORE:
                match_name = choose_qtc_family(source_family_name, qtc_family_map, score)
                if not match_name or match_name == SKIP_FITTING_OPTION:
                    report.append((
                        element_id.IntegerValue,
                        source_family_name,
                        "SKIPPED",
                        "user chose not to change fitting (best score {:.2f})".format(score)
                    ))
                    continue
                match_source = "user selected"
            else:
                match_source = "auto-match"

            source_radii = get_nominal_radii(element)
            chosen_symbol, size_confident = pick_type_for_size(
                qtc_family_map[match_name], source_radii
            )
            if not chosen_symbol.IsActive:
                chosen_symbol.Activate()
                doc.Regenerate()

            disconnected_connections = disconnect_external_connectors(element)
            doc.Regenerate()
            changed_id = element.ChangeTypeId(chosen_symbol.Id)
            doc.Regenerate()
            final_id = changed_id if changed_id and changed_id.IntegerValue != -1 else element_id
            swapped_element = doc.GetElement(final_id)
            skipped_radius_parameters = apply_nominal_radii(swapped_element, source_radii)
            doc.Regenerate()
            reconnection_failures = reconnect_external_connectors(
                swapped_element, disconnected_connections
            )
            doc.Regenerate()
            original_connection_count = len(disconnected_connections)
            final_connection_count = get_external_connection_count(swapped_element)
            status = (
                "OK" if final_connection_count >= original_connection_count
                else "CHECK CONNECTIONS"
            )
            note = "-> {} ({}; score {:.2f}){}".format(
                match_name,
                match_source,
                score,
                "" if size_confident else " [nominal radii ambiguous, used first type]"
            )
            if skipped_radius_parameters:
                note += " [not writable: {}]".format(
                    ", ".join(skipped_radius_parameters)
                )
            if reconnection_failures:
                status = "CHECK CONNECTIONS"
                note += " [{} reconnection(s) failed]".format(reconnection_failures)
            note += " [connections: {} -> {}]".format(
                original_connection_count, final_connection_count
            )
            report.append((element_id.IntegerValue, source_family_name, status, note))

    print("=== QTC Swap Report ===")
    for element_id, source_name, status, note in report:
        print("ElementId {} | {} | {} | {}".format(element_id, source_name, status, note))


main()
