"""GitHub Light - a small GitHub client for Sublime Text that needs no git.

Keeps one folder of the project in sync with one branch of one GitHub repository through the REST API:
Download, Commit Current / Commit All, Status, View / Blame / History online, Create Release.
Change detection uses git's blob hash (sha1 of "blob <size>\\0" + content), computed locally and compared
with the branch tree; the hashes of the last sync live in <folder>/.github-sync-hash.json.
"""
import sublime, sublime_plugin
import os, re, json, base64, hashlib, fnmatch, threading, webbrowser, urllib.request, urllib.error, urllib.parse

SETTINGS_FILE = "GitHub Light.sublime-settings"
PROJECT_KEY = "github_light"
STATE_FILE = ".github-sync-hash.json"
API = "https://api.github.com"
PANEL = "github_light"

DEFAULTS = {
    "repository": "",
    "branch": "main",
    "folder": "github",
    "folder_map": {"dot-github": ".github"},
    "ignore": [STATE_FILE, "*.sublime-workspace", "*.sublime-project", ".DS_Store", "Thumbs.db"],
    "token": "",
    "confirm_commit": True,
    "ask_commit_message": True,
    "ask_release_details": True,
    "tag_prefix": "v",
    "moving_tag": "ask",
    "show_panel_on_output": True,
}


# ---------------------------------------------------------------- settings and paths

def setting(window, key):
    """Project setting ("settings": {"github_light": {...}}), else package setting, else default."""
    if window is not None:
        pd = window.project_data() or {}
        proj = (pd.get("settings") or {}).get(PROJECT_KEY) or {}
        if key in proj:
            return proj[key]
    s = sublime.load_settings(SETTINGS_FILE)
    if s.has(key):
        return s.get(key)
    return DEFAULTS.get(key)


def sync_folder(window):
    """The local working copy: 'folder' relative to the project file (or to the first sidebar folder)."""
    f = setting(window, "folder") or "github"
    f = os.path.expandvars(os.path.expanduser(f))
    if not os.path.isabs(f):
        base = None
        if window is not None and window.project_file_name():
            base = os.path.dirname(window.project_file_name())
        elif window is not None and window.folders():
            base = window.folders()[0]
        if base is None:
            return None
        f = os.path.join(base, f)
    return os.path.normpath(f)


def ignored(window, rel):
    """rel: remote-style relative path with '/'"""
    name = rel.rsplit("/", 1)[-1]
    for pat in setting(window, "ignore") or []:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat):
            return True
    return False


def to_remote(window, rel):
    """local relative path -> remote path (folder_map applied to the first segment)"""
    rel = rel.replace("\\", "/")
    fmap = setting(window, "folder_map") or {}
    first, _, rest = rel.partition("/")
    if first in fmap:
        return fmap[first] + ("/" + rest if rest else "")
    return rel


def to_local(window, remote):
    fmap = setting(window, "folder_map") or {}
    inv = {v: k for k, v in fmap.items()}
    first, _, rest = remote.partition("/")
    if first in inv:
        return inv[first] + ("/" + rest if rest else "")
    return remote


def local_files(window, folder):
    """{remote path: absolute local path} of every file in the folder that is not ignored"""
    out = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace("\\", "/")
            remote = to_remote(window, rel)
            if ignored(window, remote) or ignored(window, rel):
                continue
            out[remote] = full
    return out


def blob_hash(data):
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def file_hash(path):
    with open(path, "rb") as f:
        return blob_hash(f.read())


# ---------------------------------------------------------------- state

def load_state(folder):
    p = os.path.join(folder, STATE_FILE)
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            st.setdefault("files", {})
            return st
        except Exception:
            pass
    return {"head": "", "files": {}}


