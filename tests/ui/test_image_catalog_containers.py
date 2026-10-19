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


def test_selected_catalog_identity_survives_channel_labels_and_other_os_selection():
    ref = 'localhost/base-family:latest'
    tree = [
        {'name': 'Example Remix', 'imgref': ref},
        {'name': 'Other OS', 'registry': 'localhost/other', 'children': [
            {'name': 'Stable', 'tag': 'stable'},
            {'name': 'Developer OS', 'registry': 'localhost/other-dev', 'children': [
                {'name': 'Latest', 'tag': 'latest'}]},
        ]},
        {'name': ' ', 'imgref': 'localhost/fallback:latest'},
    ]
    controller = SimpleNamespace(recipe={'distro_name': 'Example Remix'})
    with patch.object(image, '_IMAGE_TREE', tree), patch.object(image, '_DEFAULT_IMAGE', ref):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    leaves = page._BootcDefaultImage__leaf_rows
    for leaf, expected in zip(leaves, ['Example Remix', 'Other OS', 'Developer OS', 'Fallback'], strict=True):
        leaf[1].set_active(True)
        finals = page.get_finals()
        assert finals['pretty_name'] == expected
        assert finals['selected_image'] == leaf[2]
    page.row_custom.set_expanded(True)
    page.image_url_entry.set_text('localhost/custom-system:latest')
    assert page.get_finals()['pretty_name'] == image._imgref_to_pretty_name('localhost/custom-system:latest')


def test_recipe_extra_images_keep_names_and_unnamed_slug_fallback():
    controller = SimpleNamespace(recipe={'images': [
        {'name': 'Recipe Remix', 'imgref': 'localhost/family:latest'},
        {'imgref': 'localhost/unnamed:latest'},
    ]})
    with patch.object(image, '_IMAGE_TREE', []), patch.object(image, '_DEFAULT_IMAGE', ''):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    for leaf, expected in zip(page._BootcDefaultImage__leaf_rows, ['Recipe Remix', 'Unnamed'], strict=True):
        leaf[1].set_active(True)
        assert page.get_finals()['pretty_name'] == expected
