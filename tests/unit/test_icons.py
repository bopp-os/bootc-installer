"""Logo inputs work identically in native and Flatpak catalog/header views."""
from unittest.mock import Mock, patch

import pytest

from bootc_installer.utils.icons import resolve_icon, set_image_icon


@pytest.mark.parametrize('spec,kind,value', [
    ('resource:///org/example/logo.svg', 'resource', '/org/example/logo.svg'),
    ('example-logo-symbolic', 'theme', 'example-logo-symbolic'),
    ('/usr/share/example/logo.svg', 'file', '/run/host/usr/share/example/logo.svg'),
    ('/etc/example/logo.png', 'file', '/run/host/etc/example/logo.png'),
    ('/run/host/usr/share/logo.svg', 'file', '/run/host/usr/share/logo.svg'),
    ('/app/share/logo.svg', 'file', '/app/share/logo.svg'),
    ('/home/live/logo.png', 'file', '/home/live/logo.png'),
])
def test_flatpak_resolution(spec, kind, value):
    assert resolve_icon(spec, in_flatpak=True) == (kind, value)


@pytest.mark.parametrize('spec', ['', None, 12])
def test_empty_or_invalid_spec(spec):
    assert resolve_icon(spec) is None


def test_native_file_is_unchanged():
    assert resolve_icon('/usr/share/logo.svg', in_flatpak=False) == ('file', '/usr/share/logo.svg')


@pytest.mark.parametrize('spec,method,value', [
    ('resource:///org/example/logo.svg', 'set_from_resource', '/org/example/logo.svg'),
    ('example-logo', 'set_from_icon_name', 'example-logo'),
    ('/usr/share/logo.svg', 'set_from_file', '/run/host/usr/share/logo.svg'),
])
def test_gtk_image_dispatch(spec, method, value):
    image = Mock()
    with patch('bootc_installer.utils.icons.os.path.exists', return_value=True):
        set_image_icon(image, spec)
    getattr(image, method).assert_called_once_with(value)
