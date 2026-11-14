# Changelog

Format: [Keep a Changelog](https://keepachangelog.com); versions follow [Semantic Versioning](https://semver.org).

## [Unreleased]

First release.

- **Download**, **Commit Current File**, **Commit All**, **Status**: one project folder in sync with one branch through the GitHub REST API, no git needed. Changes are detected by git blob hashes; `.github-sync-hash.json` remembers the last sync. A commit is refused when GitHub changed a file since then, with *Commit anyway* / *Open on GitHub* (compare page) / *Cancel*.
- **View / Blame / History Online** for the current file, at the cursor line.
- **Create Release**: next patch / minor / major version from the latest tag (`1.0.0` if none), title and notes; optional notes from `CHANGELOG.md`'s Unreleased section, which is closed under the new version and committed first (`release_notes_from_changelog`), and Package Control's `messages/<version>.txt` (`sublime_version_files_from_changelog`).
- **Move Tag** and the `moving_tag` setting: a tag like `v1` that follows the releases (for GitHub Actions).
- Right-click menus: text area (View / Blame / History Online, Commit This File) and side bar (Commit This File / Folder / All, History Online), shown only inside the sync folder.
- Settings: `repository`, `branch`, `folder`, `folder_map` (`dot-github` → `.github`), `ignore`, `token`, `confirm_commit`, `ask_commit_message`, `ask_release_details`, `tag_prefix`.
