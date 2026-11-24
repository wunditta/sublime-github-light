# GitHub Light

A small GitHub client for Sublime Text 4 that needs **no git installation**. It keeps one folder of your Sublime project in sync with one branch of one GitHub repository through GitHub's REST API. Obviously meant for small projects of any sorts, where git would be a burden. Features:

* Sync, download or commit one or all files
* Create a release
* View a file's history or blame in the browser
* Nothing more — no branches, no merging, no history on local disk (but backups for deleted files).

Repository: https://github.com/wunditta/sublime-github-light

## How File Transfer Works

### Comparison first

Before any file transfer is done the actions are planned. This is done by comparing each file with a hash token from the last sync (to clearly identify changes on either side and deletions) or by comparing the modification dates (for unknown files).

**Hash**: The package compares **content hashes**, i.e. for every file it computes git's blob hash (`sha1("blob <size>\0" + content)`) locally and compares it with the hashes of the branch. The hashes of the last sync are kept in the local file `.github-sync-hash.json` inside the folder. This is how the package knows whether a file changed on local side, on GitHub, or on both. If anything would be overwritten, which should not happen without your consent, a confirmation is required.

### Output Panel

The output panel (console or full tab (setting `output_results`)) shows the status for each individual file (except if both sides are unchanged), and also suggests an action if the situation is unclear.

If files have another version on GitHub since the last commit (i.e. the categories "Conflict", "Unknown", "Download", "Commit (older)"), a link will be provided to GitHub’s comparison of all changes (diff).


### Confirmation Dialog

A dialog (if `confirm_file_transfer` is true, or if unresolvable situations) shows the changes only summarized for the observed **categories** with the number of concerned files. It offers three options:
* "OK": Download or upload forcefully (but still honoring the setting of `conflict_and_delete_files`). For syncing each individual conflict needs to be resolved manually.
* "As Suggested" (only present if suggestions available): Follows the suggestions as shown in the output panel.
* "Cancel"

| Category | Description
|---|---|
| Unchanged | on both sides
| Download / Commit | updates an existing file
| Download (new) / Commit (new) | adds a non-existing file
| Conflict | changed on both sides (suggestion depends on `conflict_and_delete_files`)
| Unknown | exist on both sides but never synced (so no hash token), thus an unknown situation (handled like a conflict)
| Both (new) | like Unknown, but `conflict_and_delete_files` specifies to keep both
| Delete local / Delete GitHub | will be deleted, as it was deleted on the other side (clearly identified with the hash tokens)
| Keep local (prefs) / Keep GitHub (prefs) | like Delete above, but the preferences forbid deletions (setting `conflict_and_delete_files`)
| Commit (older) / Download (older) | only for Commit or Download, when the own side is the older one (GitHub changed the file and you did not, or the other way round); suggested is to keep the newer version, so nothing is transferred, but "OK" in the confirmation dialog overwrites it anyway (with backup)

### File Transfer

Commits are made directly on the branch with the Git Data API (blobs → tree → commit → ref), one commit for all files you commit together. They appear on GitHub like any other commit, authored by the owner of the token.

After the transfer the output panel lists every file that was downloaded, committed or deleted.

The hash file (`.github-sync-hash.json`), the `_backup` folder, and the Sublime project and workspace files are not synced by default according to setting "ignore".

**Backups**: A local file is copied into `_backup` beside the project file (inside the repo folder when there is no project file) before it is deleted or overwritten (unless setting `conflict_and_delete_files` is "chaos"), and on GitHub the history keeps every version.

## How to Release

### Create Release

1. **Release tag**: Choose or enter a release tag. The latest version tag of the repository is read and these default options are offered: according to semantic versioning, each increasing one level:
    * "patch" (typicall for bug fixing; e.g. vx.x.1 -> vx.x.2)
    * "minor" (backwards compatible changes; e.g. vx.3.8 -> vx.4.0)
    * "major" (incompatible changes; e.g. v1.3.8 -> v2.0.0)
    * for the first release "v1.0.0" is offered)
