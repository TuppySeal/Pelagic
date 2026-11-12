# Pelagic

**[Features](FEATURES.md)** · **[Changelog](CHANGELOG.md)** · **[Download](https://github.com/TuppySeal/Pelagic/releases)** · **[Website](https://pelagicbrowser.app)**

Source and development instructions: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). Claude's repository workflow is in [CLAUDE.md](CLAUDE.md). Download the Windows installer from [Releases](https://github.com/TuppySeal/Pelagic/releases).


A real Chromium browser (Qt WebEngine) with a built-in AI assistant and browsing agent. Not a script driving someone else's browser: tabs, address bar, history, bookmarks, downloads, find, private windows, dev tools and PDF export are all native.

## Run
`Pelagic.exe` (what the Desktop shortcut opens; Windows shows it as Pelagic with its own icon), `run.bat`, or `python -m atlasbrowser`. `Pelagic.exe` is a tiny launcher that runs `-m atlasbrowser` with your installed Python; its source is in `launcher/` (set `PELAGIC_PYTHON` if Python lives somewhere unusual). Needs Python 3.10+ and `pip install -r requirements.txt`.

**Linux**: unpack `Pelagic-<version>-linux-x86_64.tar.gz` and run `./install.sh` (installs into `~/.local`, adds Pelagic to the applications menu; `./install.sh --remove` uninstalls). From source: `./run.sh` or `python3 -m atlasbrowser`. Browsing data lives in `~/.local/share/AtlasBrowser`. Saved passwords, cards and API keys are encrypted with a key kept in the system keyring (GNOME Keyring, KWallet, KeePassXC); without one Pelagic warns and won't save them, unless you start it with `PELAGIC_PASSWORD_STORE=basic` to keep the key in a file only your user can read. Install `ffmpeg` from your distribution for HD and MP3 YouTube downloads (optional). The prebuilt tarball is built on Ubuntu 24.04 (glibc 2.39), so it needs a distribution at least that new; on older ones build from source with `packaging/build_linux.sh`.

Qt WebEngine needs some system libraries that desktop installs usually have but minimal installs may lack (without `libxcb-cursor0` you get *Could not load the Qt platform plugin "xcb"*). On Debian/Ubuntu: `sudo apt install libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libnss3 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2t64 libgbm1` (before Ubuntu 24.04 use `libasound2` instead of `libasound2t64`).

## AI
Click the sparkle button (Ctrl+Shift+A). Add keys under the gear. Keys are encrypted with Windows DPAPI (on Linux, with a key in the system keyring) and also read from env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, ...).

The panel is the **agent**: describe a task or ask a question; it opens pages, clicks, types and scrolls while you watch (purple glow on the page) and answers from what it finds. Stop any time. Right-click selected text for "Ask Pelagic AI".

The agent never tries to solve or get around CAPTCHAs. When one appears it stops and asks you to solve it in the page, then carries on when you press Send.

Providers: Gemini, Anthropic, OpenAI, OpenRouter, Groq, Mistral, DeepSeek, xAI, Together, Fireworks, Cerebras, SambaNova, NVIDIA NIM, Perplexity, Cohere, Hugging Face, GitHub Models, Hyperbolic, Nebius, SiliconFlow, Novita, Moonshot, Zhipu, Qwen, Ollama, LM Studio, plus any custom OpenAI-/Anthropic-/Gemini-compatible endpoint.

## Automations (no AI, no tokens)
- **Repeat until something happens**: `refresh every 30 seconds until "in stock" appears and notify me`, `check https://example.com every 10 minutes when price drops below 50`, `reload every minute until the page changes`. It runs in an invisible tab; the AI is only used if you add `and ask ai`, and then once, after the match.
- Menu → **Automations…** lists, creates, pauses, runs and deletes them. Watchers survive restarts.
- The agent can set these up itself (`watch` action) so it never has to poll: you are always asked to approve it first, AI-created watchers need ≥15 s between checks, expire after 24 h, and only allow safe steps.
- Conditions are checked locally: text appears/disappears, number below/above (optionally near a word like Price), page changes, a button/link appears, URL/title contains.

