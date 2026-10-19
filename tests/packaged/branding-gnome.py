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

# Recipe generation only: no backend process, disk access or installation.
from bootc_installer.utils.processor import Processor

storage = Processor.gen_install_recipe('unused', [{
    'disk': {'auto': {'disk': '/dev/vdb'}, 'filesystem': 'ext4'},
    'hostname': 'canary',
}], {'imgref': 'localhost/qualification/example:latest',
     'local_imgref': 'oci:/var/tmp/qualification/source',
     'composeFsBackend': True, 'bootloader': 'systemd', 'filesystem': 'ext4'})
assert storage['filesystem'] == 'ext4'
assert storage['composeFsBackend'] is True
assert storage['bootloader'] == 'systemd'
assert storage['image'] == 'oci:/var/tmp/qualification/source'
assert storage['targetImgref'] == 'localhost/qualification/example:latest'
print(json.dumps({'storage_contract': 'pass', 'filesystem': storage['filesystem'],
                  'composeFsBackend': storage['composeFsBackend'],
                  'source_target_separate': True, 'installation_executed': False}))

# Build the real wizard against a valid host catalog with a root-level leaf.
# This catches constructor crashes that isolated Gtk.Image probes cannot.
import tempfile

from bootc_installer.core.system import Systeminfo
from bootc_installer.utils.recipe import RecipeLoader
from bootc_installer.views.progress import BootcProgress
from bootc_installer.windows.main_window import BootcWindow

with tempfile.TemporaryDirectory() as directory:
    recipe_path = directory + '/recipe.json'
    with open(recipe_path, 'w') as stream:
        json.dump({'log_file': directory + '/wizard.log',
                   'imgref': 'localhost/qualification/example:latest',
                   'steps': {'welcome': {'template': 'welcome'},
                             'image': {'template': 'image'}}}, stream)
    application = Adw.Application(application_id='org.bootcinstaller.Installer.Probe',
                                  flags=Gio.ApplicationFlags.NON_UNIQUE)
    application.register(None)
    with patch.dict(os.environ, {'BOOTC_CUSTOM_RECIPE': recipe_path}), \
            patch.object(RecipeLoader, '_host_live', return_value=(False, '')), \
            patch.object(Systeminfo, 'probe', return_value=None), \
            patch.object(BootcProgress, 'start', side_effect=AssertionError('installation forbidden')):
        window = BootcWindow(application=application)
        window.present()
        from gi.repository import GLib
        for _ in range(50):
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
        assert window.get_mapped(), 'real wizard did not map'
        assert window.carousel.get_n_pages() >= 2
        pages = window._BootcWindow__builder.widgets
        welcome_page = next(page for page in pages if isinstance(page, BootcDefaultWelcome))
        assert identity.name in welcome_page.page_header.title
        assert welcome_page.page_header._icon.get_paintable() is not None
        from bootc_installer.defaults.image import BootcDefaultImage
        image_page = next(page for page in pages if isinstance(page, BootcDefaultImage))
        assert image_page.get_finals()['selected_image'] == 'localhost/qualification/example:latest'
        window.close()
print(json.dumps({'packaged_window': 'pass', 'catalog_root_leaf': True,
                  'installation_executed': False}))
