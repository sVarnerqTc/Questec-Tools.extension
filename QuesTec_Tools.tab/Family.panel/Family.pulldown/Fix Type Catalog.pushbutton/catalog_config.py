# -*- coding: utf-8 -*-
"""Keyword list shared by Fix Type Catalog and its Shift+Click settings."""

from pyrevit import script


DEFAULT_KEYWORDS = ["POUNDS", "GALLONS"]


def get_keywords():
    config = script.get_config()
    raw = getattr(config, "problem_keywords", None)
    if not raw:
        return list(DEFAULT_KEYWORDS)
    return [k.strip().upper() for k in raw.split(",") if k.strip()]


def save_keywords(keywords):
    config = script.get_config()
    config.problem_keywords = ",".join(k.strip().upper() for k in keywords if k.strip())
    script.save_config()
