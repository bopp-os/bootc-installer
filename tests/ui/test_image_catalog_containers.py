"""Both root leaves and grouped leaves are valid image catalogs."""
from types import SimpleNamespace
from unittest.mock import patch

from bootc_installer.defaults import image


def test_root_and_grouped_leaves_use_their_container_api():
    ref = 'localhost/example:latest'
    tree = [
        {'name': 'Root product', 'imgref': ref, 'filesystem': 'ext4', 'composefs': True},
        {'name': 'Other products', 'children': [{'name': 'Nested', 'imgref': 'localhost/other:latest'}]},
    ]
    controller = SimpleNamespace(recipe={})
    with patch.object(image, '_IMAGE_TREE', tree), patch.object(image, '_DEFAULT_IMAGE', ref):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    leaves = page._BootcDefaultImage__leaf_rows
    assert len(leaves) == 2
    assert leaves[0][0].get_parent() is page.list_images
    assert leaves[1][0].get_parent() is not page.list_images
    finals = page.get_finals()
    assert finals['selected_image'] == ref
    assert finals['image_filesystem'] == 'ext4'
    assert finals['composefs_backend'] is True
