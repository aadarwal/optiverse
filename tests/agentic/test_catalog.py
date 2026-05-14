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
