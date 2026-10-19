"""Real GTK image decoding; run under Xvfb with the built GResource."""
from types import SimpleNamespace
from unittest.mock import patch

from bootc_installer.defaults.image import _make_icon
from bootc_installer.defaults.welcome import BootcDefaultWelcome
from bootc_installer.views.done import BootcDone, apply_icon
from bootc_installer.widgets.page_header import BootcPageHeader


def test_absolute_svg_decodes_for_header_and_catalog(tmp_path):
    logo = tmp_path / 'fork.svg'
    logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
                    '<rect width="32" height="32" fill="red"/></svg>')
    header = BootcPageHeader()
    apply_icon(header, str(logo))
    assert header._icon.get_paintable() is not None
    assert _make_icon(str(logo)).get_paintable() is not None


def test_welcome_product_logo_beats_unrelated_catalog_default():
    controller = SimpleNamespace(recipe={'distro_name': 'Example OS'})
    info = {'name': 'Example OS', 'logo': 'example-logo',
            'default_image_icon': 'unrelated-logo', 'welcome_title': 'Welcome to Example OS'}
    with patch('bootc_installer.defaults.welcome._needs_bluetooth_pairing', return_value=False):
        welcome = BootcDefaultWelcome(controller, info, 'welcome', {})
    assert welcome.page_header.icon_name == 'example-logo'
    assert welcome.page_header.title == 'Welcome to Example OS'


def test_live_completion_uses_configured_logo_and_name():
    controller = SimpleNamespace(recipe={'distro_name': 'Example OS', 'distro_logo': 'example-logo'})
    done = BootcDone(controller)
    done.set_result(True, None)
    assert done.page_header.icon_name == 'example-logo'
    assert done.page_header.title == 'Example OS is installed'
    done.set_result(False, None)
    assert done.page_header.icon_name == 'dialog-error-symbolic'


def test_neutral_welcome_keeps_catalog_default():
    controller = SimpleNamespace(recipe={})
    info = {'logo': 'org.bootcinstaller.Installer', 'default_image_icon': 'catalog-logo'}
    with patch('bootc_installer.defaults.welcome._needs_bluetooth_pairing', return_value=False):
        welcome = BootcDefaultWelcome(controller, info, 'welcome', {})
    assert welcome.page_header.icon_name == 'catalog-logo'
