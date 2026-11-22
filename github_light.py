"""GitHub Light - a small GitHub client for Sublime Text that needs no git.

Keeps one folder of the project in sync with one branch of one GitHub repository through the REST API:
Sync, Download, Commit Current / Commit All, Status, View / Blame / History online, Create Release.
Change detection uses git's blob hash (sha1 of "blob <size>\\0" + content), computed locally and compared
with the branch tree; the hashes of the last sync live in <folder>/.github-sync-hash.json.
"""
import sublime, sublime_plugin
import os, re, json, base64, hashlib, fnmatch, threading, webbrowser, datetime, calendar, time, urllib.request, urllib.error, urllib.parse

SETTINGS_FILE = "GitHub Light.sublime-settings"
PROJECT_KEY = "github_light"
STATE_FILE = ".github-sync-hash.json"
API = "https://api.github.com"
PANEL = "github_light"

DEFAULTS = {
    "repository": "",
    "branch": "main",
    "repo_folder": "",
    "promote_repo_folder": False,
    "promoted_folder_badge": "\u2605",
    "folder_map": {"dot-github": ".github"},
    "ignore": [STATE_FILE, "_backup", "*.sublime-workspace", "*.sublime-project", ".DS_Store", "Thumbs.db"],
    "token": "",
    "confirm_file_transfer": True,
    "conflict_and_delete_files": "ask",
    "ask_commit_message": True,
    "ask_release_details": "all",
    "tag_prefix": "v",
    "moving_tag": "ask",
    "release_label": "latest",
    "release_notes_from_changelog": False,
    "sublime_version_files": False,
    "output_results": "console",
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
    """The local working copy: 'folder' relative to the project file; empty = the first folder in the side bar."""
    f = setting(window, "repo_folder") or ""
    if not f:
        if window is not None and window.folders():
            return os.path.normpath(window.folders()[0])
        return None
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
        dirs[:] = [d for d in dirs if d != ".git" and not (root == folder and d == BACKUP_DIR)]
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace("\\", "/")
            remote = to_remote(window, rel)
            if ignored(window, remote) or ignored(window, rel) or DATED_COPY.search(fn):
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

_anchor_next = [False]      # the next log() puts its first line at the top of the output (set when an action starts)
_anchor_pos = {}            # view id -> layout y of the current action's first line: the view is kept there while output grows
OUTPUT_TAB = "GitHub Light"


_panel_only = set()         # ids of windows whose running action (Create Release, Move Tag) writes to the console panel only


def output_mode(window):
    """output_results: "none" (written to the panel, never shown), "console" (the output panel is shown), "tab" (a scratch
    tab "GitHub Light" that stays until closed); the old key show_panel_on_output (true/false) is still read. Create
    Release and Move Tag ignore the setting: their report goes to the console panel (the setting is about the transfers)."""
    if window is not None and window.id() in _panel_only:
        return "console"
    if not has_setting(window, "output_results") and has_setting(window, "show_panel_on_output"):
        return "console" if setting(window, "show_panel_on_output") else "none"
    v = str(setting(window, "output_results") or "console").lower()
    return v if v in ("none", "console", "tab") else "console"


def output_tab(window):
    """the scratch tab that collects the output (output_results = "tab"), created when missing"""
    for v in window.views():
        if v.settings().get("ghl_output"):
            return v
    active = window.active_view()
    v = window.new_file()                                  # new_file brings its tab to the front ...
    v.set_name(OUTPUT_TAB)
    v.set_scratch(True)
    v.settings().set("ghl_output", True)
    v.settings().set("word_wrap", False)
    if active is not None and not _anchor_next[0]:         # ... which only an action start may do (log focuses it then)
        window.focus_view(active)
    return v


def log(window, text, gap=False):
    """appends text to the console or the tab; gap: an empty line before it unless the output is still empty"""
    def do():
        w = window or sublime.active_window()
        if w is None:
            return
        mode = output_mode(w)
        if mode == "tab":
            view = output_tab(w)
        else:
            view = w.find_output_panel(PANEL) or w.create_output_panel(PANEL)
        start = view.size()
        view.set_read_only(False)
        if gap and start:
            view.run_command("append", {"characters": "\n", "scroll_to_end": False})
            start = view.size()
        view.run_command("append", {"characters": text.rstrip("\n") + "\n", "scroll_to_end": False})
        view.set_read_only(True)
        if mode == "console" and w.active_panel() != "output." + PANEL:
            w.run_command("show_panel", {"panel": "output." + PANEL})
        if _anchor_next[0]:                                   # the start of an action: its first line at the top
            _anchor_next[0] = False
            _anchor_pos.clear()
            _anchor_pos[view.id()] = view.text_to_layout(start)[1]
            if mode == "tab":
                w.focus_view(view)
        y = _anchor_pos.get(view.id())
        if y is not None:                                     # showing the panel and appending may scroll: back to the anchor
            sublime.set_timeout(lambda: view.set_viewport_position((0, y), False), 20)
    sublime.set_timeout(do, 0)


def anchor():
    """the next line written to the panel becomes the first visible line (called when an action starts)"""
    _anchor_next[0] = True


def started(window, what, panel_only=False):
    """"<what> started..." in the output, only when the output is shown (it is feedback that something is running);
    either way the output of this action starts at the top of the panel or tab. panel_only: this action (and every log
    line until the next action starts) goes to the console panel whatever output_results says."""
    if window is not None:
        _panel_only.discard(window.id())
        if panel_only:
            _panel_only.add(window.id())
    anchor()
    if output_mode(window) != "none":
        log(window, "%s started..." % what, gap=True)


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

    def last_commit_time(self, path):
        """Time (seconds since the epoch) of the last commit on the branch that touched the path, None if unknown."""
        q = "/commits?path=%s&sha=%s&per_page=1" % (urllib.parse.quote(path, safe=""), urllib.parse.quote(self.branch, safe=""))
        commits = self.call("GET", self.r(q))
        try:
            date = commits[0]["commit"]["committer"]["date"]            # e.g. 2026-11-15T10:49:32Z
            return calendar.timegm(time.strptime(date[:19], "%Y-%m-%dT%H:%M:%S"))
        except (IndexError, KeyError, TypeError, ValueError):
            return None

    def create_blob(self, data):
        return self.call("POST", self.r("/git/blobs"),
                         {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})["sha"]

    def commit(self, head, base_tree, entries, message):
        """entries: [(remote path, blob sha)], sha None deletes the path -> new commit sha"""
        tree = self.call("POST", self.r("/git/trees"),
                         {"base_tree": base_tree, "tree": [{"path": p, "mode": "100644", "type": "blob", "sha": s} for p, s in entries]})
        commit = self.call("POST", self.r("/git/commits"), {"message": message, "tree": tree["sha"], "parents": [head]})
        self.call("PATCH", self.r("/git/refs/heads/" + urllib.parse.quote(self.branch, safe="")), {"sha": commit["sha"]})
        return commit["sha"]

    def tags(self):
        """[(name, commit sha)] of the newest 100 tags"""
        return [(t["name"], t["commit"]["sha"]) for t in self.call("GET", self.r("/tags?per_page=100"))]

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

    def release(self, tag, name, body, label="latest"):
        """label: "latest" (marked as the latest release), "pre" (pre-release), "none" (neither)"""
        return self.call("POST", self.r("/releases"),
                         {"tag_name": tag, "target_commitish": self.branch, "name": name, "body": body or "",
                          "prerelease": label == "pre", "make_latest": "true" if label == "latest" else "false"})

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

def ask_mode(window):
    """ask_release_details: "all" (title and notes), "notes" (title = tag, notes tab), "never"; true/false of old files are accepted"""
    v = setting(window, "ask_release_details")
    if v is True:
        return "all"
    if v is False or v is None:
        return "never"
    v = str(v).lower()
    return v if v in ("all", "notes", "never") else "all"


def ui_confirm(message, ok_title):
    """ok_cancel_dialog from a worker thread: run it on the UI thread and wait for the answer"""
    result = {}
    done = threading.Event()

    def ask():
        result["ok"] = sublime.ok_cancel_dialog(message, ok_title)
        done.set()
    sublime.set_timeout(ask, 0)
    done.wait()
    return result.get("ok", False)


def run_async(fn):
    threading.Thread(target=fn, daemon=True).start()


def ui(fn, *args):
    sublime.set_timeout(lambda: fn(*args), 0)


def prepare(window):
    """(api, folder) or None after an error message"""
    folder = sync_folder(window)
    if not folder:
        error("No repo folder - open a project or a folder first")
        return None
    try:
        api = Api(window)
    except ApiError as e:
        error(str(e))
        return None
    return api, folder


def inside(folder, path):
    """is path (file or folder) inside the repo folder (or the folder itself)?"""
    if not folder or not path:
        return False
    p, f = os.path.normcase(os.path.normpath(path)), os.path.normcase(folder)
    return p == f or p.startswith(f + os.sep)


def active_file(window):
    v = window.active_view()
    return v.file_name() if v else None


def menu_view(window, group=None, index=None):
    """The view a right-click menu means: the clicked tab (the tab header menu passes group and index), else the active
    view."""
    if group is not None and index is not None:
        views = window.views_in_group(group)
        if 0 <= index < len(views):
            return views[index]
    return window.active_view()


def menu_file(window, files=None, group=None, index=None):
    """The file a right-click menu means: the side bar's single file, the clicked tab's file or the active file."""
    if files is not None:
        return files[0] if len(files) == 1 else None
    v = menu_view(window, group, index)
    return v.file_name() if v else None


def project_window(window):
    """is this window a GitHub Light project (its project file has a "github_light" settings block)? The right-click menus
    show nothing otherwise."""
    if window is None:
        return False
    return ((window.project_data() or {}).get("settings") or {}).get(PROJECT_KEY) is not None


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
    for t, _ in api.tags():
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


def default_message(items):
    """GitHub's own wording: "Add x.md" / "Update x.md" / "Delete x.md" / "Add 2 files, update 3 files, delete 1 file" """
    added = [it.path for it in items if it.action != "delete_remote" and it.new]
    updated = [it.path for it in items if it.action != "delete_remote" and not it.new]
    deleted = [it.path for it in items if it.action == "delete_remote"]
    if len(items) == 1:
        return ("Add " if added else "Delete " if deleted else "Update ") + items[0].path
    parts = []
    if added:
        parts.append("add " + describe(len(added), "file"))
    if updated:
        parts.append("update " + describe(len(updated), "file"))
    if deleted:
        parts.append("delete " + describe(len(deleted), "file"))
    text = ", ".join(parts)
    return text[0].upper() + text[1:]


def short_list(names):
    """the first few names for a dialog (message boxes have no scrollbar); the full list goes to the output panel"""
    if len(names) <= DIALOG_LINES:
        return "\n".join(names)
    return "\n".join(names[:DIALOG_LINES]) + "\n... and %d more (see the output panel)" % (len(names) - DIALOG_LINES)


# ---------------------------------------------------------------- commands

CLOCK_SLACK = 120          # seconds of tolerance between the local clock and GitHub's commit times
BACKUP_DIR = "_backup"     # beside the project file (else inside the repo folder); a local file is copied there before it is deleted or overwritten
MODES = ("never", "both", "ask", "sync", "always", "chaos")
DATED_COPY = re.compile(r" \(\d{4}-\d{2}-\d{2} \d{2}_\d{2}\)(\.[^./]+)?$")   # "name (2026-11-19 10_22).md": a kept older version, never synced


def local_newer(api, path, lp):
    """True if the local file was modified after the last commit that touched the path on GitHub, False if before,
    None when the commit time is not available."""
    try:
        ct = api.last_commit_time(path)
        if ct is None:
            return None
        return os.path.getmtime(lp) > ct + CLOCK_SLACK
    except (ApiError, OSError):
        return None


def has_setting(window, key):
    """is the key set explicitly (project file or settings file), not just a default?"""
    if window is not None:
        proj = ((window.project_data() or {}).get("settings") or {}).get(PROJECT_KEY) or {}
        if key in proj:
            return True
    return sublime.load_settings(SETTINGS_FILE).has(key)


def confirm_transfer(window):
    """confirm_file_transfer; the old key confirm_commit is still read when the new one is not set"""
    if not has_setting(window, "confirm_file_transfer") and has_setting(window, "confirm_commit"):
        return bool(setting(window, "confirm_commit"))
    return bool(setting(window, "confirm_file_transfer"))


def mode(window):
    """conflict_and_delete_files; the old key delete_files is still read when the new one is not set"""
    if not has_setting(window, "conflict_and_delete_files") and has_setting(window, "delete_files"):
        v = setting(window, "delete_files")
    else:
        v = setting(window, "conflict_and_delete_files")
    v = str(v or "ask").lower()
    return v if v in MODES else "ask"


def backup_root(window, folder):
    """The _backup folder: beside the project file, or inside the repo folder when there is no project file."""
    pf = window.project_file_name() if window is not None else None
    return os.path.join(os.path.dirname(pf) if pf else folder, BACKUP_DIR)


def backup(window, folder, lp):
    """Copy a local file into _backup/<relative path> (an earlier backup of the same file is replaced)."""
    rel = os.path.relpath(lp, folder)
    dest = os.path.join(backup_root(window, folder), rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(lp, "rb") as src, open(dest, "wb") as dst:
        dst.write(src.read())


def dated_name(lp, when):
    """'name (2026-11-19 10_22).ext' next to lp, for the older version of a conflict kept locally"""
    d, fn = os.path.split(lp)
    stem, ext = os.path.splitext(fn)
    return os.path.join(d, "%s (%s)%s" % (stem, time.strftime("%Y-%m-%d %H_%M", time.localtime(when)), ext))


class Item(object):
    """One path of a plan. cat: the category shown ("Download", "Commit (new)", "Conflict", "Unknown", "Commit (older)", ...);
    action: what will be done: "download", "commit", "delete_local", "delete_remote", "both" (newer keeps the name,
    the older version is kept locally as a dated copy), "skip"; ask: the item is a conflict the user may be asked about."""

    def __init__(self, path, lp, local, remote, base):
        self.path, self.lp = path, lp
        self.local, self.remote, self.base = local, remote, base
        self.cat, self.action, self.ask, self.newer, self.why = "", "skip", False, None, ""
        self.question = False      # asked per file (conflicts); an "(older)" item is only overridable by OK in the dialog
        self.hint = ""             # the suggestion text when it is not the action word ("keep GitHub (newer)")

    @property
    def new(self):
        return self.cat.endswith("(new)")

    def suggestion(self):
        if not self.ask:
            return ""
        if self.hint:
            return "-> suggested: " + self.hint
        words = {"download": "download", "commit": "commit", "both": "keep both", "skip": "skip"}
        why = {True: "local newer", False: "GitHub newer"}.get(self.newer, "no dates")
        return "-> suggested: %s (%s)" % (words[self.action], self.why or why)

    def text(self, width=0):
        """the plan line: category and path in fixed columns, the suggestion behind them"""
        line = "%-21s %s" % (self.cat + ":", self.path)
        sug = self.suggestion()
        return ("%-*s   %s" % (22 + width, line, sug)) if sug else line


class Plan(object):
    def __init__(self, op, head, base_tree, state, items, unchanged):
        self.op, self.head, self.base_tree, self.state, self.items, self.unchanged = op, head, base_tree, state, items, unchanged
        self.unchanged_paths = []

    def counts(self):
        """[(category, n)] in the order of the categories, zeros omitted"""
        order = ["Conflict", "Unknown", "Both (new)", "Download", "Download (new)", "Download (older)", "Commit", "Commit (new)",
                 "Commit (older)", "Delete local", "Delete GitHub", "Keep local (prefs)", "Keep GitHub (prefs)"]
        c = {}
        for it in self.items:
            c[it.cat] = c.get(it.cat, 0) + 1
        out = [(k, c[k]) for k in order if c.get(k)]
        if self.unchanged:
            out.append(("Unchanged", self.unchanged))
        return out


OP_TITLE = {"sync": "Sync", "download": "Download", "commit": "Commit", "status": "Status"}


def conflict_rule(it, op, m):
    """Category "Conflict" (or "Unknown"): action and suggestion per conflict_and_delete_files."""
    it.ask, it.question = True, True
    if m == "never":
        it.action, it.why = "skip", "prefs"
        return
    if m == "both":
        it.action, it.why = "both", "prefs"
        return
    # ask / sync / always / chaos: the newer side wins; a one-way operation only in its direction
    if it.newer is None:
        it.action = "skip"
    elif it.newer:
        it.action = "commit" if op != "download" else "skip"
    else:
        it.action = "download" if op != "commit" else "skip"
    if m in ("always", "chaos"):
        it.ask, it.question = False, False                    # decided by the setting, nothing to ask


def make_plan(window, api, folder, op, limit=None):
    """Compare the folder, the branch and the last sync (three-way, per path) and decide the action per path.
    op: "sync" (both directions), "download" (GitHub -> local only), "commit" (local -> GitHub only).
    limit: a predicate on the remote path restricting the run to chosen files or folders. Raises ApiError."""
    head = api.head()
    remote, base_tree = api.tree(head)
    state = load_state(folder)
    stored = state["files"]
    local = local_files(window, folder)
    m = mode(window)
    may_delete = m not in ("never", "both")
    paths = set(local) | set(remote) | set(stored)
    items, unchanged, unchanged_paths = [], 0, []
    for path in sorted(paths):
        if ignored(window, path):
            continue
        lp = local.get(path) or os.path.join(folder, to_local(window, path).replace("/", os.sep))
        if limit and not limit(path, lp):
            continue
        L = file_hash(lp) if os.path.isfile(lp) else None
        R, B = remote.get(path), stored.get(path)
        if L is None and R is None:
            del stored[path]                                  # gone on both sides: stale entry
            continue
        if L is not None and L == R:
            stored[path] = L                                  # identical: nothing to do, adopt
            unchanged += 1
            unchanged_paths.append(path)
            continue
        it = Item(path, lp, L, R, B)
        if L is not None and R is not None:
            it.newer = local_newer(api, path, lp)
            if B is None:                                     # never synced: nobody knows who changed it
                it.cat = "Both (new)" if m == "both" else "Unknown"
                conflict_rule(it, op, m)
                if m == "both":
                    it.ask = False                            # both are kept, nothing to suggest
            elif B == L:                                      # unchanged here, changed on GitHub
                if op == "commit":                            # nothing to upload unless forced: GitHub's version is the newer
                    it.cat, it.ask, it.hint = "Commit (older)", True, "keep GitHub (newer)"
                else:
                    it.cat, it.action = "Download", "download"
            elif B == R:                                      # changed here, unchanged on GitHub
                if op == "download":
                    it.cat, it.ask, it.hint = "Download (older)", True, "keep local (newer)"
                else:
                    it.cat, it.action = "Commit", "commit"
            else:                                             # changed on both sides
                it.cat = "Conflict"
                conflict_rule(it, op, m)
        elif L is not None:                                   # only here
            if B is None:
                if op == "download":
                    continue                                  # a new local file is not Download's business
                it.cat, it.action = "Commit (new)", "commit"
            else:                                             # deleted on GitHub since the last sync
                if op == "commit":
                    continue
                it.cat, it.action = ("Delete local", "delete_local") if may_delete else ("Keep local (prefs)", "skip")
        else:                                                 # only on GitHub
            if B is None:
                if op == "commit":
                    continue
                it.cat, it.action = "Download (new)", "download"
            else:                                             # deleted here since the last sync
                if op == "download":
                    continue
                it.cat, it.action = ("Delete GitHub", "delete_remote") if may_delete else ("Keep GitHub (prefs)", "skip")
        items.append(it)
    plan = Plan(op, head, base_tree, state, items, unchanged)
    plan.unchanged_paths = unchanged_paths
    return plan


def plan_text(api, plan):
    """the console text of a plan: the summary line and one line per file, the compare link below when GitHub holds other versions"""
    counts = plan.counts()
    summary = ", ".join("%s: %d" % (k, n) for k, n in counts)
    width = max([len(it.path) for it in plan.items] + [0])
    order = [k for k, _ in plan.counts()]
    key = lambda it: (order.index(it.cat) if it.cat in order else 99, it.path)
    asks = sorted([it for it in plan.items if it.ask], key=key)      # the files with a suggestion first, then the compare page
    rest = sorted([it for it in plan.items if not it.ask], key=key)
    lines = ["  " + it.text(width) for it in asks + rest]
    if plan.unchanged:
        lines.append("  %-21s %d" % ("Unchanged:", plan.unchanged))
    text = "%s %s@%s: %s\n%s" % (OP_TITLE[plan.op], api.repo, api.branch, summary, "\n".join(lines))
    diffs = [k for k, _ in counts if k in ("Conflict", "Unknown", "Download", "Commit (older)")]
    if diffs and plan.state.get("head") and plan.head != plan.state.get("head"):   # files changed on GitHub since the last sync: its comparison of the two commits
        text += "\nView diffs for %s on GitHub\n%s" % (", ".join(diffs), compare_url(api, plan.state))
    return text


def review(window, api, folder, plan):
    """UI thread. Writes the plan to the panel; shows the confirmation dialog (counts only) when confirm_file_transfer
    is on or the setting wants deletions or conflicts confirmed; then asks per conflict where the setting says so,
    then the commit message, then applies the plan."""
    op, items, m = plan.op, plan.items, mode(window)
    title = OP_TITLE[op]
    if not items:
        log(window, "%s: nothing to do, the folder matches %s@%s" % (title, api.repo, api.branch))
        return sublime.status_message("GitHub Light: nothing to %s" % op)
    counts = plan.counts()
    asks = [it for it in items if it.ask]                     # items with a suggestion: conflicts and "(older)" items
    questions = [it for it in asks if it.question and m in ("ask", "sync")]   # conflicts asked per file
    older = [it for it in asks if not it.question]            # "(older)" items: overridable by OK in the dialog only
    deletions = [it for it in items if it.action in ("delete_local", "delete_remote")]
    log(window, plan_text(api, plan))
    forced = (bool(deletions) and (m == "ask" or (m == "sync" and op != "sync"))) or bool(questions)
    if confirm_transfer(window) or forced:
        msg = "%s %s@%s\n\n%s" % (title, api.repo, api.branch, "\n".join("%s: %d" % (k, n) for k, n in counts))
        if questions or older:
            r = sublime.yes_no_cancel_dialog(msg, "OK", "As Suggested")
            if r == sublime.DIALOG_CANCEL:
                return log(window, "%s cancelled" % title)
            if r == sublime.DIALOG_NO:                        # As Suggested: the suggestions stand
                return message_then_apply(window, api, folder, plan)
            if op != "sync":                                  # OK: the operation's direction for every conflict and "(older)" item
                for it in questions + older:
                    it.action = "download" if op == "download" else "commit"
                return message_then_apply(window, api, folder, plan)
            return ask_conflicts(window, api, folder, plan, questions, 0, None)
        if not sublime.ok_cancel_dialog(msg, "OK"):
            return log(window, "%s cancelled" % title)
        return message_then_apply(window, api, folder, plan)
    if m in ("always", "chaos") and op != "sync":             # no dialog, no asking: "(older)" items go as requested
        for it in older:
            it.action = "download" if op == "download" else "commit"
    if questions:                                             # no dialog: ask per file
        return ask_conflicts(window, api, folder, plan, questions, 0, None)
    message_then_apply(window, api, folder, plan)


def conflict_choices(op):
    """(label, action) pairs of the per-file question; the dialog adds "for all remaining" variants."""
    if op == "sync":
        return [("Keep local version (commit)", "commit"), ("Keep GitHub version (download)", "download"),
                ("Keep both (the older as a dated copy)", "both"), ("Skip", "skip")]
    if op == "download":
        return [("Overwrite the local file", "download"), ("Keep the local file", "skip")]
    return [("Overwrite the GitHub version", "commit"), ("Keep the GitHub version", "skip")]


def ask_conflicts(window, api, folder, plan, conflicts, i, for_all):
    """One quick panel per conflict; each offers "for all remaining conflicts" as well."""
    if for_all is not None:
        for it in conflicts[i:]:
            it.action = for_all
        i = len(conflicts)
    if i >= len(conflicts):
        return message_then_apply(window, api, folder, plan)
    it = conflicts[i]
    choices = conflict_choices(plan.op)
    rows = [[label, it.path] for label, _ in choices]
    rest = len(conflicts) - i - 1
    if rest:
        rows += [[label + " – for all remaining conflicts", describe(rest + 1, "file")] for label, _ in choices]

    def done(index):
        if index < 0:
            return log(window, "%s cancelled" % OP_TITLE[plan.op])
        label, action = choices[index % len(choices)]
        if index >= len(choices):
            return ask_conflicts(window, api, folder, plan, conflicts, i, action)
        it.action = action
        ask_conflicts(window, api, folder, plan, conflicts, i + 1, None)
    sublime.set_timeout(lambda: window.show_quick_panel(rows, done), 150)


def commit_items(plan):
    """the items that end in a commit: uploads, deletions on GitHub, and "both" where the local file is the newer"""
    return [it for it in plan.items if it.action in ("commit", "delete_remote") or (it.action == "both" and it.newer and plan.op != "download")]


def message_then_apply(window, api, folder, plan):
    commits = commit_items(plan)
    if not commits:
        return run_async(lambda: apply_plan(window, api, folder, plan, None))
    default = default_message(commits)
    if not setting(window, "ask_commit_message"):
        return run_async(lambda: apply_plan(window, api, folder, plan, default))
    # a moment later: an input panel opened in the same tick as a closing dialog loses focus at once (= cancel)
    sublime.set_timeout(lambda: window.show_input_panel(
        "Commit message:", default,
        lambda msg: run_async(lambda: apply_plan(window, api, folder, plan, msg.strip() or default)),
        None, lambda: log(window, "%s cancelled (no message)" % OP_TITLE[plan.op])), 150)


def apply_plan(window, api, folder, plan, message):
    """Worker thread: downloads, dated copies and local deletions first, then one commit with the uploads and the
    deletions on GitHub. Lists every transferred and deleted file as done, and what went wrong."""
    w, state, stored = window, plan.state, plan.state["files"]
    title = OP_TITLE[plan.op]
    keep_backup = mode(w) != "chaos"
    errors, done = [], []
    if output_mode(w) != "none":
        log(w, "Starting transfer now...")

    def did(what, it, note=""):
        done.append("  %-21s %s%s" % (what + ":", it.path, note))

    def write_local(it, data):
        if it.local is not None and keep_backup:
            backup(w, folder, it.lp)
        os.makedirs(os.path.dirname(it.lp), exist_ok=True)
        with open(it.lp, "wb") as f:
            f.write(data)
        stored[it.path] = it.remote

    for it in plan.items:
        try:
            if it.action == "download":
                write_local(it, api.blob(it.remote))
                did("Downloaded", it)
            elif it.action == "delete_local":
                if keep_backup:
                    backup(w, folder, it.lp)
                os.remove(it.lp)
                stored.pop(it.path, None)
                did("Deleted local", it)
            elif it.action == "both":
                data = api.blob(it.remote)
                if it.newer:                                  # local is the newer: GitHub's version becomes the dated copy
                    copy = dated_name(it.lp, api.last_commit_time(it.path) or time.time())
                    with open(copy, "wb") as f:
                        f.write(data)
                    did("Downloaded", it, " (GitHub's version as %s)" % os.path.basename(copy))
                else:                                         # GitHub's is the newer: the local file becomes the dated copy
                    copy = dated_name(it.lp, os.path.getmtime(it.lp))
                    os.replace(it.lp, copy)
                    it.local = None
                    write_local(it, data)
                    did("Downloaded", it, " (local version kept as %s)" % os.path.basename(copy))
        except (ApiError, OSError) as e:
            errors.append("  %s: %s" % (it.path, e))
    commits = commit_items(plan)
    new_head = None
    if commits:
        entries = []
        for it in commits:
            if it.action == "delete_remote":
                entries.append((it.path, None))
                continue
            try:
                with open(it.lp, "rb") as f:
                    data = f.read()
                sha = api.create_blob(data)
                if sha != it.local:
                    raise ApiError(0, "hash mismatch (local %s, GitHub %s)" % (it.local[:7], sha[:7]), "")
            except (ApiError, OSError) as e:
                errors.append("  %s: %s (commit aborted, nothing was committed)" % (it.path, e))
                entries = None
                break
            entries.append((it.path, sha))
        if entries:
            try:
                new_head = api.commit(plan.head, plan.base_tree, entries, message)
            except ApiError as e:
                errors.append("  commit: %s (nothing was committed)" % e)
            else:
                for it in commits:
                    if it.action == "delete_remote":
                        stored.pop(it.path, None)
                        did("Deleted GitHub", it)
                    else:
                        stored[it.path] = it.local
                        did("Committed", it)
    if not errors:
        state["head"] = new_head or plan.head                 # the folder now matches this head (except skipped files)
    save_state(folder, state)
    if done:
        log(w, "\n".join(done))
    if errors:
        log(w, "Error:\n" + "\n".join(errors))
        error("%s: %s failed, see the console" % (title, describe(len(errors), "action")))
    else:
        log(w, "Finished" + (", committed as %s" % new_head[:7] if new_head else ""))
    ui(sublime.status_message, "GitHub Light: %s %s" % (title.lower(), "failed" if errors else "finished"))


def start(window, op, limit=None):
    p = prepare(window)
    if not p:
        return
    api, folder = p

    def work():
        try:
            plan = make_plan(window, api, folder, op, limit)
        except ApiError as e:
            return error(str(e))
        save_state(folder, plan.state)                        # adopted identical files, dropped stale entries
        ui(review, window, api, folder, plan)
    os.makedirs(folder, exist_ok=True)
    started(window, OP_TITLE[op])
    run_async(work)


def side_bar_limit(window, files=None, dirs=None):
    """A predicate on (remote path, local path) for the files or the folder clicked in the side bar; None for the whole
    folder. Compares local absolute paths, case-normalised (the same test is_visible uses). Returns (limit, error text)."""
    folder = sync_folder(window)
    if files:
        chosen = set(os.path.normcase(os.path.normpath(f)) for f in files if f and folder and inside(folder, f) and os.path.isfile(f))
        if not chosen:
            return None, "The file is not inside the repo folder \"%s\"" % folder
        return (lambda path, lp: os.path.normcase(os.path.normpath(lp)) in chosen), None
    if dirs:
        sub = os.path.normpath(dirs[0])
        if not folder or not inside(folder, sub):
            return None, "The folder is not inside the repo folder \"%s\"" % folder
        if os.path.normcase(sub) == os.path.normcase(folder):
            return None, None
        prefix = os.path.normcase(sub) + os.sep
        return (lambda path, lp: os.path.normcase(os.path.normpath(lp)).startswith(prefix)), None
    return None, None


def side_bar_visible(window, files=None, dirs=None):
    # side bar: Sublime fills "files": [] / "dirs": [] with the clicked items - an EMPTY list on the other kind of item
    folder = sync_folder(window)
    if (files is not None or dirs is not None) and not project_window(window):
        return False
    if files is not None:
        return bool(files) and all(inside(folder, f) for f in files)
    if dirs is not None:
        return bool(dirs) and all(inside(folder, d) for d in dirs)
    return True


class GhlSyncCommand(sublime_plugin.WindowCommand):
    """Both directions: what changed on GitHub comes down, what changed here goes up, deletions on either side since
    the last sync are carried over (per delete_files), conflicts are asked. From the side bar (dirs=[...]) limited
    to that folder."""

    def run(self, files=None, dirs=None):
        limit, err = side_bar_limit(self.window, files, dirs)
        if err:
            return error(err)
        start(self.window, "sync", limit)

    def is_visible(self, files=None, dirs=None):
        return side_bar_visible(self.window, files, dirs)

    def is_enabled(self, files=None, dirs=None):
        return project_window(self.window)


class GhlDownloadCommand(sublime_plugin.WindowCommand):
    """GitHub -> folder: changed and new files of the branch; files deleted on GitHub since the last sync per
    delete_files; a file changed on both sides is asked for (suggested: the newer version). From the side bar
    (files=[...] / dirs=[...]) limited to those files or that folder."""

    def run(self, files=None, dirs=None):
        limit, err = side_bar_limit(self.window, files, dirs)
        if err:
            return error(err)
        start(self.window, "download", limit)

    def is_visible(self, files=None, dirs=None):
        return side_bar_visible(self.window, files, dirs)

    def is_enabled(self, files=None, dirs=None):
        return project_window(self.window)

    def description(self, files=None, dirs=None):
        # the only dynamic caption: one or several files from the side bar
        if files is not None:
            return "GitHub: Download File" if len(files) <= 1 else "GitHub: Download Files"
        return None


class GhlCommitCommand(sublime_plugin.WindowCommand):
    """Folder -> GitHub: the current file (scope "current"), every changed file of the folder (scope "all"), the files
    given by the side bar (files=[...]) or the files below a side bar folder (dirs=[...]), in one commit; files
    deleted here since the last sync per delete_files; a file changed on both sides is asked for."""

    def run(self, scope="all", files=None, dirs=None, context=False, group=None, index=None):
        w = self.window
        if scope == "current" and not files and not dirs:
            files = [menu_file(w, None, group, index)]
        if files:
            folder = sync_folder(w)
            chosen = [f for f in files if f and folder and inside(folder, f) and os.path.isfile(f)]
            dirty = [v for v in w.views() if v.is_dirty() and v.file_name() in chosen]
            if dirty:
                if not sublime.ok_cancel_dialog("%s not saved. Save and commit?" % ("The file is" if len(dirty) == 1 else "%d files are" % len(dirty)), "Save and commit"):
                    return
                for v in dirty:
                    v.run_command("save")
        limit, err = side_bar_limit(w, files, dirs)
        if err:
            return error(err)
        start(w, "commit", limit)

    def is_enabled(self, scope="all", files=None, dirs=None, context=False, group=None, index=None):
        if not project_window(self.window):
            return False
        if scope == "current" and not files and not dirs:
            return inside(sync_folder(self.window), menu_file(self.window, None, group, index))
        return True

    # side bar: Sublime fills "files": [] / "dirs": [] with the clicked items - an EMPTY list on the other kind of item
    def is_visible(self, scope="all", files=None, dirs=None, context=False, group=None, index=None):
        if files is not None or dirs is not None:
            return side_bar_visible(self.window, files, dirs)
        if context:
            return project_window(self.window) and self.is_enabled(scope, group=group, index=index)
        return True

    def description(self, scope="all", files=None, dirs=None, context=False, group=None, index=None):
        # the only dynamic caption (one or several files from the side bar); static captions are in the menu files
        if files is not None:
            return "GitHub: Commit File" if len(files) <= 1 else "GitHub: Commit Files"
        return None




class GhlStatusCommand(sublime_plugin.WindowCommand):
    """What a Sync would do, in the same categories, without doing anything. Right-click menus: in the side bar on any
    item of a project window, in the text area and on a tab only for a file inside the repo folder."""

    def is_visible(self, context=False, side_bar=False, group=None, index=None):
        if side_bar:
            return project_window(self.window)
        if context:
            return project_window(self.window) and inside(sync_folder(self.window), menu_file(self.window, None, group, index))
        return True

    def is_enabled(self, context=False, side_bar=False, group=None, index=None):
        return project_window(self.window)

    def run(self, context=False, side_bar=False, group=None, index=None):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p

        def work():
            try:
                plan = make_plan(self.window, api, folder, "sync")
            except ApiError as e:
                return error(str(e))
            plan.op = "status"
            head_note = "" if plan.head == plan.state.get("head") else "   (last sync %s)" % (plan.state.get("head", "")[:7] or "never")
            first, _, rest = plan_text(api, plan).partition("\n")
            log(self.window, first + head_note + ("\n" + rest if rest else ""))
        started(self.window, "Status")
        run_async(work)


class GhlOpenOnlineCommand(sublime_plugin.WindowCommand):
    """Open the current file on GitHub: kind = "blob" (view), "blame" or "history"."""

    def run(self, kind="blob", files=None, context=False, group=None, index=None):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        v = None if files else menu_view(self.window, group, index)
        fn = menu_file(self.window, files, group, index)
        if not inside(folder, fn) or not os.path.isfile(fn):
            return error("The file is not inside the repo folder \"%s\"" % folder)
        path = to_remote(self.window, os.path.relpath(fn, folder))
        line = None
        if kind in ("blob", "blame") and v and v.sel():
            line = v.rowcol(v.sel()[0].begin())[0] + 1
        webbrowser.open(api.web(kind, urllib.parse.quote(path), line))

    # the File Review submenu cannot be hidden (Sublime shows every submenu), so its items are disabled instead of hidden
    def is_enabled(self, kind="blob", files=None, context=False, group=None, index=None):
        return project_window(self.window) and inside(sync_folder(self.window), menu_file(self.window, files, group, index))


def syntax_for(scope, fallback, sample=None):
    """The path of the syntax Sublime would use for a file named sample (the user's own choice for that extension),
    else an installed syntax for the scope (the default package may be disabled in favour of another one, e.g. Markdown
    for MarkdownEditing), else fallback."""
    try:
        if sample:
            found = sublime.find_syntax_for_file(sample)
            if found:
                return found.path
        found = sublime.find_syntax_by_scope(scope)
        return found[0].path if found else fallback
    except Exception:
        return fallback


def diff_tab(window, fn, suffix, text):
    """A read-only scratch tab with Diff syntax named after the file: "<name> <suffix>", with the parent folder behind it
    when another open file of the window has the same name (as Sublime disambiguates its tabs)."""
    name = os.path.basename(fn)
    same = [v for v in window.views() if v.file_name() and os.path.basename(v.file_name()) == name
            and os.path.normcase(v.file_name()) != os.path.normcase(fn)]
    title = "%s %s" % (name, suffix) + ((" \u2014 " + os.path.basename(os.path.dirname(fn))) if same else "")
    view = window.new_file()
    view.set_name(title)
    view.set_scratch(True)
    view.run_command("append", {"characters": text + "\n"})
    view.assign_syntax("Packages/Diff/Diff.sublime-syntax")
    view.set_read_only(True)
    return view


def unified(a, b, a_name, b_name):
    import difflib
    return "\n".join(difflib.unified_diff(a, b, a_name, b_name, lineterm=""))


class GhlDiffCommand(sublime_plugin.WindowCommand):
    """The difference between the local file (current or clicked) and its version on the branch head, as a unified diff
    in a scratch tab. A file with unsaved changes asks whether the current (unsaved) or the saved state is compared."""

    def run(self, files=None, context=False, group=None, index=None):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        fn = menu_file(self.window, files, group, index)
        if not inside(folder, fn) or not os.path.isfile(fn):
            return error("The file is not inside the repo folder \"%s\"" % folder)
        view = self.window.find_open_file(fn)
        mine = None
        if view is not None and view.is_dirty():
            r = sublime.yes_no_cancel_dialog("Compare the current, unsaved state, or the saved state with the state on GitHub?\n\n"
                                             + os.path.basename(fn), "Current", "Saved")
            if r == sublime.DIALOG_CANCEL:
                return
            if r == sublime.DIALOG_YES:
                mine = view.substr(sublime.Region(0, view.size())).splitlines()
        if mine is None:
            with open(fn, "rb") as f:
                mine = f.read().decode("utf-8", "replace").splitlines()
        path = to_remote(self.window, os.path.relpath(fn, folder))
        started(self.window, "Diff")
        run_async(lambda: self.work(api, fn, path, mine))

    def work(self, api, fn, path, mine):
        try:
            head = api.head()
            remote, _ = api.tree(head)
            sha = remote.get(path)
            if not sha:
                log(self.window, "Diff %s: not on GitHub" % path)
                return error("%s was not found on GitHub!" % os.path.basename(fn))
            theirs = api.blob(sha).decode("utf-8", "replace").splitlines()
        except ApiError as e:
            return error(str(e))
        diff = unified(theirs, mine, "GitHub: " + path, "local: " + path)
        text = diff if diff else "No difference: %s is the same locally and on GitHub" % path
        ui(self.show, fn, path, text)

    def show(self, fn, path, text):
        diff_tab(self.window, fn, "(GitHub diff)", text)
        log(self.window, "Diff %s: %s" % (path, "no difference" if text.startswith("No difference") else "shown in a tab"))

    # the File Review submenu cannot be hidden (Sublime shows every submenu), so its items are disabled instead of hidden
    def is_enabled(self, files=None, context=False, group=None, index=None):
        return project_window(self.window) and inside(sync_folder(self.window), menu_file(self.window, files, group, index))


class GhlDiffUnsavedCommand(sublime_plugin.WindowCommand):
    """The unsaved changes of an open file (current, clicked tab or side bar's file) against its saved state, as a unified
    diff in a scratch tab - Sublime's "Show Unsaved Changes" in a tab. Any file, no project needed."""

    def target(self, files=None, group=None, index=None):
        fn = menu_file(self.window, files, group, index)
        v = self.window.find_open_file(fn) if fn else None
        return v if v is not None and v.is_dirty() and os.path.isfile(fn) else None

    def run(self, files=None, context=False, group=None, index=None):
        v = self.target(files, group, index)
        if v is None:
            return sublime.status_message("GitHub Light: no unsaved changes")
        fn = v.file_name()
        with open(fn, "rb") as f:
            saved = f.read().decode("utf-8", "replace").splitlines()
        current = v.substr(sublime.Region(0, v.size())).splitlines()
        name = os.path.basename(fn)
        diff = unified(saved, current, "saved: " + name, "unsaved: " + name)
        diff_tab(self.window, fn, "(unsaved changes)", diff or "No difference: the unsaved changes are only in line endings or encoding")

    def is_enabled(self, files=None, context=False, group=None, index=None):
        return self.target(files, group, index) is not None


CHANGELOG = "CHANGELOG.md"
UNRELEASED_RE = re.compile(r"^## \[?Unreleased\]?[ \t]*\n", re.M | re.I)
NEXT_H2_RE = re.compile(r"^## ", re.M)


def read_unreleased(folder):
    """(section text without its heading, stripped) of CHANGELOG.md, or None when there is no file or no section"""
    path = os.path.join(folder, CHANGELOG)
    if not os.path.isfile(path):
        return None
    text = open(path, "r", encoding="utf-8").read()
    m = UNRELEASED_RE.search(text)
    if not m:
        return None
    rest = text[m.end():]
    n = NEXT_H2_RE.search(rest)
    return (rest[:n.start()] if n else rest).strip()


def release_changelog(folder, tag, notes=None):
    """Rename the Unreleased section to the tag (v1.2.0, as the release is named) with today's date; new empty Unreleased
    on top. With notes, the section body is replaced by them (the text as confirmed in the release dialog)."""
    path = os.path.join(folder, CHANGELOG)
    text = open(path, "r", encoding="utf-8").read()
    m = UNRELEASED_RE.search(text)
    today = datetime.date.today().isoformat()
    rest = text[m.end():]
    if notes is not None:
        n = NEXT_H2_RE.search(rest)
        rest = "\n" + notes.strip() + "\n\n" + (rest[n.start():] if n else "")
    new = text[:m.start()] + "## [Unreleased]\n\n## [%s] - %s\n" % (tag, today) + rest
    open(path, "w", encoding="utf-8").write(new)
    return path


def write_version_message(folder, version, tag, notes):
    """messages/<tag>.txt with the notes and its entry in messages.json (Package Control shows it after an upgrade).
    The json key must be the bare version: Package Control looks the note up by the version parsed from the tag."""
    mdir = os.path.join(folder, "messages")
    os.makedirs(mdir, exist_ok=True)
    txt = os.path.join(mdir, tag + ".txt")
    open(txt, "w", encoding="utf-8").write("%s\n\n%s\n" % (tag, notes))
    mjson = os.path.join(folder, "messages.json")
    data = {}
    if os.path.isfile(mjson):
        try:
            data = json.loads(open(mjson, "r", encoding="utf-8").read())
        except ValueError:
            data = {}
    data[version] = "messages/%s.txt" % tag
    open(mjson, "w", encoding="utf-8").write(json.dumps(data, indent=4) + "\n")
    return [txt, mjson]


def commit_files(window, api, folder, paths, message):
    """Commit the given local files as they are (no conflict check - they were just written); returns the new head."""
    state = load_state(folder)
    head = api.head()
    _, base_tree = api.tree(head)
    entries = []
    for lp in paths:
        with open(lp, "rb") as f:
            data = f.read()
        remote = to_remote(window, os.path.relpath(lp, folder))
        entries.append((remote, api.create_blob(data), blob_hash(data)))
    new = api.commit(head, base_tree, [(r, sha) for r, sha, _ in entries], message)
    for r, _, h in entries:
        state["files"][r] = h
    state["head"] = new
    save_state(folder, state)
    log(window, "Commit to %s@%s: %s\n%s\n  Committed as %s" % (api.repo, api.branch, message, "\n".join("  - %s: OK" % r for r, _, _ in entries), new[:7]))
    return new


class GhlSettingsCommand(sublime_plugin.WindowCommand):
    """Settings: default settings (read-only) | user settings | project file, when a project is open; else Sublime's two panes."""

    def run(self):
        open_settings(self.window, "GitHub Light", SETTINGS_FILE)


def open_settings(window, package, settings_file):
    base = "${packages}/%s/%s" % (package, settings_file)
    project = window.project_file_name()
    if not project:
        return window.run_command("edit_settings", {"base_file": base, "default": "{\n\t$0\n}\n"})
    user = os.path.join(sublime.packages_path(), "User", settings_file)
    if not os.path.isfile(user):
        with open(user, "w", encoding="utf-8") as f:
            f.write("{\n}\n")
    default = os.path.join(sublime.packages_path(), package, settings_file)
    if not os.path.isfile(default):                   # installed as .sublime-package: unpack the default file into a view
        sublime.run_command("new_window")
        w = sublime.active_window()
        w.set_layout({"cols": [0.0, 0.34, 0.67, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]})
        v = w.new_file()
        v.set_name(settings_file + " (default)")
        v.set_scratch(True)
        v.run_command("append", {"characters": sublime.load_resource("Packages/%s/%s" % (package, settings_file))})
        v.assign_syntax("Packages/JavaScript/JSON.sublime-syntax")
        v.set_read_only(True)
        w.set_view_index(v, 0, 0)
        w.focus_group(1)
        w.open_file(user)
        w.focus_group(2)
        w.open_file(project)
        return
    sublime.run_command("new_window")
    w = sublime.active_window()
    w.set_layout({"cols": [0.0, 0.34, 0.67, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]})
    w.focus_group(0)
    v = w.open_file(default)
    make_read_only(v)
    w.focus_group(1)
    w.open_file(user)
    w.focus_group(2)
    w.open_file(project)


def make_read_only(view, tries=50):
    if view.is_loading():
        if tries > 0:
            sublime.set_timeout(lambda: make_read_only(view, tries - 1), 50)
        return
    view.set_read_only(True)



class GhlNewProjectCommand(sublime_plugin.WindowCommand):
    """Menu bar: a project file for GitHub Light in a folder chosen (or created) in the system's folder dialog, named
    after the folder, opened with its settings. The repository on GitHub is not created. Sublime 3 has no folder
    dialog: an input panel asks for the path."""

    def run(self):
        if hasattr(sublime, "select_folder_dialog"):
            sublime.select_folder_dialog(lambda folder: folder and self.create(folder))
        else:
            self.window.show_input_panel("Folder of the new GitHub project (created if missing):", "",
                                         lambda folder: folder.strip() and self.create(folder.strip()), None, None)

    def create(self, folder):
        folder = os.path.normpath(folder)
        name = os.path.basename(folder)
        if not name:
            return sublime.error_message("GitHub Light: a drive root cannot be the project folder")
        project = os.path.join(folder, name + ".sublime-project")
        if os.path.exists(project):
            return sublime.error_message("GitHub Light: %s exists already" % project)
        os.makedirs(os.path.join(folder, "repo"), exist_ok=True)   # the repo folder; _backup comes beside the project file
        with open(project, "w", encoding="utf-8") as f:
            f.write(PROJECT_TEMPLATE)
        sublime.run_command("new_window")
        w = sublime.active_window()
        w.run_command("open_project_or_workspace", {"file": project})

        def settings(tries=20):
            if not w.project_file_name():
                if tries > 0:
                    sublime.set_timeout(lambda: settings(tries - 1), 100)
                return
            w.run_command("ghl_settings")
        sublime.set_timeout(settings, 200)


PROJECT_TEMPLATE = """{
    "folders":
    [
        { "path": "." }
    ],
    "settings":
    {
        "github_light":
        {
            // Settings of GitHub Light for this project. Any key of the package settings (left column of
            // Tools > GitHub Light > Settings) can be set here and overrides it for this project - except "token".
            "repository": "owner/name",
            // The repo folder (what is synced), relative to this file; backups of overwritten or deleted files go to _backup beside this file.
            "repo_folder": "repo",
            // The repo folder as its own entry in the side bar: false, true (the root folder hides it) or "duplicate" (the
            // root shows it too); the badge is appended to its name.
            "promote_repo_folder": false,
            "promoted_folder_badge": "\u2605",
        }
    }
}
"""

_pending_release = None      # the release waiting for its notes tab (one at a time)


class GhlReleaseNotesDoneCommand(sublime_plugin.TextCommand):
    """Ctrl+Enter in the release notes tab: take the text and create the release."""

    def run(self, edit):
        global _pending_release
        p = _pending_release
        if not p or p["view"] != self.view.id():
            return
        notes = self.view.substr(sublime.Region(0, self.view.size()))
        _pending_release = None
        self.view.set_scratch(True)
        self.view.close()
        run_async(lambda: p["cmd"].create(p["api"], p["prefix"], p["version"], p["tag"], p["title"], notes))

    def is_enabled(self):
        return bool(_pending_release) and _pending_release["view"] == self.view.id()


# ------------------------------------------------------------ promoted folder --
# promote_repo_folder: the repo folder as a top-level entry of the side bar (true: the root folder hides it,
# "duplicate": the root shows it too); checked when a project loads, when the project file is saved and at plugin load.
# Existing entries are never moved or removed - false means hands off.

def promote_folder(window, folder, mode, badge, top):
    """Ensures a top-level "folders" entry for folder (absolute path) in the project file: inserted at the top (top=True)
    or directly above the root entry that contains it (GitHub Light: above the root, the TTS editor puts its folder on top); with mode true the root entry excludes it. Writes the project
    file only when something changes. Returns True when it did."""
    if not mode or window is None or not folder or not window.project_file_name():
        return False
    pd = window.project_data() or {}
    folders = pd.get("folders") or []
    base = os.path.dirname(window.project_file_name())
    folder = os.path.normpath(folder)

    def absolute(entry):
        p = entry.get("path") or ""
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(base, p))
    key = os.path.normcase(folder)
    exists = any(os.path.normcase(absolute(e)) == key for e in folders)
    roots = [e for e in folders if key.startswith(os.path.normcase(absolute(e)) + os.sep)]
    changed = False
    if not exists:
        rel = os.path.relpath(folder, base)
        entry = {"path": folder if rel.startswith("..") or os.path.isabs(rel) else rel.replace(os.sep, "/")}
        if badge:
            entry["name"] = "%s %s" % (os.path.basename(folder), badge)
        at = 0 if top or not roots else folders.index(roots[0])
        folders.insert(at, entry)
        changed = True
    if mode is True:
        for root in roots:
            rel = os.path.relpath(folder, absolute(root)).replace(os.sep, "/")
            pattern = rel if "/" not in rel else "*/" + rel      # a direct child by name, a nested one by its path
            pats = root.setdefault("folder_exclude_patterns", [])
            if pattern not in pats:
                pats.append(pattern)
                changed = True
    if changed:
        pd["folders"] = folders
        window.set_project_data(pd)
    return changed


def check_promoted_folder(window):
    if window is None or not project_window(window):
        return
    mode = setting(window, "promote_repo_folder")
    if mode not in (True, "duplicate"):
        return
    if promote_folder(window, sync_folder(window), mode, str(setting(window, "promoted_folder_badge") or "").strip(), top=False):
        log(window, "Project: the repo folder was added to the side bar's folders (promote_repo_folder)")


class GhlProjectListener(sublime_plugin.EventListener):
    def on_load_project_async(self, window):
        check_promoted_folder(window)

    def on_post_save_async(self, view):
        w = view.window()
        if w is not None and view.file_name() and w.project_file_name() \
                and os.path.normcase(view.file_name()) == os.path.normcase(w.project_file_name()):
            check_promoted_folder(w)


def plugin_loaded():
    sublime.set_timeout(lambda: [check_promoted_folder(w) for w in sublime.windows()], 500)


class GhlReleaseNotesListener(sublime_plugin.EventListener):
    def on_pre_close(self, view):
        global _pending_release
        if _pending_release and _pending_release["view"] == view.id():
            tag = _pending_release["tag"]
            _pending_release = None
            log(view.window(), "Release %s cancelled (notes tab closed)" % tag)


class GhlReleaseCommand(sublime_plugin.WindowCommand):
    """Create a tag and a release on the branch head; the next version is chosen as patch, minor or major."""

    def is_enabled(self):
        return project_window(self.window)

    def run(self):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        self.folder = folder
        self.notes = None                                # the Unreleased section (release_notes_from_changelog)
        if setting(self.window, "release_notes_from_changelog"):
            self.notes = read_unreleased(folder)
            if self.notes is None:
                return error("No \"Unreleased\" section found in %s (expected a heading \"## [Unreleased]\")" % os.path.join(folder, CHANGELOG))
        started(self.window, "Create Release", panel_only=True)
        if self.notes is not None:
            if not self.notes:
                if not sublime.ok_cancel_dialog("The \"Unreleased\" section of %s is empty.\n\nRelease anyway (empty notes%s)?"
                                                % (CHANGELOG, "" if ask_mode(self.window) != "never" else ", the section is closed empty"), "Release anyway"):
                    return log(self.window, "Release cancelled: the Unreleased section of %s is empty" % CHANGELOG)
            else:
                log(self.window, "Release notes from %s:\n%s" % (CHANGELOG, "\n".join("  " + l for l in self.notes.splitlines())))
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
            label = setting(self.window, "release_label") or "ask"
            if label in ("latest", "pre", "none"):
                return self.after_label(api, prefix, version, tag, label)
            labels = [["Latest release", "Marked as the latest release of the repository"],
                      ["Pre-release", "Marked as a pre-release; the latest release stays as it is"],
                      ["No label", "Neither latest nor pre-release"]]
            sublime.set_timeout(lambda: self.window.show_quick_panel(
                labels, lambda j: self.after_label(api, prefix, version, tag, ("latest", "pre", "none")[j]) if j >= 0 else None), 150)
        self.window.show_quick_panel(items, picked)

    def after_label(self, api, prefix, version, tag, label):
        self.label = label
        mode = ask_mode(self.window)
        if mode == "never":
            return run_async(lambda: self.create(api, prefix, version, tag, tag, None))
        if mode == "notes":
            return sublime.set_timeout(lambda: self.body(api, prefix, version, tag, tag), 150)
        sublime.set_timeout(lambda: self.window.show_input_panel(
            "Release title:", tag, lambda title: self.body(api, prefix, version, tag, title), None, None), 150)

    def body(self, api, prefix, version, tag, title):
        """The notes are edited in a scratch tab (Markdown, word wrap): Ctrl+Enter creates the release, closing the tab cancels."""
        global _pending_release
        v = self.window.new_file()
        v.set_scratch(True)
        v.set_name("Release notes %s" % tag)
        v.assign_syntax(syntax_for("text.html.markdown", "Packages/Markdown/Markdown.sublime-syntax", "notes.md"))
        v.settings().set("word_wrap", True)
        v.settings().set("ghl_release_notes", True)
        v.run_command("append", {"characters": "\n" + (self.notes or "")})   # line 1 stays empty: the banner hangs below it, above the notes
        _pending_release = {"view": v.id(), "cmd": self, "api": api, "prefix": prefix, "version": version, "tag": tag, "title": title}
        key = "\u2318" if sublime.platform() == "osx" else "Ctrl"
        html = ('<body id="ghl-release"><style>body {padding: 0.3rem 0.6rem; margin-bottom: 0.4rem; background-color: color(var(--background) blend(var(--foreground) 92%%)); '
                'border-left: 0.25rem solid var(--bluish);} a {text-decoration: none;} .k {color: var(--foreground); opacity: 0.6;}</style>'
                '<b>Release notes for %s</b> &nbsp; <a href="done">Create release</a> &nbsp;|&nbsp; <a href="cancel">Cancel</a> '
                '&nbsp; <span class="k">%s+Enter or %s+S creates the release, closing the tab cancels</span></body>' % (tag, key, key))
        v.add_phantom("ghl_release", sublime.Region(0, 0), html, sublime.LAYOUT_BLOCK, on_navigate=lambda href: self.phantom_click(v, href))
        sublime.status_message("GitHub Light: edit the release notes, then %s+Enter or %s+S to create %s (close the tab to cancel)" % (key, key, tag))
        log(self.window, "Release %s: edit the notes in the tab \"%s\", then %s+Enter or %s+S creates the release; close the tab to cancel." % (tag, v.name(), key, key))
        sublime.set_timeout(lambda: self.window.focus_view(v), 50)   # in front of the output tab, whatever the log did

    def phantom_click(self, v, href):
        if href == "done":
            v.run_command("ghl_release_notes_done")
        elif href == "cancel":
            v.close()

    def create(self, api, prefix, version, tag, title, entered):
        """entered: the text of the notes panel, or None when the panel was not shown.
        Release notes = the entered text, else the changelog section (release_notes_from_changelog), else empty;
        sublime_version_files writes messages/<tag>.txt with the same notes."""
        vstr = "%d.%d.%d" % version
        section = self.notes or ""
        typed = entered.strip() if entered is not None else None
        notes = typed if typed is not None else section
        label = getattr(self, "label", "latest")
        log(self.window, "Release %s%s, title \"%s\"%s\n%s" % (
            tag, {"pre": " (pre-release)", "none": " (no label)", "latest": " (latest release)"}.get(label, ""), title.strip() or tag,
            "" if typed is None else " (notes edited in the tab)" if typed != section.strip() else " (notes as in the changelog)",
            "\n".join("  " + l for l in notes.splitlines()) if notes else "  (no notes)"))
        try:
            # the changelog and the Package Control message file must be in the release: commit them first
            paths = []
            if self.notes is not None:
                if not notes and section:
                    # the prefilled notes were deleted in the tab: ask, do not just drop the section text
                    if not ui_confirm("The release notes are empty (the changelog section was deleted in the tab).\n\nRelease anyway?", "Release anyway"):
                        return log(self.window, "Release cancelled: empty notes")
                paths.append(release_changelog(self.folder, tag, notes if notes != section.strip() else None))
            if setting(self.window, "sublime_version_files"):
                paths += write_version_message(self.folder, vstr, tag, notes)
            if paths:
                commit_files(self.window, api, self.folder, paths, "Release %s" % tag)
            rel = api.release(tag, title.strip() or tag, notes, getattr(self, "label", "latest"))
            sha = api.head()
        except ApiError as e:
            log(self.window, "Error: %s" % e)
            return error(str(e))
        except OSError as e:
            log(self.window, "Error: could not write the release files: %s" % e)
            return error("Could not write the release files: %s" % e)
        log(self.window, "Finished, release %s created: %s" % (tag, rel.get("html_url", "")))
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
        tags = api.tags()
    except ApiError as e:
        return error(str(e))
    prefix = setting(window, "tag_prefix") or ""
    version_re = re.compile(re.escape(prefix) + r"\d+\.\d+\.\d+")

    def label(commit):
        """the commit's version tags, e.g. "v1.0.2 (62ee521)", else the short sha"""
        names = [t for t, c in tags if c == commit and t != name and version_re.fullmatch(t)]
        return "%s (%s)" % (", ".join(names), commit[:7]) if names else commit[:7]
    if old is None:
        log(window, "Tag %s created at %s" % (name, label(sha)))
    elif old == sha:
        log(window, "Tag %s already points to %s" % (name, label(sha)))
    else:
        log(window, "Tag %s moved from %s to %s" % (name, label(old), label(sha)))
    ui(sublime.status_message, "GitHub Light: tag %s -> %s" % (name, label(sha)))


class GhlMoveTagCommand(sublime_plugin.WindowCommand):
    """Create or move a tag (such as v1) to the branch head; the name follows the moving_tag setting, or is asked for."""

    def is_enabled(self):
        return project_window(self.window)

    def run(self):
        p = prepare(self.window)
        if not p:
            return
        api, folder = p
        started(self.window, "Move Tag", panel_only=True)
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
