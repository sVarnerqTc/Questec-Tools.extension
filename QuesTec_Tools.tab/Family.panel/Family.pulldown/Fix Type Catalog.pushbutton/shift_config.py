# -*- coding: utf-8 -*-
"""Shift+Click: edit the keywords that pre-check type catalog columns."""

from pyrevit import forms

import catalog_config


def main():
    current = catalog_config.get_keywords()
    value = forms.ask_for_string(
        default=", ".join(current),
        prompt="Columns whose header contains any of these words are pre-checked for removal.\n"
               "Separate with commas (not case sensitive). Example: POUNDS, GALLONS",
        title="Fix Type Catalog Settings",
    )
    if value is None:
        return

    keywords = [k.strip() for k in value.split(",") if k.strip()]
    if not keywords:
        keywords = catalog_config.DEFAULT_KEYWORDS
    catalog_config.save_keywords(keywords)
    forms.alert(
        "Saved keywords:\n\n{0}".format(", ".join(catalog_config.get_keywords())),
        title="Fix Type Catalog Settings",
    )


if __name__ == "__main__":
    main()
