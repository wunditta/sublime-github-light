# Changelog

Format: [Keep a Changelog](https://keepachangelog.com), versions: [Semantic Versioning](https://semver.org).

## [Unreleased]

### Added

* **GitHub: Diff File** (menu, text area, side bar, command palette; current or clicked file): the difference between the local file and its version on the branch head as a unified diff in a scratch tab with diff highlighting; the way to look at a Conflict, Commit, Download or (older) file before deciding

* Setting `output_results` (replaces `show_panel_on_output`, the old key is still read): "console" (the output panel, as before), "tab" (a scratch tab "GitHub Light" that collects the output of all actions until it is closed), "none"

* Side bar: "GitHub: Sync Folder" and "GitHub: Download Folder" on a folder, "GitHub: Download File(s)" on files, limited to the clicked items like Commit Folder/File; the confirmation dialog and `conflict_and_delete_files` apply as usual

* **Sync**: a three-way comparison per file (hash at the last sync in the state file, local hash, hash in the branch) decides what happens: changed on one side only → that side wins (download or commit); new on one side → added on the other; deleted on one side since the last sync → deleted on the other; changed on both sides → a conflict. Download and Commit stay as the one-way operations and use the same comparison, limited to their direction
* Every file gets a category: Unchanged, Download, Download (new), Commit, Commit (new), Conflict, Unknown (on both sides, never synced: handled like a conflict, the newer version suggested; "Both (new)" under the setting "both"), Delete local, Delete GitHub, Keep local/GitHub (prefs) (a deletion the setting forbids), Commit (older) / Download (older) (a one-way operation whose own side is the older one: suggested is to keep the newer version, OK in the confirmation dialog overwrites it anyway)
* Setting `conflict_and_delete_files` (replaces `delete_files`, the old key is still read): what happens with conflicts and deletions, see the settings file: "never", "both" (the newer file keeps its name, the older is kept locally as `name (YYYY-MM-DD HH_MM).ext`, never synced), "ask", "sync", "always", "chaos"
* The confirmation dialog (`confirm_file_transfer`, also forced by the setting above): the counts per category and a hint to the console; **OK** / **Cancel**, and **As Suggested** only when there are conflicts to decide ("ask", "sync"): then OK means for Download and Commit the operation's direction for every conflict, for Sync one question per conflict (keep local / keep GitHub / keep both / skip, each also "for all remaining"), and As Suggested takes the suggestions (the newer version wins). Without the dialog the conflicts are asked one by one; with "always"/"chaos" the "(older)" files go as requested
* The console lists the plan, one line per file, category and path in fixed columns, conflicts with their suggestion behind (`Conflict:   core.md   -> suggested: commit (local newer)`), the number of unchanged files as the last line, below it the GitHub compare link when there are files to look at; then, once the dialogs are answered, `Starting transfer now...` and after the run one line per file done (`Downloaded:`, `Committed:`, `Deleted local:`, `Deleted GitHub:`, a resolved conflict with the name of its dated copy behind), then `Finished` (with the commit id) or `Error:` with the files and reasons
* Backup: a local file is copied into the `_backup` folder next to the state file before it is deleted or overwritten (not with "chaos"); on GitHub the history is the backup

### Changed

* The compare link stands after the file list of Sync, Download, Commit and Status as two unindented lines, `View diffs for Conflict, Download, Commit (older) on GitHub` (naming only the categories present out of Conflict, Unknown, Download and Commit (older)) and the URL below; it is shown only when the plan holds such a file, as these are the files that have another version on GitHub (it is GitHub's comparison of the last-sync commit with the branch head, one page for all files, not a per-file link)

* Sync, Download, Commit, Status, Create Release and Move Tag write "… started..." to the console at once, preceded by an empty line, so the wait for GitHub is visible and one action is set off from the last (not with `output_results: "none"`); the console scrolls so that the action's first line is the first visible line and stays there while the output grows

* Status shows what a Sync would do, in the same categories as the plan, with the compare link under the same rule (was: its own list of unchanged / to commit / conflicts / untracked / new on GitHub / missing locally)

* Right-click menu captions start with "GitHub: " (GitHub: View, Blame, History, Commit File, Commit Folder); no menu entry carries an ellipsis any more, since whether a dialog follows depends on the setting


* Menu captions are in the menu files; `description()` in the code only for the side-bar commit of one or several files

* Key Bindings menu entry: `user_file` written as `${packages}/User/Default (${platform}).sublime-keymap` (Package Control's checker)

* `confirm_commit` is renamed `confirm_file_transfer`, as it governs the confirmation dialog of Sync, Download and Commit alike (the old key is still read); the former commit dialog (Commit / Open on GitHub / Cancel) and Download's question (Overwrite / Skip them / Cancel) are replaced by it
* A file counts as changed on both sides (a conflict) not only by the hashes in the state file but also by the dates, because the state file can be wrong: Download does not overwrite a local file that was saved after the last GitHub commit touching it, and Commit treats a GitHub version that is younger than the local file as changed on GitHub; both cases go through the confirmation dialog
* `Default.sublime-keymap` lists every command, those without a default key commented out with empty keys, ready to copy into the user key bindings
* The last line of a Download reads "Missing on GitHub (local files exist): …"
* Release notes tab: a banner with *Create release* / *Cancel* links; Ctrl+S creates the release as well as Ctrl+Enter
* **New GitHub Project below…** (side bar, right-click on a folder): asks for a name, creates the sub-folder `<name>` with the project file `<name>.sublime-project` in it (folder `.`, the `github_light` settings block with `repository` to fill in), opens the project and the three-column Settings window; the repository itself is not created on GitHub
* **Settings** opens three columns when a project is open: the package's default settings (read-only), the user settings and the project file — so a project can be configured with the names and comments in view (default | user as before without a project)
* "ask_release_details" gets these values:
  * "all": asks for title and notes
  * "notes": the tag is used as title, the notes can be edited with the defaults pre-filled:
    * `"release_notes_from_changelog": false`: empty
    * `"release_notes_from_changelog": true`: from the `## [Unreleased]` section of `CHANGELOG.md`
  * "never": everything is filled with the default values of the option above

### Fixed

* Side bar: the restriction to the clicked files or folder compares local paths case-insensitively; before, a path spelled differently by Sublime and by the project (drive letter, case) made the run find nothing ("nothing to do" although Status listed files)

## [v1.0.0] - 2026-11-14

### First Release

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
    - an empty section asks: release anyway (empty notes) or cancel
  - `sublime_version_files`: Package Control's `messages/<tag>.txt` with the same notes
- `release_label`: latest / pre-release / none, or asked each time
- **Move Tag** and `moving_tag`: a tag like `v1` that follows the releases (for GitHub Actions)
- Right-click menus
  - text area: View / Blame / History on GitHub, Commit File to GitHub
  - side bar: Commit File / Folder to GitHub, History on GitHub
  - shown only inside the sync folder; menu-bar entries greyed out outside it
- Settings: `repository`, `branch`, `folder` (empty = the project's first folder), `folder_map` (`dot-github` → `.github`), `ignore`, `token`, `confirm_commit`, `ask_commit_message`, `ask_release_details`, `tag_prefix`

