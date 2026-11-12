# Changelog

All notable changes to Pelagic are listed here, newest first. Downloads for each version are on the
[Releases page](https://github.com/TuppySeal/Pelagic/releases). For everything Pelagic can do, see
[FEATURES.md](FEATURES.md).

Versions are three-part numbers, x.y.z, the same for Windows (`PelagicSetup-<version>.exe`) and Linux
(`Pelagic-<version>-linux-x86_64.tar.gz`), with release tags `v<version>`. The first release, 1.0.0.0, was the only
one numbered with four parts.

<!--
How to add a version:
1. Put changes under "Unreleased" as you make them, in the sections below (delete empty sections).
2. When you publish a release, rename "Unreleased" to "[x.y.z] - YYYY-MM-DD", add a fresh empty
   "Unreleased" above it, and add a link for the new version at the bottom of this file.
Sections: Added (new features), Changed (existing features that work differently), Fixed (bugs),
Removed (features taken out), Security (anything that affects safety or privacy).
-->

## [Unreleased]

### Added
- **Always-on instruction sets**: keep several named sets (one per activity), switch between them from the AI
  panel, and pause or resume them with the *Always-on* tick box. Your existing instructions become the first set.
- **The agent can group tabs**: into a named, coloured group, by site, or ungroup them; it also sees which group
  each tab is in.
- **No context** in the AI panel's Options and usage: for repetitive tasks, sends only your request and your
  always-on instructions. The agent still sees the page it's working on but remembers only its last step; questions
  leave out earlier messages, page text and notes.
- **Formatted text from the AI agent**: the agent can paste text with formatting (bold, italics, headings, lists,
  links, paragraphs), written as Markdown or HTML, into rich text editors, including ones inside other sites'
  frames. Plain text boxes get the text without the markup, and your clipboard isn't used.
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
- The AI agent can type a whole block of text into a field that has no id in its element list, such as a rich text editor
  (TinyMCE) inside another site's frame: it clicks into the field, then types the text in one action instead of
  one key at a time. Password and card fields are still refused.

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