Agent safety: never types passwords, asks before irreversible-looking clicks (buy/send/delete/post), treats page text as data not instructions, step limit, Stop button.

## Address bar autocomplete
As you type, the address bar fills in sites you've visited (press Backspace to keep just what you typed) and drops down matching history, bookmarks and your search engine's suggestions; arrow keys pick one. Turn it off in Settings → General → *Autocomplete searches and URLs*.

## Homepage
New tabs open on Pelagic's homepage. Click **+ Add shortcut** to pin a site there, or hover a shortcut and click ⋮ to rename or remove it. **✎ Customize** (bottom right) opens Settings → Homepage. There you can manage shortcuts or switch to *Most visited sites*, set the background (Pelagic ocean, a solid colour, or your own photo with darken and blur), and choose what shows: logo, tagline, search box, shortcuts, clock and date.

## Bookmarks
Click the star (or Ctrl+D) to bookmark a page; a box opens to rename it, change its address or pick a folder. Bookmarks show their site icons. Right-click one on the bookmarks bar to edit, move to a folder or delete it; right-click a folder to open all, rename or delete it; right-click empty space for *New folder…*. Ctrl+Shift+O opens the bookmark manager: double-click to open, F2 to rename, drag bookmarks into folders.

## Tabs and developer tools
- Tabs sit on top, above the address bar (like Firefox and Chrome). They're all one width and shrink evenly when there are many; past that, the strip scrolls. Right-click a tab to pin, duplicate, mute, group, or close others/to the right; middle-click closes. Ctrl+Shift+T reopens closed tabs; the ⌄ button searches open tabs.
- **Tab groups**: right-click → *Add tab to group*. Click the coloured label to collapse/expand; right-click it → *Edit name and color…* for a name box and colour dots (or *Color* → any preset or *Custom color…*), or to ungroup or close the group. Pinned tabs and groups come back after a restart.
- **Sleeping tabs**: tabs you haven't looked at for 30 minutes give back their memory (greyed icon) and reload when you click them. The tab you're on, pinned tabs, tabs playing sound, tabs with DevTools open and the AI's tab stay awake. Right-click a tab → *Put tab to sleep* to do it now (or *Wake tab* if it's asleep); right-click a group label → *Put group to sleep* / *Wake group*. Settings → General to turn it off or change the time.
- **Split view** (Ctrl+Shift+E), **vertical tabs** and **workspaces** are in the menu; hovering a tab shows a preview (Settings → General). The mouse wheel over the tab strip scrolls it without switching tabs. Drag a group's label to move the whole group.
- **DevTools** dock under the page, per tab: Ctrl+Shift+I (or F12), Ctrl+Shift+C for the element picker (press again to pick another element), DevTools' own ✕ closes them, right-click → *Inspect*. Ctrl+U shows the page source.
- Also: Ctrl+N new window, Ctrl+S save page, Ctrl+Shift+B bookmarks bar, Ctrl+PgUp/PgDn switch tabs, Ctrl+Shift+PgUp/PgDn move a tab, Ctrl+Shift+Del clear browsing data, F11 full screen.

## Extensions and ad blocker
The puzzle button in the toolbar shows how many ads/trackers were blocked on the page, pauses the blocker for a site, turns scripts on or off and runs their menu commands. **Manage extensions…** opens the Extensions page.

- **Ad blocker**: EasyList and EasyPrivacy, refreshed every few days (shared by all profiles; on/off and paused sites are per profile). Works in private windows too.
- **Userscripts**: click Install on Greasy Fork or OpenUserJS inside Pelagic and confirm. Common GM_* functions are supported; cross-site GM_xmlhttpRequest is not.
- **Your own styles and scripts**: Extensions → *New style or script…*, pick sites like `youtube.com`.

- **Dark mode for websites** (built in): makes light sites dark and leaves dark ones alone, including sites built from frames (school and work portals) and sites with strict security policies. Big drawings like Google Slides' slides and thumbnails keep their real colours, like photos. Puzzle menu → *Dark mode for websites: Turn off for this site* (it then offers *Turn on for this site*), or turn the whole extension off on the Extensions page.