2. **Release title** (depends on `ask_release_details`): Enter it in the input panel
3. **Relase notes** (depends on `ask_release_details`): Write them in an editor tab with Markdown highlighting.
    * **CHANGELOG.md**: If you maintain a CHANGELOG.md file (in the root of the repo folder) the editor tab is prefilled with the text from it. See below *Release notes from the changelog*
    * The top of the panel shows how to confirm the release (buttons, **Ctrl+S**, etc).
4. Tag and release are created on the branch head, marked according to the setting `release_label` (latest / pre-release / none). Note: publishing on the marketplace cannot be done that way, so you would need to enable this manually (only once, further releases keep it).
5. If you use moving tags (see section *Moving Tag*), then you can update it manually, or it is done automatically (see setting `moving_tag`).

### Moving Tag

A **moving tag** is a tag, which is redirected to another tag. It is called moving as in most cases it is updated to point to the latest release tag, or to the latest stable release. Normally it only shows the first or first two levels, such as `v1` or `v1.2`. Thus, a reference to the repo with the moving tag always gets the latest compatible version without the need to change the reference. Some projects offer a `latest` tag in the same spirit.

Moving tags are especially common for **GitHub Actions**, which users reference exactly this way (`uses: owner/action@v1`).  

Sublime's Package Control and most other package managers read the real version tags, so for a Sublime package or an ordinary repository you may not need this function.

### Release notes from the changelog

