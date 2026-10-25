# Changes

## 1.1.0-beta.5

- Offer a default data-backup mode and an explicit full-removal mode before GUI confirmation.
- Full removal deletes all installation files and prior archives/backups identified by product and the exact original installation path; it creates no new backup.
- Restore pre-install shared settings and preserve changes owned by other installations in both modes.
- Refresh installed uninstall tools and app-list version without replacing original restoration snapshots.
- Document both choices and add isolated full-removal, history-scope, cancellation, and updater tests.

## 1.1.0-beta.4

- Interactive Install.cmd now asks for the installation folder after selecting the CD drive.
- Provide an editable path, Browse button, new-folder support, and cancellation without changing files.
- Keep explicit --target behavior for command-line users.
- Detect a different registered installation before copying CD files; require uninstalling it before changing locations.
- Document destination selection and changing drives; add destination-validation tests.

## 1.1.0-beta.3

- Recognize an already installed default destination and offer repair/launch in the interactive installer instead of an unexplained empty-directory error.
- Add `--repair`: restore app-list/OLE registration without recopying the application or replacing user preferences; retain original uninstall snapshots.
- Do not overwrite or repair a different registered installation.
- Clear physical-CD read-only attributes from installed writable files and profiles.
- Support read-only installed files during uninstall; restore original profile read-only attributes when recorded.
- Add repair, snapshot-preservation, ownership, and read-only regression tests.

## 1.1.0-beta.2

- Register the per-user installation in Windows 11 Installed apps with an uninstall command.
- Bundle a dedicated GUI/CLI uninstaller, and build a separate uninstaller-only ZIP.
- Snapshot old profile bytes and typed registry values before activation.
- Back up saved spots, changed/unknown files, and current profiles before removing owned files.
- Preserve settings/registry values subsequently owned by another installation.
- Refuse running related apps, reparse points, and out-of-root paths.
- Legacy installations can add the app-list entry; legacy removal archives the entire folder and restores only recorded old state.
- Add isolated uninstall tests and a full CD install-to-uninstall integration test.

## 1.1.0-beta.1

- Public-distribution layout separated from private CD extraction and diagnostic folders.
- Direct physical-CD/directory input; ISO is optional and its whole-image hash is not required.
- Validate 28 required media files by SHA-256 and decode all 44 DATA.Z members before installation.
- Per-user default install path, CD selection dialog, and no machine-specific paths.
- Refuse nonempty installation destinations and unsupported media/DLLs.
- No default SPF/SPG file-association changes.
- Source/release allowlist, license notices, build script, and tests without original product files.
- Full install simulation supports local CD fixtures with registry calls mocked.

## 1.0 (private prototype)

- Verified native map display, zoom, address search, and launcher restart on one Windows 11 x64 Japanese PC.
- MFCO30 import redirection and prelaunch of the original SDBOLE32 server.
- Prototype archive and development folders are not public-distribution inputs.
