from optiverse.agentic.catalog import catalog_summary, load_builtin_catalog


def test_load_builtin_catalog_contains_expected_components():
    catalog = load_builtin_catalog()

    assert "waveplate_hwp" in catalog
    assert "pbs_2in" in catalog
    assert catalog["waveplate_hwp"]["name"] == "Half Waveplate (HWP)"
    assert catalog["pbs_2in"]["interfaces"][0]["is_polarizing"] is True


def test_catalog_summary_is_prompt_sized():
    catalog = load_builtin_catalog()
    summary = catalog_summary(catalog)

    pbs = next(item for item in summary if item["catalog_id"] == "pbs_2in")
    assert pbs["name"] == 'PBS (2" Polarizing)'
    assert pbs["interfaces"][0]["element_type"] == "beam_splitter"
    assert pbs["interfaces"][0]["is_polarizing"] is True
    assert pbs["interfaces"][0]["pbs_transmission_axis_deg"] == 0.0
    assert pbs["capabilities"] == ["pass_through", "polarization_control", "reflects", "splits"]


def test_catalog_summary_infers_lens_and_waveplate_capabilities():
    catalog = load_builtin_catalog()
    summary = catalog_summary(catalog)

    lens = next(item for item in summary if item["catalog_id"] == "lens_standard_1in")
    hwp = next(item for item in summary if item["catalog_id"] == "waveplate_hwp")

    assert lens["interfaces"][0]["efl_mm"] == 100.0
    assert lens["interfaces"][0]["clear_aperture_mm"] == 25.4
    assert "focuses" in lens["capabilities"]
    assert hwp["interfaces"][0]["phase_shift_deg"] == 180.0
    assert hwp["interfaces"][0]["fast_axis_deg"] == 0.0
    assert "polarization_control" in hwp["capabilities"]
