# -*- coding: utf-8 -*-

from pyrevit import forms, script


OPT_MECH = "Include Mechanical Equipment (all types)"
OPT_HANGERS = "Include Hangers"


def main():
    config = script.get_config()
    current_mech = getattr(config, "include_mechanical_equipment", True)
    current_hangers = getattr(config, "include_hangers", True)

    all_options = [OPT_MECH, OPT_HANGERS]
    preselected = [o for o, enabled in [(OPT_MECH, current_mech), (OPT_HANGERS, current_hangers)] if enabled]

    result = forms.SelectFromList.show(
        all_options,
        title="By System Settings",
        button_name="Save",
        multiselect=True,
        filterfunc=None,
        resetfunc=None,
        default=preselected,
        info_panel="Select which additional elements to include when isolating by system."
    )

    if result is None:
        script.exit()

    config.include_mechanical_equipment = OPT_MECH in result
    config.include_hangers = OPT_HANGERS in result
    script.save_config()

    mech_state = "ON" if config.include_mechanical_equipment else "OFF"
    hanger_state = "ON" if config.include_hangers else "OFF"
    forms.alert(
        "Include Mechanical Equipment: {0}\nInclude Hangers: {1}".format(mech_state, hanger_state),
        title="By System Settings"
    )


if __name__ == "__main__":
    main()
