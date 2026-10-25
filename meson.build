project('org.bootcinstaller.Installer',
          version: '3.0.0',
    meson_version: '>= 0.59.0',
  default_options: [ 'warning_level=2',
                     'werror=false',
                   ],
)

python = import('python')
py_inst = python.find_installation('python3')

# Runtime Python dependency: segno draws the phone companion's QR code. The
# app still runs without it (the page offers the link instead), so this only
# warns. The Flatpak installs it as the python3-segno module.
if not python.find_installation('python3', modules: ['segno'], required: false).found()
  warning('python3 module "segno" not found: the phone companion page will show no QR code')
endif

i18n = import('i18n')

gnome = import('gnome')

subdir('data')
if get_option('build-fisherman')
  subdir('fisherman')
endif
subdir('bootc_installer')
subdir('po')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