def save_state(folder, state):
    p = os.path.join(folder, STATE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------- output

def log(window, text):
    def do():
        w = window or sublime.active_window()
        if w is None:
            return
        panel = w.find_output_panel(PANEL) or w.create_output_panel(PANEL)
        panel.set_read_only(False)
        panel.run_command("append", {"characters": text.rstrip("\n") + "\n", "scroll_to_end": True})
        panel.set_read_only(True)
        if setting(w, "show_panel_on_output"):
            w.run_command("show_panel", {"panel": "output." + PANEL})
    sublime.set_timeout(do, 0)


def error(text):
    sublime.set_timeout(lambda: sublime.error_message("GitHub Light: " + text), 0)


# ---------------------------------------------------------------- API

class ApiError(Exception):
    def __init__(self, status, message, url):
        Exception.__init__(self, message)
        self.status, self.url = status, url


class Api(object):
    def __init__(self, window):
        self.repo = (setting(window, "repository") or "").strip().strip("/")
        self.branch = (setting(window, "branch") or "main").strip()
        self.token = (setting(window, "token") or "").strip()
        if not self.repo or "/" not in self.repo:
            raise ApiError(0, "No repository set - put \"repository\": \"owner/name\" into the project settings", "")
        if not self.token:
            raise ApiError(0, "No token - put \"token\": \"<fine-grained personal access token>\" into the User settings "
                              "(Preferences > Package Settings > GitHub Light > Settings)", "")

    def call(self, method, path, body=None, raw=False):
        url = path if path.startswith("http") else API + path
        data = None
        headers = {"Authorization": "Bearer " + self.token, "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "sublime-github-light",
                   "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(msg).get("message", msg)
            except Exception:
                pass
            if e.code in (401, 403):
                msg += " - check the token and its 'Contents: read and write' permission for this repository"
            raise ApiError(e.code, msg, url)
        except urllib.error.URLError as e:
            raise ApiError(0, "Network error: %s" % e.reason, url)
        if raw:
            return content
        return json.loads(content.decode("utf-8")) if content else {}

    def r(self, path):
        return "/repos/%s%s" % (self.repo, path)

    def head(self):
        """sha of the branch head commit"""
        return self.call("GET", self.r("/git/ref/heads/" + urllib.parse.quote(self.branch, safe="")))["object"]["sha"]

    def tree(self, head):
        """{remote path: blob sha} of the whole branch, plus the tree sha"""
        t = self.call("GET", self.r("/git/trees/%s?recursive=1" % head))
        if t.get("truncated"):
            raise ApiError(0, "The repository tree is too large for one request (GitHub truncated it)", "")
        files = {e["path"]: e["sha"] for e in t.get("tree", []) if e.get("type") == "blob"}
        return files, t["sha"]

    def blob(self, sha):
        return self.call("GET", self.r("/git/blobs/" + sha), raw=True)

    def create_blob(self, data):
        return self.call("POST", self.r("/git/blobs"),
                         {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})["sha"]

    def commit(self, head, base_tree, entries, message):
        """entries: [(remote path, blob sha)] -> new commit sha"""
        tree = self.call("POST", self.r("/git/trees"),
                         {"base_tree": base_tree, "tree": [{"path": p, "mode": "100644", "type": "blob", "sha": s} for p, s in entries]})
        commit = self.call("POST", self.r("/git/commits"), {"message": message, "tree": tree["sha"], "parents": [head]})
        self.call("PATCH", self.r("/git/refs/heads/" + urllib.parse.quote(self.branch, safe="")), {"sha": commit["sha"]})
        return commit["sha"]

    def tags(self):
        return [t["name"] for t in self.call("GET", self.r("/tags?per_page=100"))]

    def tag_target(self, name):
        """sha the tag points to, or None if the tag does not exist"""
        try:
            return self.call("GET", self.r("/git/ref/tags/" + urllib.parse.quote(name, safe="")))["object"]["sha"]
        except ApiError as e:
            if e.status == 404:
                return None
            raise

    def move_tag(self, name, sha):
        """create the tag or move it to sha; returns the previous sha (None if new)"""
        old = self.tag_target(name)
        if old is None:
            self.call("POST", self.r("/git/refs"), {"ref": "refs/tags/" + name, "sha": sha})
        elif old != sha:
            self.call("PATCH", self.r("/git/refs/tags/" + urllib.parse.quote(name, safe="")), {"sha": sha, "force": True})
        return old

    def release(self, tag, name, body):
        return self.call("POST", self.r("/releases"),
                         {"tag_name": tag, "target_commitish": self.branch, "name": name, "body": body or ""})

    def web(self, kind, path="", line=None):
        base = "https://github.com/%s" % self.repo
        if kind == "compare":
            return base + "/compare/" + path          # path = "sha...branch"
        if kind == "history":
            return base + "/commits/%s/%s" % (self.branch, path)
        url = base + "/%s/%s/%s" % (kind, self.branch, path)    # blob | blame
        if line:
            url += "#L%d" % line
        return url


# ---------------------------------------------------------------- helpers

def run_async(fn):
    threading.Thread(target=fn, daemon=True).start()


def ui(fn, *args):
    sublime.set_timeout(lambda: fn(*args), 0)


def prepare(window):
    """(api, folder) or None after an error message"""
    folder = sync_folder(window)
    if not folder:
        error("No project folder - open a project or a folder first")
        return None
    try:
        api = Api(window)
    except ApiError as e:
        error(str(e))
        return None
    return api, folder


def compare_url(api, state):
    if state.get("head"):
        return api.web("compare", "%s...%s" % (state["head"][:12], api.branch))
    return "https://github.com/%s/commits/%s" % (api.repo, api.branch)


def describe(count, what):
    return "%d %s%s" % (count, what, "" if count == 1 else "s")


DIALOG_LINES = 12


def latest_version(api, prefix):
    """(major, minor, patch) of the highest version tag, or None"""
    versions = []
    for t in api.tags():
        m = re.fullmatch(re.escape(prefix) + r"(\d+)\.(\d+)\.(\d+)", t)
        if m:
            versions.append(tuple(int(x) for x in m.groups()))
    return max(versions) if versions else None


def moving_tag_name(window, prefix, version, mode=None):
    """the moving tag for a version per the moving_tag setting: "major" -> v1, "minor" -> v1.2, other text -> that name, "" -> None"""
    mode = setting(window, "moving_tag") if mode is None else mode
    if not mode or mode == "ask":
        return None
    if mode == "major":
        return "%s%d" % (prefix, version[0])
    if mode == "minor":
        return "%s%d.%d" % (prefix, version[0], version[1])
    return mode


def default_message(changed):
    """GitHub's own wording: "Add x.md" / "Update x.md" / "Add 2 files, update 3 files" """
    added = [p for p, _, _, new in changed if new]
    updated = [p for p, _, _, new in changed if not new]
    if len(changed) == 1:
        return ("Add " if added else "Update ") + changed[0][0]
    parts = []
    if added:
        parts.append("add " + describe(len(added), "file"))
    if updated:
        parts.append("update " + describe(len(updated), "file"))
    text = ", ".join(parts)
    return text[0].upper() + text[1:]

def short_list(names):
    """the first few names for a dialog (message boxes have no scrollbar); the full list goes to the output panel"""
    if len(names) <= DIALOG_LINES:
        return "\n".join(names)
    return "\n".join(names[:DIALOG_LINES]) + "\n... and %d more (see the output panel)" % (len(names) - DIALOG_LINES)


# ---------------------------------------------------------------- commands

class GhlDownloadCommand(sublime_plugin.WindowCommand):
    """Write every file of the branch that changed since the last sync into the folder."""

    def run(self):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        run_async(lambda: self.work(api, folder))

    def work(self, api, folder):
        w = self.window
        try:
            head = api.head()
            remote, _ = api.tree(head)
        except ApiError as e:
            return error(str(e))
        os.makedirs(folder, exist_ok=True)
        state = load_state(folder)
        stored = state["files"]
        local = local_files(w, folder)
        todo, conflicts, gone = [], [], []
        for path, sha in sorted(remote.items()):
            if ignored(w, path):
                continue
            lp = os.path.join(folder, to_local(w, path).replace("/", os.sep))
            exists = path in local or os.path.isfile(lp)
            if exists:
                lh = file_hash(lp)
                if lh == sha:
                    stored[path] = sha                       # identical anyway: adopt
                    continue
                if path in stored and lh != stored[path]:
                    conflicts.append(path)                   # changed here AND different on GitHub
                    continue
                if path not in stored and lh != sha:
                    conflicts.append(path)                   # unknown local file differs from GitHub
                    continue
            todo.append(path)
        for path in list(stored):
            if path not in remote:
                gone.append(path)
        ui(self.decide, api, folder, head, remote, state, todo, conflicts, gone)

    def decide(self, api, folder, head, remote, state, todo, conflicts, gone):
        overwrite = []
        if conflicts:
            log(self.window, "Download: %s changed locally and differ from GitHub:\n%s"
                % (describe(len(conflicts), "file"), "\n".join("  " + p for p in conflicts)))
            msg = ("%s changed locally and differ from GitHub:\n\n%s\n\nOverwrite the local files with the GitHub version?"
                   % (describe(len(conflicts), "file"), short_list(conflicts)))
            r = sublime.yes_no_cancel_dialog(msg, "Overwrite", "Skip them")
            if r == sublime.DIALOG_CANCEL:
                return log(self.window, "Download cancelled")
            if r == sublime.DIALOG_YES:
                overwrite = conflicts
        run_async(lambda: self.write(api, folder, head, remote, state, todo + overwrite, [c for c in conflicts if c not in overwrite], gone))

    def write(self, api, folder, head, remote, state, todo, skipped, gone):
        w = self.window
        written, failed, lines = 0, 0, []
        for path in todo:
            try:
                data = api.blob(remote[path])
                lp = os.path.join(folder, to_local(w, path).replace("/", os.sep))
                os.makedirs(os.path.dirname(lp), exist_ok=True)
                with open(lp, "wb") as f:
                    f.write(data)
            except (ApiError, OSError) as e:
                lines.append("  %s: Error %s" % (path, e))
                failed += 1
                continue
            state["files"][path] = remote[path]
            lines.append("  %s: OK" % path)
            written += 1
        for path in gone:
            del state["files"][path]
        if not failed:
            state["head"] = head                             # the folder now matches this head (except skipped files)
        save_state(folder, state)
        head_line = "Download from %s@%s: %s written%s" % (api.repo, api.branch, describe(written, "file"),
                                                             ", %s failed" % describe(failed, "file") if failed else "")
        if skipped:
            lines.append("  Skipped (changed locally): " + ", ".join(skipped))
        if gone:
            lines.append("  Deleted on GitHub (local copies kept): " + ", ".join(gone))
        log(w, "\n".join([head_line] + lines))
        if failed:
            error("%s could not be downloaded, see the output panel" % describe(failed, "file"))
        ui(sublime.status_message, "GitHub Light: %s downloaded" % describe(written, "file"))


class GhlCommitCommand(sublime_plugin.WindowCommand):
    """Commit the current file (scope "current") or every changed file of the folder (scope "all")."""

    def run(self, scope="all"):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        candidates = None
        if scope == "current":
            v = self.window.active_view()
            fn = v.file_name() if v else None
            if not fn or not os.path.normpath(fn).startswith(folder + os.sep):
                return error("The current file is not inside the sync folder \"%s\"" % folder)
            if v.is_dirty():
                if not sublime.ok_cancel_dialog("The file is not saved. Save and commit?", "Save and commit"):
                    return
                v.run_command("save")
            rel = os.path.relpath(fn, folder)
            candidates = {to_remote(self.window, rel): fn}
        run_async(lambda: self.work(api, folder, candidates))

    def work(self, api, folder, candidates):
        w = self.window
        state = load_state(folder)
        stored = state["files"]
        if candidates is None:
            candidates = local_files(w, folder)
        try:
            head = api.head()
            remote, base_tree = api.tree(head)
        except ApiError as e:
            return error(str(e))
        changed, conflicts = [], []
        for path, lp in sorted(candidates.items()):
            if ignored(w, path):
                continue
            lh = file_hash(lp)
            rh = remote.get(path)
            if lh == rh:
                stored[path] = lh                            # already on GitHub like this
                continue
            if path in stored:
                if rh != stored[path]:
                    conflicts.append((path, lp, lh, False))  # GitHub moved on since the last sync
                    continue
            elif rh is not None:
                conflicts.append((path, lp, lh, False))      # never synced, but exists on GitHub with other content
                continue
            changed.append((path, lp, lh, rh is None))       # new on GitHub when it has no blob there
        save_state(folder, state)
        ui(self.decide, api, folder, head, base_tree, state, changed, conflicts)

    def decide(self, api, folder, head, base_tree, state, changed, conflicts):
        w = self.window
        if not changed and not conflicts:
            log(w, "Commit: nothing changed")
            return sublime.status_message("GitHub Light: nothing to commit")
        names = [p + "   \u2190 changed on GitHub" for p, _, _, _ in conflicts] + [p + ("   (new)" if new else "") for p, _, _, new in changed]
        listing = short_list(names)
        total = len(changed) + len(conflicts)
        log(w, "Commit: %s to %s@%s%s\n%s" % (describe(total, "file"), api.repo, api.branch,
            " (%s changed on GitHub since the last sync)" % describe(len(conflicts), "file") if conflicts else "",
            "\n".join("  " + n for n in names)))
        if conflicts:
            msg = ("Commit %s to %s@%s?\n\n%s\n\n%s changed on GitHub since your last sync; committing overwrites "
                   "the GitHub version with yours." % (describe(total, "file"), api.repo, api.branch, listing, describe(len(conflicts), "file")))
            r = sublime.yes_no_cancel_dialog(msg, "Commit", "Open on GitHub")
            if r == sublime.DIALOG_NO:
                webbrowser.open(compare_url(api, state))
            if r != sublime.DIALOG_YES:
                return log(w, "Commit cancelled: changed on GitHub: " + ", ".join(p for p, _, _, _ in conflicts))
            log(w, "Commit: overwriting the GitHub version of " + ", ".join(p for p, _, _, _ in conflicts))
            changed = changed + conflicts
        elif setting(w, "confirm_commit"):
            if not sublime.ok_cancel_dialog("%s changed since your last commit to %s@%s. Commit now?\n\n%s" % (describe(total, "file"), api.repo, api.branch, listing), "Commit"):
                return log(w, "Commit cancelled")
        default = default_message(changed)
        if not setting(w, "ask_commit_message"):
            return run_async(lambda: self.push(api, folder, head, base_tree, state, changed, default))
        # a moment later: an input panel opened in the same tick as a closing dialog loses focus at once (= cancel)
        sublime.set_timeout(lambda: w.show_input_panel(
            "Commit message:", default,
            lambda msg: run_async(lambda: self.push(api, folder, head, base_tree, state, changed, msg.strip() or default)),
            None, lambda: log(w, "Commit cancelled (no message)")), 150)

    def push(self, api, folder, head, base_tree, state, changed, message):
        w = self.window
        entries, lines = [], []
        log(w, "Commit to %s@%s: %s" % (api.repo, api.branch, message))
        for path, lp, lh, _ in changed:
            try:
                with open(lp, "rb") as f:
                    data = f.read()
                sha = api.create_blob(data)
                if sha != lh:
                    raise ApiError(0, "hash mismatch (local %s, GitHub %s)" % (lh[:7], sha[:7]), "")
            except (ApiError, OSError) as e:
                log(w, "  %s: Error %s\nCommit aborted, nothing was committed." % (path, e))
                return error("%s could not be uploaded: %s" % (path, e))
            log(w, "  - %s: OK" % path)
            entries.append((path, sha))
        try:
            new = api.commit(head, base_tree, entries, message)
        except ApiError as e:
            log(w, "  Error %s\nCommit aborted, nothing was committed." % e)
            return error(str(e))
        for path, _, lh, _ in changed:
            state["files"][path] = lh
        state["head"] = new
        save_state(folder, state)
        log(w, "  Committed as %s" % new[:7])
        ui(sublime.status_message, "GitHub Light: committed %s (%s)" % (describe(len(entries), "file"), new[:7]))


class GhlStatusCommand(sublime_plugin.WindowCommand):
    """List what differs between the folder, the last sync and the branch."""

    def run(self):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        run_async(lambda: self.work(api, folder))

    def work(self, api, folder):
        w = self.window
        state = load_state(folder)
        stored = state["files"]
        local = local_files(w, folder)
        try:
            head = api.head()
            remote, _ = api.tree(head)
        except ApiError as e:
            return error(str(e))
        changed, conflicts, untracked, newremote, gone, same = [], [], [], [], [], 0
        for path, lp in sorted(local.items()):
            lh = file_hash(lp)
            rh = remote.get(path)
            if lh == rh:
                same += 1
                continue
            if path not in stored:
                (conflicts if rh is not None else untracked).append(path)
            elif rh != stored[path]:
                conflicts.append(path)
            else:
                changed.append(path)
        for path in sorted(remote):
            if ignored(w, path):
                continue
            if path not in local:
                (gone if path in stored else newremote).append(path)
        lines = ["Status %s@%s (head %s%s)" % (api.repo, api.branch, head[:7],
                 "" if head == state.get("head") else ", last sync " + (state.get("head", "")[:7] or "never"))]
        lines.append("  %s unchanged" % describe(same, "file"))
        for title, items in (("To commit (changed locally)", changed), ("Conflict (changed on GitHub and locally)", conflicts),
                             ("Untracked (new local file, not on GitHub)", untracked), ("New on GitHub (download)", newremote),
                             ("Missing locally (on GitHub, deleted or never downloaded)", gone)):
            if items:
                lines.append("  %s:" % title)
                lines += ["    " + p for p in items]
        log(w, "\n".join(lines))


class GhlOpenOnlineCommand(sublime_plugin.WindowCommand):
    """Open the current file on GitHub: kind = "blob" (view), "blame" or "history"."""

    def run(self, kind="blob"):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        v = self.window.active_view()
        fn = v.file_name() if v else None
        if not fn or not os.path.normpath(fn).startswith(folder + os.sep):
            return error("The current file is not inside the sync folder \"%s\"" % folder)
        path = to_remote(self.window, os.path.relpath(fn, folder))
        line = None
        if kind in ("blob", "blame") and v.sel():
            line = v.rowcol(v.sel()[0].begin())[0] + 1
        webbrowser.open(api.web(kind, urllib.parse.quote(path), line))

    def is_enabled(self, kind="blob"):
        v = self.window.active_view()
        return bool(v and v.file_name())


class GhlReleaseCommand(sublime_plugin.WindowCommand):
    """Create a tag and a release on the branch head; the next version is chosen as patch, minor or major."""

    def run(self):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        run_async(lambda: self.work(api))

    def work(self, api):
        prefix = setting(self.window, "tag_prefix") or ""
        try:
            current = latest_version(api, prefix)
        except ApiError as e:
            return error(str(e))
        ui(self.choose, api, prefix, current)

    def choose(self, api, prefix, current):
        if current is None:
            options = [("1.0.0", "First release (no version tag yet)")]
        else:
            ma, mi, pa = current
            options = [("%d.%d.%d" % (ma, mi, pa + 1), "Patch - backward compatible bug fixes"),
                       ("%d.%d.0" % (ma, mi + 1), "Minor - new functionality, backward compatible"),
                       ("%d.0.0" % (ma + 1), "Major - incompatible changes")]
        items = [[prefix + v, d + ("" if current is None else "  (current %s%d.%d.%d)" % ((prefix,) + current))] for v, d in options]

        def picked(i):
            if i < 0:
                return
            tag = items[i][0]
            version = tuple(int(x) for x in options[i][0].split("."))
            if not setting(self.window, "ask_release_details"):
                return run_async(lambda: self.create(api, prefix, version, tag, tag, ""))
            sublime.set_timeout(lambda: self.window.show_input_panel(
                "Release title:", tag, lambda title: self.body(api, prefix, version, tag, title), None, None), 150)
        self.window.show_quick_panel(items, picked)

    def body(self, api, prefix, version, tag, title):
        self.window.show_input_panel("Release notes (optional):", "",
                                     lambda notes: run_async(lambda: self.create(api, prefix, version, tag, title, notes)), None, None)

    def create(self, api, prefix, version, tag, title, notes):
        try:
            rel = api.release(tag, title.strip() or tag, notes.strip())
            sha = api.head()
        except ApiError as e:
            return error(str(e))
        log(self.window, "Release %s created: %s" % (tag, rel.get("html_url", "")))
        ui(sublime.status_message, "GitHub Light: release %s created" % tag)
        mode = setting(self.window, "moving_tag")
        if mode == "ask":
            ui(self.ask_moving, api, prefix, version, sha)
        else:
            name = moving_tag_name(self.window, prefix, version, mode)
            if name:
                run_async(lambda: move_tag(self.window, api, name, sha))

    def ask_moving(self, api, prefix, version, sha):
        items = [["Move %s" % moving_tag_name(None, prefix, version, "major"), "The moving tag of the major version follows this release"],
                 ["Move %s" % moving_tag_name(None, prefix, version, "minor"), "The moving tag of the minor version follows this release"],
                 ["No moving tag", "Leave the tags as they are"]]

        def picked(i):
            if i in (0, 1):
                name = items[i][0][5:]
                run_async(lambda: move_tag(self.window, api, name, sha))
        sublime.set_timeout(lambda: self.window.show_quick_panel(items, picked), 150)


def move_tag(window, api, name, sha):
    try:
        old = api.move_tag(name, sha)
    except ApiError as e:
        return error(str(e))
    if old is None:
        log(window, "Tag %s created at %s" % (name, sha[:7]))
    elif old == sha:
        log(window, "Tag %s already points to %s" % (name, sha[:7]))
    else:
        log(window, "Tag %s moved from %s to %s" % (name, old[:7], sha[:7]))
    ui(sublime.status_message, "GitHub Light: tag %s -> %s" % (name, sha[:7]))


class GhlMoveTagCommand(sublime_plugin.WindowCommand):
    """Create or move a tag (such as v1) to the branch head; the name follows the moving_tag setting, or is asked for."""

    def run(self):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        run_async(lambda: self.work(api))

    def work(self, api):
        prefix = setting(self.window, "tag_prefix") or ""
        try:
            current = latest_version(api, prefix)
            sha = api.head()
        except ApiError as e:
            return error(str(e))
        mode = setting(self.window, "moving_tag")
        name = moving_tag_name(self.window, prefix, current, mode if mode not in ("ask", "") else "major") if current else prefix + "1"
        ui(self.ask, api, name, sha)

    def ask(self, api, name, sha):
        self.window.show_input_panel("Tag to create or move to %s:" % sha[:7], name,
                                     lambda n: run_async(lambda: move_tag(self.window, api, n.strip(), sha)) if n.strip() else None, None, None)
