"""Probe the installed GNOME bundle, never the source checkout."""
import gettext
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

assert os.path.isfile('/.flatpak-info'), 'must run inside the installed Flatpak'
pkg = '/app/share/org.bootcinstaller.Installer'
sys.path.insert(0, pkg)
gettext.install('bootc_installer', '/app/share/locale')
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio

Gio.Resource.load(pkg + '/bootc-installer.gresource')._register()
Adw.init()
from bootc_installer.defaults.image import _make_icon
from bootc_installer.defaults.welcome import BootcDefaultWelcome
from bootc_installer.utils import branding, icons
from bootc_installer.views.done import BootcDone

assert branding.__file__.startswith('/app/'), branding.__file__
identity = branding.resolve()
assert identity.name == 'Example Packaged Remix', identity
assert identity.logo == '/usr/share/pixmaps/example fork #1.svg', identity
kind, path = icons.resolve_icon(identity.logo)
assert (kind, path) == ('file', '/run/host' + identity.logo)
assert os.path.isfile(path), path
controller = SimpleNamespace(recipe={'distro_name': identity.name, 'distro_logo': identity.logo})
info = {'name': identity.name, 'logo': identity.logo,
        'default_image_icon': 'unrelated-stock-icon',
        'welcome_title': 'Welcome to ' + identity.name}
with patch('bootc_installer.defaults.welcome._needs_bluetooth_pairing', return_value=False):
    welcome = BootcDefaultWelcome(controller, info, 'welcome', {})
done = BootcDone(controller)
done.set_result(True, None)
for label, image in [('welcome', welcome.page_header._icon),
                     ('done', done.page_header._icon), ('catalog', _make_icon(identity.logo))]:
    texture = image.get_paintable()
    assert texture is not None, label
    assert (texture.get_intrinsic_width(), texture.get_intrinsic_height()) == (120, 60), label
assert welcome.page_header.title == 'Welcome to ' + identity.name
assert done.page_header.title == identity.name + ' is installed'
done.set_result(False, None)
assert done.page_header.icon_name == 'dialog-error-symbolic'
print(json.dumps({'result': 'pass', 'sandbox': True, 'module': branding.__file__,
                  'name': identity.name, 'resolved_logo': path,
                  'decoded_widgets': ['welcome', 'done', 'catalog'], 'size': [120, 60]}))
