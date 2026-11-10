# Changelog

All notable changes to Pelagic are listed here, newest first. Downloads for each version are on the
[Releases page](https://github.com/TuppySeal/Pelagic/releases). For everything Pelagic can do, see
[FEATURES.md](FEATURES.md).

Versions use the same four-part number as the Windows installer (`PelagicSetup-<version>.exe`).

<!--
How to add a version:
1. Put changes under "Unreleased" as you make them, in the sections below (delete empty sections).
2. When you publish a release, rename "Unreleased" to "[x.y.z.w] - YYYY-MM-DD", add a fresh empty
   "Unreleased" above it, and add a link for the new version at the bottom of this file.
Sections: Added (new features), Changed (existing features that work differently), Fixed (bugs),
Removed (features taken out), Security (anything that affects safety or privacy).
-->

## [Unreleased]

### Added
- **Blocked domains (like Pi-hole)**: Settings → Privacy → *Edit blocked domains…*, or the puzzle menu → *Block
  example.com everywhere…*. Blocks whole domains and their subdomains as pages and inside other pages, with your own
  list, downloadable hosts-file or domain blocklists (StevenBlack, OISD, Hagezi), a *Never block* list, and a
  *This site is blocked* page with *Unblock*. Works in private windows and whether or not the ad blocker is on.
- **Proxy and VPN connection**: Settings → *Connection* sends Pelagic's browsing through a SOCKS5, SOCKS4, HTTP or
  HTTPS proxy (such as a VPN service's proxy or Tor) or a PAC address, with a bypass list, *Test proxy*, proxy
  sign-in for HTTP proxies, and WebRTC kept from going around the proxy. The default still follows the computer's
  settings and any VPN app. Takes effect after a restart.

### Changed

### Fixed

## [1.0.0.0] - 2026-11-05

The first public release of Pelagic.

### Added
- **Windows installer**: `PelagicSetup-1.0.0.0.exe`, with Start menu and Desktop shortcuts and an uninstaller.
- **Linux build** (added to this release on 2026-11-09): `Pelagic-1.0.0-linux-x86_64.tar.gz`. Unpack it and run
  `./install.sh`. Needs Ubuntu 24.04 (glibc 2.39) or newer; saved passwords, cards and API keys are protected by
  the system keyring.
- Everything listed in [FEATURES.md](FEATURES.md): a Chromium-based browser with the built-in AI assistant and
  browsing agent, automations, ad blocker and userscripts, built-in dark mode for websites, tab groups, sleeping
  tabs, split view, profiles, saved passwords with checkup, address and card autofill, folder sync, unsafe-site
  warnings, reader mode, YouTube downloads and more.
- Download site at [pelagicbrowser.app](https://pelagicbrowser.app).

[Unreleased]: https://github.com/TuppySeal/Pelagic/compare/v1.0.0.0...HEAD
[1.0.0.0]: https://github.com/TuppySeal/Pelagic/releases/tag/v1.0.0.0