Scripts are per profile and don't run in private windows. Chrome Web Store extensions aren't supported: Qt WebEngine's support for them is still experimental.

## Profiles
Click the round profile button (right of the menu) to open another profile, add one (for example Work) or manage them. Each profile has its own saved passwords, history, bookmarks, cookies and sign-ins (so each can use a different Google account), open tabs and automations. API keys and AI provider/agent settings are shared. Your original data is the first profile; other profiles live in `profiles\<id>` inside the data folder.

## Saved passwords
Menu → **Passwords…**. After you sign in, Pelagic offers to save the password (Save, Never for this site, Not now) and to update it when it changes. Click a login field on a saved site to pick an account and fill it. Passwords are encrypted with your Windows account (DPAPI) in `passwords.dat`, are never saved from private windows, and are never shown to or typed by the AI agent.

**Import from Google**: Passwords → Import → *Import from Google…* opens Google Password Manager; click *Download file* under Export passwords and Pelagic imports the file and deletes it immediately. CSV exports from Chrome, Edge or Firefox can be imported too (delete the CSV afterwards).

**Password checkup**: Passwords → *Checkup* → *Check passwords* finds saved passwords that appeared in data breaches, are reused, or are easy to guess. Only the first 5 characters of each password's SHA-1 hash are sent (to Have I Been Pwned), never the password.

## Addresses and cards
Menu → **Addresses and cards…**. After you send a form with an address or card, Pelagic offers to save it; click an address or card field later to fill the whole form. Cards show masked (Visa •••• 4242), the security code is never saved, and the AI never sees card fields. Encrypted like passwords in `autofill.dat`. Settings → Passwords to turn it off.

## Downloads, printing, permissions and spelling
- **Downloads** (Ctrl+J): progress, speed and time left, pause / resume / cancel, retry, open or show in folder, and a remembered list. *Ask where to save each file* can be turned off to save straight into Downloads.
- **Print…** (Ctrl+P) with the Windows print dialog; *Save page as PDF…* is in the menu too.
- **Site permissions…** lists every site you allowed or blocked (location, camera, microphone, notifications…) to change or reset.
- **Spell check**: Settings → General. The dictionary for your language downloads the first time; suggestions appear at the top of the right-click menu.

## Opening files

Menu → Open file… (Ctrl+O), drag a file onto the window, type its path in the address bar, or use "Open with
Pelagic". Markdown files are shown formatted (Show source switches to the text as written); text files (.txt, .log,
.json, .csv, code) get a readable view in the reader's Dark, Light or Sepia colours, and F5 reads the file again.
Web pages (.html), PDFs and pictures open as usual.

## YouTube downloads

Menu → Download video or audio… downloads the YouTube or YouTube Music video you're on (or a pasted link, Short or
playlist) as .mp4 video or audio, with progress and Cancel. It uses yt-dlp; HD video and .mp3 also need ffmpeg
(bundled as ffmpeg\ffmpeg.exe, or on PATH). Downloading is against YouTube's terms of service: personal use only.

## Unsafe-site warnings
Before opening a known phishing or malware address, Pelagic shows a red warning page (*Back to safety*, or *Details* → visit anyway for this session), and blocks downloads from listed sites. The lists (Phishing Army, OpenPhish, URLhaus) refresh every few hours and are checked on your computer; the sites you visit aren't sent anywhere. Google Safe Browsing itself needs a Google API key, so coverage is close to, not the same as, Chrome's. Settings → Privacy to turn it off.

## Blocked domains (like Pi-hole)
Settings → Privacy → **Edit blocked domains…** (or the puzzle menu → *Block example.com everywhere…*). Blocked domains and all their subdomains never load: not as pages (you get a *This site is blocked* page with *Unblock*) and not as images, scripts or frames inside other sites. Type your own domains (plain names, `*.example.com`, `||example.com^` or hosts-file lines like `0.0.0.0 example.com`), add downloadable blocklists such as StevenBlack's hosts file, OISD or Hagezi (refreshed every few days), and keep a *Never block* list. Per profile, works in private windows, and is separate from the ad blocker, so it still applies when the ad blocker is off or paused.

