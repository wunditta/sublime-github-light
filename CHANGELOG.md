# Changelog

Format: [Keep a Changelog](https://keepachangelog.com), versions: [Semantic Versioning](https://semver.org).

## [Unreleased]

## [v1.0.0] - 2026-11-14

### Firste Release
- **Download**: the branch into the project folder
  - changes detected by git blob hashes, last sync in `.github-sync-hash.json`
  - local changes are never overwritten without asking
- **Commit Current File** / **Commit All**
  - one commit through the REST API, no git needed
  - refused when GitHub changed a file since the last sync: Commit / Open on GitHub / Cancel
  - messages in GitHub's wording ("Add x.md", "Update 2 files"), every file listed as OK or Error
- **Status**: unchanged, to commit, conflicts, untracked, new on GitHub, missing locally
- **View / Blame / History Online** for the current file, at the cursor line
- **Create Release**
  - next patch / minor / major from the latest tag, `v1.0.0` if none
  - notes in an editor tab (Markdown, word wrap), Ctrl+Enter creates the release
  - `release_notes_from_changelog`: notes from the Unreleased section of `CHANGELOG.md`, section closed and committed first
  - `sublime_version_files`: Package Control's `messages/<tag>.txt` with the same notes
- **Move Tag** and `moving_tag`: a tag like `v1` that follows the releases (for GitHub Actions)
- Right-click menus
  - text area: View / Blame / History on GitHub, Commit File to GitHub
  - side bar: Commit File / Folder to GitHub, History on GitHub
  - shown only inside the sync folder; menu-bar entries greyed out outside it
- Settings: `repository`, `branch`, `folder` (empty = the project's first folder), `folder_map` (`dot-github` → `.github`), `ignore`, `token`, `confirm_commit`, `ask_commit_message`, `ask_release_details`, `tag_prefix`

