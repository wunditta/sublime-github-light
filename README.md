# GitHub Light

A small GitHub client for Sublime Text that needs **no git installation**. It keeps one folder of your project in sync with one branch of one GitHub repository through GitHub's REST API: download the files, commit what you changed, look at a file's history or blame in the browser, create a release. Nothing more — no branches, no merging, no history on your disk.

Meant for people who keep a few files on GitHub (a wiki, a package, documentation) and do not want to learn git for it. If you need branches and merges, use git.

## How it works

GitHub stores no modification times, so the package compares **content hashes**: for every file it computes git's blob hash (`sha1("blob <size>\0" + content)`) locally and compares it with the hashes of the branch, which one request to the API returns for all files at once. The hashes of your last sync are kept in `.github-sync-hash.json` inside the folder; this is how the package knows whether a file changed on your side, on GitHub, or on both. A commit is refused when GitHub changed a file since your last sync, so nothing is overwritten unseen.

Commits are made directly on the branch with the Git Data API (blobs → tree → commit → ref), one commit for all files you commit together, with the message you type. They appear on GitHub like any other commit, authored by the owner of the token.

## Setup

1. **Token.** On GitHub: Settings › Developer settings › Personal access tokens › Fine-grained tokens › Generate new token. Resource owner: you; repository access: only the repository you sync; permissions: *Contents: Read and write* (nothing else). Copy the token.
2. **User settings.** Preferences › Package Settings › GitHub Light › Settings, right-hand side:
   ```json
   {
       "token": "github_pat_…"
   }
   ```
   The token stays in your User settings and never in a project file.
3. **Project settings.** Project › Edit Project:
   ```json
   {
       "folders": [ { "path": "." } ],
       "settings": {
           "github_light": {
               "repository": "owner/name",
               "branch": "main",
               "folder": "github"
           }
       }
   }
   ```
   `folder` is the local working copy, relative to the project file. It may be empty; the first Download fills it.
4. Tools › GitHub Light › **Download**.

## Commands

All in Tools › GitHub Light and in the Command Palette as "GitHub Light: …".

| Command | What it does |
|---|---|
| **Download** | Fetches the branch and writes every file that changed on GitHub since your last sync into the folder. A file that you changed locally *and* that differs on GitHub is listed first: Overwrite, Skip them, or Cancel. Files deleted on GitHub are reported, the local copies stay. |
| **Commit Current File** | Commits the file in the active view if it changed (asks to save it first if needed). |
| **Commit All** | Commits every changed and every new file of the folder in one commit. With `confirm_commit` the list is shown first; then you type the message (unless `ask_commit_message` is off). The output panel lists every file with `OK` or the error. |
| **Status** | Lists in the output panel what is unchanged, to commit, in conflict, untracked, new on GitHub, or missing locally. Reads from GitHub, changes nothing. |
| **View Online** / **Blame Online** | Opens the current file on GitHub at the line the cursor is on. |
| **History Online** | Opens the commit history of the current file on GitHub. |
| **Create Release** | Reads the latest version tag of the repository and offers the next **patch**, **minor** and **major** version (semantic versioning: patch = backward compatible bug fixes, minor = new functionality, major = incompatible changes); `1.0.0` when there is no tag yet. Then title and optional notes, and the tag and release are created on the branch head. |

### When a commit is refused

"… changed on GitHub since your last sync" means somebody (or an action) committed to the file after you last downloaded it. The commit dialog then marks those files with "← changed on GitHub" and offers three ways out: *Commit* overwrites the GitHub version with yours (the other change is still in the history on GitHub, nothing is lost for good); *Open on GitHub* shows the compare page from your last sync to the current branch head, so you can see what changed, and cancels; *Cancel*. This dialog appears even with `confirm_commit` off. After a look at the changes, either Download (your local change is kept if it does not conflict, otherwise you are asked) and commit again, or copy your change into the downloaded version.

## Settings

| Key | Default | Meaning |
|---|---|---|
| `repository` | `""` | `owner/name`. Per project. |
| `branch` | `"main"` | The branch. |
| `folder` | `"github"` | Local working copy, relative to the project file (or to the first folder in the side bar when there is no project file). |
| `folder_map` | `{"dot-github": ".github"}` | Local folder names that stand for another name on GitHub (first path segment). The default lets you keep `.github` as `dot-github` locally, where tools that hide dot-folders can see it. |
| `ignore` | state file, `*.sublime-workspace`, `*.sublime-project`, `.DS_Store`, `Thumbs.db` | Glob patterns never synced. |
| `token` | `""` | The fine-grained personal access token. User settings only. |
| `confirm_commit` | `true` | Show the file list and ask before committing. |
| `ask_commit_message` | `true` | Ask for the commit message; `false` uses the default ("Add x.md" / "Update x.md", or "Add 2 files, update 3 files"). |
| `ask_release_details` | `true` | Ask for title and notes of a release; `false` takes the tag as title and no notes. |
| `tag_prefix` | `"v"` | Prefix of version tags (`v1.2.3`). Set `""` for plain numbers. |
| `show_panel_on_output` | `true` | Open the output panel when the package reports something. |

Every setting can be set in the project file under `"settings": {"github_light": {…}}`, which overrides the general settings.

## Key bindings

None by default. Preferences › Package Settings › GitHub Light › Key Bindings shows the commands; copy the ones you want to the right-hand side, for example

```json
[
    { "keys": ["primary+alt+c"], "command": "ghl_commit", "args": {"scope": "current"} },
    { "keys": ["primary+shift+alt+c"], "command": "ghl_commit", "args": {"scope": "all"} },
    { "keys": ["primary+alt+d"], "command": "ghl_download" }
]
```

(`primary` is Ctrl on Windows and Linux, ⌘ on macOS.)

## Limits

* One folder, one repository, one branch per project. No branches, merges, rebases, stashes.
* Commit never deletes files on GitHub; delete them on the website if you must.
* Binary files are synced like any other file (by hash), but the compare page on GitHub shows no diff for them.
* The repository's wiki is a separate git repository that the API does not expose; GitHub Light cannot sync it. Keep the pages in the repository and publish them with [publish-wiki-badges-action](https://github.com/wunditta/publish-wiki-badges-action).
* Repositories whose tree does not fit into one API response (tens of thousands of files) are not supported.

## Installation

Via [Package Control](https://packagecontrol.io): `Package Control: Install Package` › `GitHub Light`. By hand: copy this repository into a folder `GitHub Light` inside Sublime's `Packages` folder (Preferences › Browse Packages…).

## License

GNU General Public License v3.0 or later — see LICENSE. Issues and suggestions: https://github.com/wunditta/sublime-github-light/issues
