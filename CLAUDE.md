# Pelagic development

This is the source repository for TuppySeal/Pelagic. Read README.md and docs/DEVELOPMENT.md before changing build or repository layout.

## Layout
- atlasbrowser/: Python app and bundled assets. Preserve this package name; the launcher and installer depend on it.
- tests/: existing standalone regression scripts.
- launcher/: Windows C launcher, manifests and resource definitions.
- packaging/: PyInstaller and Inno Setup definitions and Windows build script.
- playground/: standalone playground page.
- website/: download website and its images.
- docs/: development and contribution instructions.

## Future changes and Git
The owner requested that Claude be able to commit future requested Pelagic changes. Work in this Git checkout, inspect git status first, and leave unrelated edits intact. Use the configured origin https://github.com/TuppySeal/Pelagic.git and the existing Git Credential Manager authentication. Never read, print, copy, embed, or upload credentials.

For each requested change: inspect the diff, run relevant existing tests, stage only files belonging to that change, and make a descriptive commit. Push to origin when the user's task calls for publishing/synchronizing the change. Never force-push or rewrite existing published commits. If another contributor updated origin, fetch and resolve the divergence without discarding work.

Keep installers and updater executables in GitHub Releases, not Git history. Keep browser profiles, API keys, personal browsing data, caches and build environments out of commits. The .gitignore is a safeguard, not a substitute for reviewing staged files. The TLS keys in tests/certificate_selftest.py and fake API key in tests/secrets_test.py are deliberate local test fixtures.

The developer's source folder and live app may coexist: never delete build output or user data merely to clean Git status. Do not change access permissions, create credentials, or disable approval/security controls to enable Git. Report authentication or unavailable shell access explicitly.
