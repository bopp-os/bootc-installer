"""Canonical live-media storage metadata must survive the UI adapter."""

import pytest

from bootc_installer.utils.processor import Processor

REF = "localhost/qualification/example:latest"
SOURCE = "oci:/var/tmp/qualification/source"


def generate(system=None, selection=None, filesystem="xfs"):
    finals = {"disk": {"auto": {"disk": "/dev/vdb"}, "filesystem": filesystem,
                       "btrfsSubvolumes": filesystem == "btrfs"}, "hostname": "canary"}
    finals.update(selection or {})
    recipe = {"imgref": REF, "local_imgref": SOURCE, **(system or {})}
    return Processor.gen_install_recipe("unused", [finals], recipe)


@pytest.mark.parametrize("backend,bootloader,filesystem", [
    (False, "grub2", "xfs"), (True, "systemd", "ext4"),
    (False, "grub2", "ext4"), (True, "systemd", "btrfs"),
])
def test_top_level_contract_preserves_independent_fields(backend, bootloader, filesystem):
    recipe = generate({"composeFsBackend": backend, "bootloader": bootloader,
                       "filesystem": filesystem})
    assert recipe["composeFsBackend"] is backend
    assert recipe["bootloader"] == bootloader
    assert recipe["filesystem"] == filesystem
    assert recipe["image"] == SOURCE
    assert recipe["targetImgref"] == REF


@pytest.mark.parametrize("filesystem", ["xfs", "ext4", "btrfs", "zfs"])
def test_disk_filesystem_is_not_silently_replaced(filesystem):
    assert generate(filesystem=filesystem)["filesystem"] == filesystem


def test_selected_image_fields_win_including_false():
    recipe = generate({"composeFsBackend": True, "filesystem": "btrfs", "bootloader": "systemd"},
                      {"selected_image": REF, "composefs_backend": False,
                       "image_filesystem": "ext4", "bootloader": "grub2"})
    assert (recipe["composeFsBackend"], recipe["filesystem"], recipe["bootloader"]) == (False, "ext4", "grub2")


def test_missing_selected_filesystem_does_not_overwrite_backend():
    recipe = generate({"images": [{"imgref": REF, "composefs": True, "filesystem": "ext4"}]},
                      {"selected_image": REF, "composefs_backend": False})
    assert recipe["filesystem"] == "ext4"
    assert recipe["composeFsBackend"] is False


def test_matching_image_metadata_not_first_unrelated_row():
    recipe = generate({"images": [
        {"imgref": "unrelated", "composefs": False, "filesystem": "xfs"},
        {"imgref": REF, "composefs": True, "filesystem": "ext4", "bootloader": "systemd"},
    ]})
    assert (recipe["filesystem"], recipe["composeFsBackend"], recipe["bootloader"]) == ("ext4", True, "systemd")


def test_unrelated_image_does_not_supply_backend():
    recipe = generate({"images": [{"imgref": "unrelated", "composefs": True, "filesystem": "btrfs"}]})
    assert (recipe["filesystem"], recipe["composeFsBackend"]) == ("xfs", False)


def test_ext4_override_clears_btrfs_subvolumes():
    recipe = generate({"filesystem": "ext4"}, filesystem="btrfs")
    assert recipe["filesystem"] == "ext4"
    assert recipe["btrfsSubvolumes"] is False


@pytest.mark.parametrize("system", [{"filesystem": "typo"}, {"bootloader": "typo"},
                                    {"composeFsBackend": "false"}, {"composeFsBackend": None}])
def test_invalid_metadata_fails_closed(system):
    with pytest.raises(ValueError):
        generate(system)


def test_invalid_disk_filesystem_fails_closed():
    with pytest.raises(ValueError):
        generate(filesystem="typo")


def test_unsupported_backend_is_preserved_for_fisherman_rejection():
    assert generate({"imageType": "ostree"})["imageType"] == "ostree"


def test_manual_layout_preserved():
    recipe = Processor.gen_install_recipe("unused", [{"hostname": "canary", "disk": {
        "/dev/vdb1": {"fs": "fat32", "mp": "/boot/efi"},
        "/dev/vdb2": {"fs": "ext4", "mp": "/"},
    }}], {"imgref": REF, "composeFsBackend": True, "filesystem": "ext4"})
    assert recipe["customMounts"][-1] == {"partition": "/dev/vdb2", "target": "/", "fstype": "ext4"}
    assert recipe["composeFsBackend"] is True


def test_nested_catalog_inherits_storage_and_expands_registry_tag():
    recipe = generate({"images": [{"registry": "localhost/qualification/example",
                                   "composefs": True, "filesystem": "ext4",
                                   "bootloader": "systemd", "children": [{"tag": "latest"}]}]})
    assert (recipe["filesystem"], recipe["composeFsBackend"], recipe["bootloader"]) == ("ext4", True, "systemd")


@pytest.mark.parametrize("key", ["filesystem", "imageType", "bootloader", "flatpakVarPath"])
@pytest.mark.parametrize("value", [None, False, 0, []])
def test_falsey_non_string_metadata_fails_closed(key, value):
    with pytest.raises(ValueError):
        generate({key: value})


def test_unrelated_nested_catalog_cannot_supply_parent_metadata():
    recipe = generate({"images": [{"registry": "unrelated/image", "composefs": True,
                                   "filesystem": "btrfs", "children": [{"tag": "latest"}]}]})
    assert (recipe["filesystem"], recipe["composeFsBackend"]) == ("xfs", False)


def test_nested_second_catalog_child_overrides_parent():
    recipe = generate({"images": [
        {"registry": "unrelated/image", "children": [{"tag": "latest"}]},
        {"registry": "localhost/qualification/example", "composefs": False,
         "filesystem": "xfs", "children": [{"tag": "latest", "filesystem": "ext4", "composefs": True}]},
    ]})
    assert (recipe["filesystem"], recipe["composeFsBackend"]) == ("ext4", True)


def test_nvidia_source_rewrite_does_not_lose_base_metadata(monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "bootc_installer.core.system",
                        SimpleNamespace(Systeminfo=SimpleNamespace(has_nvidia_gpu=lambda: True)))
    recipe = generate({"images": [{"imgref": REF, "filesystem": "ext4", "composefs": True}]},
                      {"selected_image": REF, "nvidia_imgref": REF + "-nvidia"})
    assert (recipe["filesystem"], recipe["composeFsBackend"]) == ("ext4", True)
    assert recipe["image"] == SOURCE
    assert recipe["targetImgref"] == REF + "-nvidia"


@pytest.mark.parametrize("images", [None, {}, [None], [False], [{"children": None}]])
def test_malformed_recipe_catalog_fails_with_actionable_error(images):
    with pytest.raises(ValueError):
        generate({"images": images})


@pytest.mark.parametrize("content", ['[]', '{"images": null}', '{"images": [null]}', '{broken'])
def test_malformed_host_catalog_fails_closed(monkeypatch, content):
    import io

    original = open

    def read(path, *args, **kwargs):
        if str(path).endswith('/bootc-installer/images.json'):
            return io.StringIO(content)
        return original(path, *args, **kwargs)

    monkeypatch.setattr('builtins.open', read)
    with pytest.raises(ValueError):
        generate()


def test_local_source_cannot_install_a_different_selected_image():
    with pytest.raises(ValueError, match='Local install source'):
        generate(selection={'selected_image': 'unrelated/image:latest'})


def test_local_source_without_explicit_target_fails_closed():
    with pytest.raises(ValueError, match='Local install source'):
        generate({'imgref': ''}, {'selected_image': REF})
