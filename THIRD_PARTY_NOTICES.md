# Third-party notices

`setup30.py` is vendored, without modification, from:

- Project: https://github.com/ostrich/setup30
- Commit: `0d6965e7e979abcc63fb6333b47df89cf2961190`
- License: MIT; full notice in `LICENSE-setup30.txt`.
- Copyright (c) 2026 contributors.

The installer calls `parse_entries(..., scan_tail_bytes=65536)` so that all 44
members of the supported CD archive are found. The upstream default scan window
is smaller. No original MapFan files are part of this source tree or release.

Python and 7-Zip are optional/external prerequisites as described in README.md;
neither is bundled. Windows/.NET and OLEDLG.DLL are supplied by the user's OS;
no Microsoft runtime DLL is bundled in this release.
