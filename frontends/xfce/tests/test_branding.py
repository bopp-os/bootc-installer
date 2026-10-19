"""tuna_installer_xfce/branding.py against the shared fixtures.

The module is a byte-identical copy of shared/branding/branding.py (the
monorepo's tests/unit/test_shared_branding.py enforces that); this test
proves the copy this tree ships resolves the contract's cases, so the XFCE
CI job catches a drift on its own.
"""

import json
import os

import pytest

from tuna_installer_xfce import branding, core

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.normpath(os.path.join(HERE, "..", "..", "..", "shared", "branding", "fixtures"))

pytestmark = pytest.mark.skipif(
    not os.path.isdir(FIXTURES), reason="shared fixtures only exist in the monorepo checkout"
)


def _case(name):
    with open(os.path.join(FIXTURES, "expected.json")) as fh:
        case = json.load(fh)[name]
    file_data = None
    if case["branding"]:
        with open(os.path.join(FIXTURES, case["branding"])) as fh:
            file_data = json.load(fh)
    os_release = None
    if case["os_release"]:
        with open(os.path.join(FIXTURES, case["os_release"])) as fh:
            os_release = fh.read()
    return case, file_data, os_release


@pytest.mark.parametrize(
    "name", [name for name, case in json.load(
        open(os.path.join(FIXTURES, "expected.json"))).items()
        if isinstance(case, dict) and "expect" in case])
def test_fixture_case(name):
    case, file_data, os_release = _case(name)
    got = branding.from_sources(file_data, os_release)
    assert got.as_dict() == case["expect"]
    for k, v in case.get("expect_copy", {}).items():
        assert got.copy[k] == v, k
    for k, v in case.get("expect_assets", {}).items():
        assert got.assets.get(k, "") == v, k
    if "expect_store_url" in case:
        assert got.store_url == case["expect_store_url"]


def test_name_override():
    case, file_data, os_release = _case("name_override")
    got = branding.from_sources(file_data, os_release, case["name_override"])
    assert got.name == case["expect_name"]


def test_core_exposes_branding(tmp_path, monkeypatch):
    """core.PRODUCT_NAME, the recipe's distroID and the hostname seed all come
    from the same resolution; nothing in core.py names a product."""
    f = tmp_path / "branding.json"
    f.write_text('{"name": "Marlin", "id": "marlin", "default_hostname": "reef"}')
    monkeypatch.setenv(branding.ENV_FILE, str(f))
    b = core.resolve_branding()
    assert (b.name, b.id, b.default_hostname) == ("Marlin", "marlin", "reef")
    recipe = core.build_recipe(disk="/dev/sda", filesystem="xfs", encryption_type="none",
                               image="ghcr.io/example/x:1", hostname=b.default_hostname,
                               branding=b)
    assert recipe["distroID"] == "marlin"
    assert recipe["hostname"] == "reef"