## Proxy and VPN
Settings → **Connection**. *Use the computer's settings* (the default) follows the system proxy settings and any VPN app you run (WireGuard, OpenVPN or your VPN service's app), which already covers everything Pelagic does. To send only Pelagic through a VPN or proxy, choose *Use this proxy server* and enter a SOCKS5, SOCKS4, HTTP or HTTPS proxy: many VPN services (Mullvad, NordVPN, Proton VPN, Private Internet Access, Windscribe) offer one, and Tor is SOCKS5 `127.0.0.1` port `9050`. A PAC address and *No proxy* are also available. *Test proxy* checks that the server answers. With SOCKS5, website names are looked up through the proxy too. WebRTC (video calls) is kept from going around the proxy. HTTP and HTTPS proxies can ask for a user name and password (saved encrypted, or asked for on first use); the browser engine can't sign in to SOCKS5 proxies. The setting is shared by all profiles and takes effect after a restart. With an HTTP proxy Pelagic's own requests (AI providers, list downloads) use it too; with SOCKS they connect directly.

## Sync
Settings → **Sync** → *Choose folder…*: pick a folder that OneDrive, Google Drive or Dropbox keeps in sync, then the same folder in Pelagic on your other computer. Bookmarks, the reading list and history (90 days) sync, including edits and deletions. Tick *Also sync passwords, addresses and cards* and enter the same sync passphrase on each computer to sync those too, encrypted with the passphrase (it never leaves the computer). Sync runs at start, every 5 minutes, when the last window closes, and with *Sync now*.

## Local HTTPS devices
For devices with self-signed certificates (for example, `https://10.0.255.1`), Pelagic shows a certificate warning. Choose **Trust for this session** only if you recognize the device and its certificate. Cancel is the default. Trust is limited to that host and certificate, and expires when Pelagic closes; private windows have separate trust decisions. A changed certificate requires another decision. Certificate details include the SHA-256 fingerprint.

## Test
`python tests/selftest.py` runs checks against mock AI servers and a local site (providers, retries, UI, agent loop, new tabs, vision, password refusal).

`python tests/automation_test.py` checks conditions, the Local interpreter, watchers (wake only on a match, one AI call after) and the AI `watch` action.

`python tests/extensions_test.py` checks the ad blocker, userscripts, site styles and per-profile/private-window rules.

`python tests/autocomplete_test.py` checks inline completion, history/bookmark/search suggestion rows and the on/off setting.

`python tests/tabs_test.py` checks equal-width tabs, pinning, groups, reopen closed tab, tab search and DevTools.

`python tests/features_test.py` checks bookmark editing/folders/icons, group colours, sleeping tabs, the CAPTCHA hand-off and dark mode.

`python tests/homepage_test.py` checks shortcuts, editing from the page, backgrounds, show/hide options and the Homepage settings tab.

`python tests/profiles_test.py` checks per-profile data, shared keys and settings, switching and deleting.

`python tests/passwords_test.py` checks the encrypted store, save/update prompts, autofill, private-window and agent rules, and the Google import.

`python tests/focused_typing_test.py` checks that the agent types whole blocks of text into focused editors inside other sites' frames, and still refuses password and card fields.

`python tests/network_test.py` checks the proxy setting (through a local test proxy), blocked domains in pages, page parts and private windows, downloaded blocklists, the blocked page and its Unblock link.

`python tests/chrome_parity_test.py` checks downloads, site permissions, printing, spell check, address and card autofill, the password checkup, unsafe-site warnings and the Sync tab.

`python tests/sync_test.py` checks folder sync between two computers: merging, edits, deletions, and passphrase-encrypted passwords and cards.

`python tests/certificate_selftest.py` checks certificate warnings and session trust against local HTTPS fixtures, including cancellation, navigation cleanup, private profiles, and changed certificates. It needs no additional dependencies.

`python tests/secretbox_test.py` checks how saved secrets are encrypted off Windows (system keyring, the refusal without one, and the `PELAGIC_PASSWORD_STORE=basic` key file) using a fake keyring, on any system.