This package supports a `CHANGELOG.md` in the ["Keep a Changelog"](https://keepachangelog.com) form. The changes, which are yet unreleased, are written under section `## [Unreleased]` (tied to heading level 2). When `release_notes_from_changelog` is enabled, the release notes are taken from this section (as suggestion). After the release, the section is automatically renamed to `## [vx.y.z] - <today>` and adds a new heading `## [Unreleased]` above. If this section is not available a reminder dialog is shown.

When `sublime_version_files` is enabled, the same information is written to Package Control's `messages/v1.2.0.txt` (with a reference in `messages.json`).

```md
# Changelog

## [Unreleased]

### Added

* ...

### Changed

* ...

## [v1.0.2] - 2026-11-14

### Fixed
```

## Setup

1. Generate a repo access **Token**. On GitHub user navigation menu (top right):
    * Settings › Credentials › Fine-grained personal access tokens › Generate new token:
        * Resource owner: you
        * Repository access: whatever suits you
        * Permissions: Add > **Contents**, then change to **Read and write** (nothing else).
    * Copy the token (and save it somewhere really safe immediately, as you cannot get the token string again later).
2. Create the project, either by:
    * **Tools > GitHub Light > New Project...**: choose (or create) the project folder in the dialog; the project file `<folder name>.sublime-project` is written into it with the subfolder `repo` as the repo folder (`"repo_folder": "repo"`), and the settings window opens.
    * **Manually**: create the project folder on your local machine, save the Sublime project into it (Project > Save Project as...), add the folder to the project (Project > Add Folders to Project...) and set `"repo_folder"` to the subfolder that holds the files for GitHub (empty = the whole project folder).
3. Edit settings: Preferences > Package Settings > GitHub Light > Settings. You will see a 3 column layout:
    * Default settings (left; read only)
    * User settings (middle): copy from default and edit your settings, which should be applied to all projects
    * Project settings (right; same as Project > Edit Project): copy from default and edit your settings, which should be project specific
2. **User settings**: Settings apply to all projects. Put the token here and not in the project settings (double security: by default it does not matter, as the setting "ignore" prevents the project setting file to be uploaded to GitHub anyways; but if you change "ignore" in the wrong way, your access token would be published to GitHub; so put it here):
   ```jsonc
   {
       "token": "github_pat_…"
   }
   ```
3. **Project settings**: Project specific settings are typically the repository.
   ```jsonc
   {
       "folders": [
           { "path": "." }
       ],
       "settings": {
           "github_light": {
               // The repository with which the repo folder is synced with, as "owner/name" (e.g. "wunditta/sublime-github-light")
               "repository": "owner/repo_name",
               // Local folder for the downloaded TTS scripts, relative to the project file.
               // Defaults to the first listed folder above (folders)
               //"repo_folder": "",
               // Show the script folder as its own entry at the top of the side bar (see "Settings")
               "promote_script_folder": false,
           }
       }
   }
   ```
   Without `repo_folder` the first added folder of the project is the repo folder.
4. Tools › GitHub Light › **Sync** (or **Download**).

## Usage

* **Tools › GitHub Light**: main menu
* **Project**: most important commands are appended to the Project menu (only within GitHub Light project windows)
* **Command Palette**: shows as "GitHub Light: …".
* **Context menus** (right-click menus on **side bar**, **text area**, and **tabs**): depending on context and where you clicked some of the commands below are shown. Most of them only apply to files and folders in the project or repo folder.

| Command | What it does |
|---|---|
| **Diff Unsaved Changes…** | The unsaved changes of an open file against its saved state as a "diff" in a scratch tab (if you want it shown in the console use Sublime's "Show Unsaved Changes…"). |
| **Show Project Changes…** | Is basically a simulated Sync and lists the files and the actions, which a sync would use in the output panel. This functions is useful to get an overview of what are the differences between GitHub and your local files. |
| **Diff GitHub and Local in Sublime**<br>*(within menu item "File Review")* | Shows the difference between the local file and its version on GitHub as "diff" in a scratch tab. For unsaved files you are asked whether the current or the saved state should be compared. |
| **View Online** / **Blame Online**<br>*(within menu item "File Review")* | Opens the current file on GitHub at the line the cursor is on. |
| **History Online**<br>*(within menu item "File Review")* | Opens the commit history of the current file on GitHub. |
| **Sync** | Syncs in both directions by comparing the hash patterns since the last sync, so a conflict (both sides changed) or file deletions (an already synced file is missing) can be detected reliably. If there is no hash pattern this is not possible and you need to decide which side prevails (either for all files, or per file). Note: if or when a confirmation dialog is shown, and how unclear situations should be resolved, depend on the settings `conflict_and_delete_files` and `confirm_file_transfer`, but regardless of the chosen settings, no data can be lost silently (also see *Categories, conflicts and the confirmation dialog*). |
| **Download** | Works similar to "Sync" but only downloads files from GitHub to the repo folder. Pressing "OK" in the confirmation dialog downloads forcefully, regardless of which file is newer, or if there is an unresolved conflict (however, setting `conflict_and_delete_files` is still honored); for a safer way use "As suggested". |
| **Commit All / Current File** | Commits the current file or all files in the repo folder in the same way as download works (you will be asked to save unsaved files first). With `ask_commit_message` you can provide one. |
| **Create Release** | See *How to Release" for details*. |
| **Move Tag** | Creates or updates a pointer tag to the current branch head (see below *Moving Tag*). The name is asked for, prefilled per `moving_tag`. |

## Settings

### User Settings

```JSONC
{
    // Settings for GitHub Light package
    // Every setting here can be overridden for all projects in the package settings, or per project in the .sublime-project file

    // The repository with which the repo folder is synced with, as "owner/name" (e.g. "wunditta/sublime-github-light")
    "repository": "",

    // The branch for file transfer.
    "branch": "main",

    // The repo folder: the local working copy of the repository, what is synced. Empty = the first folder of the project
    // (the top one in the side bar). Absolute or relative path (a relative path is taken from the folder holding the
    // project file); New Project creates the subfolder "repo" and sets this.
    "repo_folder": "",

    // The repo folder as its own entry in the side bar (above the project folder), so it stands out:
    //     false = nothing is touched
    //     true = the entry is added and the project folder hides the repo folder (folder_exclude_patterns)
    //     "duplicate" = like above, but the project folder shows it too.
    // This does not take effect immediately in some cases. Just restart Sublime to update.
    // Existing entries are never moved or removed (set it to false and delete the entry yourself to undo).
    "promote_repo_folder": false,
    // Appended to the promoted folder's name (a space in between); empty = the plain folder name.
    "promoted_folder_badge": "\u2605",

    // Local folder names, which stand for differently named folders on GitHub (only first folder level).
    // This is e.g. necessary if you use an AI agent, which is not allowed to write to a local folder `.github`.
    "folder_map": {"dot-github": ".github"},

    // Files never downloaded or committed (glob patterns, matched against the full relative path and the file name).
    "ignore": [".github-sync-hash.json", "_backup", "*.sublime-workspace", "*.sublime-project", ".DS_Store", "Thumbs.db"],

    // Personal access token (GitHub > Settings › Credentials › Fine-grained personal access tokens › Generate new token, limited
    // to the repository, with the permission "Contents: Read and write".
    "token": "",

    // Shows a confirmation dialog with a summary of what will be done (number of files to write, skip, delete, conflicts, etc).
    // The output panel shows the full list of files with their actions (in case of ambiguity a suggestion is shown if possible).
    // Confirming with "OK" will do as requested (i.e. uploading or downloading, ignoring suggested actions, so e.g. an upload
    // will upload even if the file on GitHub is newer); a sync needs to ask per conflict. The button "As suggested" (only
    // appears if necessary) will follow the suggested actions as shown in the output panel. Note: the suggested actions depend
    // on the setting "conflict_and_delete_files". So, for example, if this setting is false, no confirmation dialog is shown,
    // except if the setting "conflict_and_delete_files" wants deletions or conflicts confirmed.
    "confirm_file_transfer": true,

    // Any file transfer is written to a state file, which allows to detect conflicts (both sides changed) and if a file was
    // deleted on one side (i.e. a file that exists on one side only, although it was synced before). This allows safely syncing
    // both sides. However, while this is the expected behavior for syncing, it may not be the case for a one way transfer (up
    // or down) and a file deletion may come unexpected. Therefore, this setting allows to finetune the behavior for deletions
    // and conflicts (file changed on both sides):
    //   "never":  If a file was deleted on one side, it will not be deleted on the other. Conflict files are left alone.
    //   "both":   Deleted files like above. Conflict: Both files are kept (older one with modification date) locally only (dated
    //             copies are never synced).
    //   "ask":    Deletions and conflicts trigger the confirmation dialog (confirm_file_transfer=true) or will ask for each
    //             file (for conflict: keep local, GitHub, both). Deleted and overwritten conflict files are backed-up.
    //   "sync":   Sync deletes without asking (for conflicts like "ask"), a Download/Commit like "ask". Backup: yes
    //   "always": Sync, Download and Commit delete without asking. Conflicts keep the newer, delete the older. Backup: yes
    //   "chaos":  Like "always". No backup!
    // Backup: a local file is copied into the folder "_backup" beside the project file (without a project file: inside the
    // repo folder) before it is deleted or overwritten
    // (on GitHub the history is the backup). Files never synced are never deleted. The old name "delete_files" is still read.
    "conflict_and_delete_files": "ask",

    // Ask for the commit message. false: the default message is used ("Add x.md", "Update x.md", "Add 2 files, update 3 files").
    "ask_commit_message": true,

    // What the "Create Release" function asks for:
    //   "all":   manually specify the title and the notes
    //   "notes": the tag is used as title; the notes can be edited (default depends on release_notes_from_changelog)
    //   "never": the default values from "notes" are taken without asking
    // The notes open in an editor tab (Markdown, word wrap) with a banner:
    // Ctrl+Enter, Ctrl+S or the banner's link creates the release; to cancel close the tab (ESC).
    "ask_release_details": "all",

    // Prefix of the version tags when creating a release ("v" -> v1.2.3, "" -> 1.2.3).
    "tag_prefix": "v",

    // Adds or updates a moving tag. If you use this you need to update this after each new release! A moving tag is a long time
    // support tag, which points to a real release and does not change with each new release (e.g.  v1 that always points to the
    // latest v1.x.x release). Especially GitHub Actions are referenced that way to stay valid for a longer time
    // (e.g. `uses: owner/action@v1`).
    //   "ask":   ask after each release whether to move the major (v1) or minor (v1.2) tag
    //   "major": move the major tag (v1) without asking (e.g. v1.1.1 >>> v1; v2.0.1 >>> v2)
    //   "minor": move the minor tag (v1.2) without asking (e.g. v1.2.3 >>> v1.2; v1.3.4 >>> v1.3)
    //   "":      do not create or update a moving tag
    //   any other value: a fixed tag name that is moved to every release (e.g. "latest")
    "moving_tag": "",

    // Label of a new release (the options provided on the GitHub page for a new release):
    // * "latest": marked as the latest release
    // * "pre": pre-release
    // * "none": neither
    // * "" or "ask": a dropdown asks each time
    "release_label": "latest",

    // If you maintain a `CHANGELOG.md` file (in root), setting this to true will take the release notes from there: use
    // `## [Unreleased]` (tied to level 2) for the section with the changes of the new release. The section text is taken as
    // release notes. After releasing, this heading is renamed to the new version with date, e.g. `## [v1.0.2] - 2026-11-14`, and
    // a new section "## [Unreleased]" is added at the top. If this section is empty or missing a confirmation dialog comes up to
    // continue or cancel.
    "release_notes_from_changelog": false,

    // For Sublime Packages: True: works like "release_notes_from_changelog" but writes the text into `messages/<tag>.txt`
    // and binds it to messages.json. Sublime's Package Control shows this to users of a Sublime Text package after an upgrade.
    "sublime_version_files": false,

    // Where GitHub Light writes its output (Sync, Download, Commit, Show Project Changes):
    //   "console": the output panel, shown when something is written (default)
    //   "tab":     a scratch-buffer tab "GitHub Light" until you close it (will not ask for save)
    //   "none":    nothing is shown (the output still goes to the panel, open it by hand if needed)
    // Note: it is strongly recommended to keep the output visible, as it is the only source of detailed information about the
    // status of the files.
    "output_results": "console",
}
```

### Key bindings

Keys are only defined for confirming the release notes (Ctrl/Cmd+S, Ctrl/Cmd+Enter) and only in this context, so they will not be active in any other situations. Preferences › Package Settings › GitHub Light › Key Bindings has all available commands (commented out). Copy the ones you want to the right-hand side, for example:

```jsonc
[
    { "keys": ["primary+alt+c"], "command": "ghl_commit", "args": {"scope": "current"} },
    { "keys": ["primary+shift+alt+c"], "command": "ghl_commit", "args": {"scope": "all"} },
    { "keys": ["primary+alt+d"], "command": "ghl_sync" }
]
```
`primary` is Ctrl on Windows and Linux, ⌘ on macOS.

## Limits of this Package

* One folder, one repository, one branch per project. No branches, merges, rebases, stashes.
* The repository's wiki is a separate git repository that the API does not expose; GitHub Light cannot sync it. If you want your GitHub wiki uptodate with every commit you can write the wiki as markdown files and put them in a separate folder (e.g. `docs`) and use a GitHub action to automatically convert those files into the wiki (e.g. [publish-wiki-badges-action](https://github.com/wunditta/publish-wiki-badges-action)).
* Repositories whose tree does not fit into one API response (tens of thousands of files) are not supported.

## Installation

Via [Package Control](https://packagecontrol.io): `Package Control: Install Package` › `GitHub Light`. By hand: copy this repository into a folder `GitHub Light` inside Sublime's `Packages` folder (open with: Preferences › Browse Packages…).

## License

GNU General Public License v3.0 or later — see LICENSE. Issues and suggestions: https://github.com/wunditta/sublime-github-light/issues
