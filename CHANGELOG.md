# Changelog

Format: [Keep a Changelog](https://keepachangelog.com); versions follow [Semantic Versioning](https://semver.org).

## [Unreleased]

First release.

- **Download**, **Commit Current File**, **Commit All**, **Status**: one project folder in sync with one branch through the GitHub REST API, no git needed. Changes are detected by git blob hashes; `.github-sync-hash.json` remembers the last sync. A commit is refused when GitHub changed a file since then: the dialog marks those files and offers Commit / Open on GitHub (compare page) / Cancel.
- Commit messages in GitHub's wording ("Add x.md", "Update x.md", "Add 2 files, update 3 files"); every file is listed as "path: OK" or "path: Error …".
- **View / Blame / History Online** for the current file, at the cursor line.
- **Create Release**: next patch / minor / major version from the latest tag (`v1.0.0` if none), title and notes; optionally the notes come from `CHANGELOG.md`'s Unreleased section, which is closed under the new tag and committed first (`release_notes_from_changelog`), plus Package Control's `messages/<tag>.txt` (`sublime_version_files_from_changelog`).
- **Move Tag** and the `moving_tag` setting ("ask" / "major" / "minor" / fixed name / ""): a tag like `v1` that follows the releases (for GitHub Actions); the report names the version tags of old and new target.
- Right-click menus: text area (View / Blame / History on GitHub, Commit File to GitHub) and side bar (Commit File / Folder to GitHub, History on GitHub), shown only inside the sync folder; menu-bar entries are greyed out while the active file is outside it.
- Settings: `repository`, `branch`, `folder`, `folder_map` (`dot-github` → `.github`), `ignore`, `token`, `confirm_commit`, `ask_commit_message`, `ask_release_details`, `tag_prefix`.
