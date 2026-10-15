pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
utilsdir = join_paths(pkgdatadir, 'bootc_installer/utils')

sources = [
  '__init__.py',
  'finals.py',
  'run_async.py',
  'processor.py',
  'recipe.py',
  'builder.py',
  'progress_parser.py',
  'codec_check.py',
  'phone_companion.py',
  'fisherman_runner.py',
  'fisherman_session.py',
  'field_check.py',
  'branding.py',
  'copy.py',
  'sha512crypt.py',
]

# The demo mode (BOOTC_DEMO=1) replays this byte-identical copy of
# shared/progress/dry-run-transcript.ndjson; views/progress.py reads it
# from here.
install_data(sources + ['dry-run-transcript.ndjson'], install_dir: utilsdir)
