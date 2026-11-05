# Claude setup for Pelagic

## Working folder
The live source and Git checkout is `C:\Users\Justice\.gemini\antigravity\scratch\AtlasBrowser` on the owner's Windows PC, tracking `origin` = https://github.com/TuppySeal/Pelagic.git, branch `main`. The same folder holds local build output (`build/`, `dist/`, launcher exes), which is ignored by Git and must not be deleted.

## How Claude reaches it
- Claude's cloud threads in the "AI Browser" project can read and write files in this folder through folder access, but folder access cannot run commands, so it cannot run Git.
- Git commands are run through a Claude Code Remote Control session started on this PC in this folder. That session uses the PC's existing Git install and Git Credential Manager sign-in; Claude never sees or stores the credentials.
- Verified on 2026-11-05 with: `git status`, `git fetch`, `git add docs/CLAUDE_SETUP.md`, `git commit`, `git push origin main` (this file's commit). Git version: `git version 2.56.0.windows.4`.

## Git commands Claude uses
`git status`, `git diff`, `git log`, `git fetch`, `git pull --ff-only`, `git add <specific files>`, `git commit -m ...`, `git push origin main`. Never `git push --force`, history rewrites, or `git add -A` without reviewing the staged list.

## How future changes get committed
1. The owner asks for a change in the project.
2. Claude edits the files, then runs the relevant tests in `tests/` and reviews `git status` and `git diff`.
3. Claude stages only the files for that change and commits with a descriptive message.
4. Claude pushes to `origin main` when the request calls for publishing it, and reports the commit hash.
5. Installers stay in GitHub Releases, not in Git. Secrets, profiles and browsing data never get committed (see CLAUDE.md).
