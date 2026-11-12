# Pelagic features

Pelagic is a real Chromium browser (Qt WebEngine) with a built-in AI assistant and browsing agent, for Windows and
Linux. This page is the quick list; the [README](README.md) explains how to use each feature, and the
[CHANGELOG](CHANGELOG.md) says which version added what.

## AI assistant and agent
- **AI panel** (sparkle button, Ctrl+Shift+A): ask questions or describe a task. The agent opens pages, clicks,
  types and scrolls while you watch, then answers from what it found. Stop it any time.
- **Ask Pelagic AI** on any selected text from the right-click menu.
- **Bring your own key** for 25+ providers: Gemini, Anthropic, OpenAI, OpenRouter, Groq, Mistral, DeepSeek, xAI,
  Ollama, LM Studio and more, plus any OpenAI-, Anthropic- or Gemini-compatible endpoint. Keys are encrypted.
- **Token and cost tracking** for each task, and a **No context** option for repetitive tasks that sends only your
  request and always-on instructions.
- **Pelagic Local**: a rule-based helper for simple browser tasks with no AI, no network and no tokens.
- **Safety built in**: the agent never types passwords or sees card fields, asks before buying, sending, deleting
  or posting, treats page text as data rather than instructions, and hands CAPTCHAs back to you.
- **Password guard**: warns before you send the AI a message that looks like it contains a password.

## Automations (no AI needed)
- Watch a page and act when something happens: `refresh every 30 seconds until "in stock" appears and notify me`.
- Conditions: text appears or disappears, a number goes above or below a value, the page changes, a button or link
  appears, the URL or title contains something.
- Run in an invisible tab, survive restarts, and are managed from Menu → Automations.

## Tabs and windows
- Tabs on top with equal widths, a scrolling strip, tab search and reopen closed tabs (Ctrl+Shift+T).
- **Tab groups** with names and colours, collapsible, movable, and restored after a restart. Optional automatic
  grouping by site.
- **Sleeping tabs** free memory from tabs you haven't used for a while.
- **Split view**, **vertical tabs**, **workspaces** and tab hover previews.
- Pinned tabs, mute, duplicate, private windows and crash restore.

## Browsing
- Address bar autocomplete from history, bookmarks and search suggestions.
- Customisable **homepage**: shortcuts or most visited sites, ocean, colour or photo backgrounds, clock and date.
- **Bookmarks** with folders, site icons, a bookmarks bar and a bookmark manager (Ctrl+Shift+O).
- **History** page (including read-only access to Google Chrome's history) and a **reading list**.
- **Reader mode**, AI **page translation**, **screenshots** and **picture-in-picture**.
- **Downloads** manager (Ctrl+J) with pause, resume and retry.
- **Print** (Ctrl+P) and save as PDF.
- **Open files**: formatted Markdown, readable text and code files, PDFs and pictures.
- **YouTube downloads** as video or audio (personal use only).
- **Screen sharing** picker for Discord, Meet, Teams and others.
- **Spell check** in your language.

## Extensions, ad blocking and dark mode
- **Ad and tracker blocker** (EasyList and EasyPrivacy), with a blocked count and per-site pause.
- **Blocked domains, like Pi-hole**: block whole domains and their subdomains everywhere, with your own list,
  downloadable blocklists (hosts files and domain lists) and a never-block list.
- **Userscripts** from Greasy Fork and OpenUserJS, plus your own styles and scripts for chosen sites.
- **Extension gallery** of Pelagic's own extensions, installed with one click.
- **Dark mode for websites**, built in: darkens light sites, leaves dark ones alone, and can be turned off per site.

## Passwords, privacy and security
- **Saved passwords** with save and update prompts, autofill, and import from Google Password Manager or a
  Chrome, Edge or Firefox CSV.
- **Password checkup** for breached, reused and weak passwords (only part of a hash is ever sent).
- **Address and card autofill**; the card security code is never saved.
- Everything is encrypted with your Windows account, or with a key in the system keyring on Linux.
- **Proxy and VPN**: send browsing through a SOCKS5, HTTP or HTTPS proxy (a VPN service's proxy or Tor) or a PAC
  address, with WebRTC leak protection; or follow the computer's settings and VPN app.
- **Unsafe-site warnings** for known phishing and malware, checked on your computer.
- **Site permissions** page for camera, microphone, location, notifications and more.
- Clear browsing data (Ctrl+Shift+Del) and safe handling of self-signed certificates on local devices.

## Profiles and sync
- **Profiles**, each with its own passwords, history, bookmarks, cookies, tabs and automations.
- **Folder sync** through OneDrive, Google Drive or Dropbox for bookmarks, the reading list and history, with
  optional passphrase-encrypted sync of passwords, addresses and cards.

## Extras
- **DevTools** docked under the page (F12), element picker and page source.
- **Pelagic Playground**: hands-on challenges for every feature. Type `pelagic:playground` in the address bar or
  click the homepage logo five times.
