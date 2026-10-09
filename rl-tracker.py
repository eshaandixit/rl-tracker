import argparse
import ctypes
import json
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from urllib.parse import quote

if sys.platform != "win32":
    sys.exit("RL Tracker only runs on Windows.")
try:
    from curl_cffi import requests as http
    from PIL import Image, ImageDraw, ImageOps, ImageTk
except ImportError:
    sys.exit("Missing packages. Run:  python -m pip install -r requirements.txt")

set_window_owner = ctypes.windll.user32.SetWindowLongPtrW
set_window_owner.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
set_window_owner.restype = ctypes.c_ssize_t
GWLP_HWNDPARENT = -8

BROWSERS = ["safari", "firefox", "chrome", "edge"]

ALWAYS_ON_TOP = False
OPACITY = 100
MIN_OPACITY = 10

STATS_HOST = "127.0.0.1"
STATS_PORT = 49123
API_URL = "https://api.tracker.gg/api/v2/rocket-league/standard/profile/{platform}/{identifier}"
PROFILE_URL = "https://rocketleague.tracker.network/rocket-league/profile/{platform}/{identifier}/overview"
CACHE_TTL = 600
REQUEST_GAP = 0.75
BACKOFF = 60
ICON_SIZE = 36
DEFAULT_AVATAR = "https://trackercdn.com/cdn/rocketleague.tracker.network/images/defaultAvatar.jpg"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://rocketleague.tracker.network/",
    "Origin": "https://rocketleague.tracker.network",
}

PLATFORMS = {"steam": "steam", "epic": "epic", "ps4": "psn", "ps5": "psn", "psn": "psn",
             "xboxone": "xbl", "xbox": "xbl", "xbl": "xbl", "switch": "switch"}
PLAYLISTS = {10: "1v1", 11: "2v2", 13: "3v3"}
TEAM_SIZE_TO_PLAYLIST = {1: 10, 2: 11, 3: 13}

BG, ROW_ME, SEP = "#0c0c0c", "#262626", "#3a3a3a"
KEY = "#0c0c0d"
OUTLINE = "#000000"
FG, DIM = "#f0f0f0", "#8c8c8c"
BLUE, ORANGE = "#4aa3ff", "#ff9f43"
BTN_BG, BTN_ON = "#1f1f1f", "#f0f0f0"
FONT, FONT_BOLD, FONT_SMALL = ("Segoe UI", 12), ("Segoe UI", 12, "bold"), ("Segoe UI", 10)


def parse_profile(data):
    avatar = ((data.get("userInfo") or {}).get("customAvatarUrl")
              or (data.get("platformInfo") or {}).get("avatarUrl") or DEFAULT_AVATAR)
    out = {"wins": None, "avatar": avatar, "playlists": {}}
    for seg in data.get("segments", []):
        kind = seg.get("type")
        st = seg.get("stats") or {}
        pid = (seg.get("attributes") or {}).get("playlistId")
        if kind == "overview":
            out["wins"] = (st.get("wins") or {}).get("value")
        elif kind == "playlist" and pid in PLAYLISTS:
            tier_md = (st.get("tier") or {}).get("metadata") or {}
            rating = st.get("rating") or {}
            entry = out["playlists"].setdefault(pid, {})
            entry["mmr"] = rating.get("value")
            entry["rank"] = tier_md.get("name")
            entry["icon"] = tier_md.get("iconUrl") or (rating.get("metadata") or {}).get("iconUrl")
        elif kind == "peak-rating" and pid in PLAYLISTS:
            out["playlists"].setdefault(pid, {})["peak"] = (st.get("peakRating") or {}).get("value")
    for e in out["playlists"].values():
        vals = [v for v in (e.get("mmr"), e.get("peak")) if isinstance(v, (int, float))]
        e["peak"] = max(vals) if vals else None
    return out


class Tracker:
    def __init__(self):
        self.cache = {}
        self.last_request = 0.0
        self.blocked_until = 0.0
        self.browser = 0

    def _get(self, url, headers=None):
        r, error = None, None
        for _ in BROWSERS:
            try:
                r = http.get(url, headers=headers, timeout=10, impersonate=BROWSERS[self.browser])
                if r.status_code != 403:
                    return r
            except Exception as e:
                error = e
            self.browser = (self.browser + 1) % len(BROWSERS)
        if r is None:
            raise error
        return r

    def image(self, url):
        try:
            r = self._get(url)
            return r.content if r.status_code == 200 else None
        except Exception:
            return None

    def lookup(self, platform, identifier):
        key = (platform, identifier.lower())
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        if time.time() < self.blocked_until:
            return {"error": "paused (rate limited)", "retry": True}

        wait = REQUEST_GAP - (time.time() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.time()

        url = API_URL.format(platform=platform, identifier=quote(identifier, safe=""))
        try:
            r = self._get(url, HEADERS)
        except Exception as e:
            return {"error": f"network error ({type(e).__name__})", "retry": True}

        if r.status_code == 200:
            try:
                result = parse_profile(r.json()["data"])
            except (ValueError, KeyError, TypeError):
                return {"error": "unexpected response"}
        elif r.status_code == 404:
            result = {"error": "not found"}
        elif r.status_code in (403, 429):
            self.blocked_until = time.time() + BACKOFF
            return {"error": f"blocked ({r.status_code})", "retry": True}
        else:
            return {"error": f"HTTP {r.status_code}"}

        self.cache[key] = (time.time(), result)
        return result


def lookup_target(primary_id, name):
    parts = primary_id.split("|")
    if len(parts) < 2:
        return None
    platform = PLATFORMS.get(parts[0].lower())
    if platform is None or parts[1] in ("", "0"):
        return None
    return (platform, parts[1]) if platform == "steam" else (platform, name)


def guess_playlist(roster):
    counts = Counter(p["team"] for p in roster.values())
    return TEAM_SIZE_TO_PLAYLIST.get(max(counts.values(), default=2), 11)


def find_viewed_player(roster, game):
    if not game.get("bHasTarget") or game.get("bReplay"):
        return None
    target = game.get("Target") or {}
    return next((pid for pid, p in roster.items()
                 if p["name"] == target.get("Name") and p["team"] == target.get("TeamNum")), None)


def fmt_int(v):
    return f"{int(v):,}" if isinstance(v, (int, float)) else "-"


def stream_events(host, port):
    decoder = json.JSONDecoder()
    while True:
        try:
            with socket.create_connection((host, port), timeout=3) as sock:
                sock.settimeout(1.0)
                yield {"Event": "_Connected"}
                buf = ""
                while True:
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", errors="ignore")
                    while True:
                        start = buf.find("{")
                        if start == -1:
                            buf = ""
                            break
                        try:
                            msg, end = decoder.raw_decode(buf, start)
                        except json.JSONDecodeError:
                            buf = buf[start + 1:] if len(buf) - start > 1_000_000 else buf[start:]
                            break
                        buf = buf[end:]
                        if isinstance(msg, dict):
                            yield msg
        except OSError:
            pass
        yield None
        time.sleep(3)


def stream_worker(q, host, port):
    signature, connected, me = None, None, None
    for msg in stream_events(host, port):
        if msg is None:
            if connected is not False:
                q.put(("clear",))
                q.put(("closed",))
                q.put(("status", "Waiting for Rocket League…"))
                signature, connected, me = None, False, None
            continue
        if not connected:
            connected = True
            q.put(("status", "Connected, waiting for a match"))

        event, data = msg.get("Event"), msg.get("Data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if not isinstance(data, dict):
            continue
        if event == "UpdateState" and data.get("Players"):
            roster = {p.get("PrimaryId") or f"name:{p.get('Name')}":
                      {"name": p.get("Name", "?"), "team": p.get("TeamNum", 0)} for p in data["Players"]}
            sig = tuple(sorted((k, v["team"]) for k, v in roster.items()))
            if sig != signature:
                signature = sig
                q.put(("roster", roster))
                q.put(("status", "In match"))
            if me is None:
                me = find_viewed_player(roster, data.get("Game") or {})
                if me:
                    q.put(("me", me))
        elif event == "MatchDestroyed":
            signature, me = None, None
            q.put(("menu",))
            q.put(("status", "Main menu"))


class OutlinedText(tk.Canvas):
    fonts = {}

    def __init__(self, parent, text, fg, font, anchor="w"):
        super().__init__(parent, bg=KEY, highlightthickness=0, bd=0)
        if font not in self.fonts:
            self.fonts[font] = tkfont.Font(font=font)
        self.font, self.anchor = self.fonts[font], anchor
        offsets = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy] + [(0, 0)]
        self.items = [(self.create_text(0, 0, font=font, anchor=anchor,
                                        fill=fg if (dx, dy) == (0, 0) else OUTLINE), dx, dy)
                      for dx, dy in offsets]
        self.bind("<Configure>", lambda _e: self.layout())
        self.set(text)

    def set(self, text):
        for item, _, _ in self.items:
            self.itemconfigure(item, text=text)
        self.configure(width=self.font.measure(text) + 4, height=self.font.metrics("linespace") + 2)
        self.layout()

    def layout(self):
        x = 2 if self.anchor == "w" else self.winfo_width() - 2
        y = self.winfo_height() / 2
        for item, dx, dy in self.items:
            self.coords(item, x + dx, y + dy)


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.tracker = Tracker()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.icon_pool = ThreadPoolExecutor(max_workers=2)
        self.players, self.stats, self.me = {}, {}, None
        self.icons, self.icon_pending = {}, set()
        self.blank = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
        self.mode, self.manual = 11, False
        self.status = "Starting…"
        self.build()
        self.refresh()
        self.root.after(100, self.poll)

    def build(self):
        self.root.title("RL Tracker")
        self.root.configure(bg=BG)
        self.root.minsize(380, 120)
        self.on_top = ALWAYS_ON_TOP
        self.fitted = None

        self.win = tk.Toplevel(self.root, bg=KEY)
        self.win.overrideredirect(True)
        self.win.attributes("-transparentcolor", KEY)
        def window_only(handler):
            return lambda e: handler() if e.widget is self.root else None
        self.root.bind("<Configure>", window_only(self.follow))
        self.root.bind("<Unmap>", window_only(self.win.withdraw))
        self.root.bind("<Map>", window_only(self.on_map))
        self.apply_on_top()
        self.root.attributes("-alpha", OPACITY / 100)
        self.me_bar = tk.Frame(self.root, bg=ROW_ME)
        self.me_row = None

        self.ui = tk.Frame(self.win, bg=KEY)
        self.ui.pack(fill="both", expand=True)
        top = tk.Frame(self.ui, bg=KEY)
        top.pack(fill="x", padx=10, pady=(10, 6))
        self.buttons = {}
        for key, pid in zip("123", PLAYLISTS):
            b = tk.Label(top, text=PLAYLISTS[pid], font=FONT_BOLD, width=5, pady=3, cursor="hand2")
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda _e, p=pid: self.set_mode(p))
            self.root.bind_all(key, lambda _e, p=pid: self.set_mode(p))
            self.buttons[pid] = b
        self.pin_btn = tk.Label(top, text="On top", font=FONT_SMALL, padx=8, pady=4, cursor="hand2")
        self.pin_btn.pack(side="right")
        self.pin_btn.bind("<Button-1>", lambda _e: self.toggle_on_top())
        self.root.bind_all("t", lambda _e: self.toggle_on_top())
        self.root.bind_all("<Button-1>", self.open_profile, add="+")
        self.slider = tk.Scale(top, from_=MIN_OPACITY, to=100, orient="horizontal", length=70, width=10,
                               sliderlength=14, showvalue=False, bd=0, highlightthickness=0,
                               bg=BTN_ON, activebackground="#ffffff", troughcolor=BTN_BG, cursor="hand2",
                               command=lambda v: self.set_opacity(int(v)))
        self.slider.set(OPACITY)
        self.slider.pack(side="right", padx=(0, 10))
        OutlinedText(top, "Opacity", DIM, FONT_SMALL).pack(side="right", padx=(0, 4))
        self.status_lbl = OutlinedText(top, "", DIM, FONT_SMALL)
        self.status_lbl.pack(side="right", padx=(0, 10))

        self.table = tk.Frame(self.ui, bg=KEY)
        self.table.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.table.columnconfigure(2, weight=1)
        for c in (3, 4, 5):
            self.table.columnconfigure(c, minsize=72)

    def on_map(self):
        self.win.deiconify()
        self.win.update_idletasks()
        set_window_owner(int(self.win.wm_frame(), 16), GWLP_HWNDPARENT, int(self.root.wm_frame(), 16))
        self.win.lift()
        self.follow()

    def follow(self):
        self.win.geometry(f"{self.root.winfo_width()}x{self.root.winfo_height()}"
                          f"+{self.root.winfo_rootx()}+{self.root.winfo_rooty()}")
        self.place_highlight()

    def place_highlight(self):
        if self.me_row is None:
            self.me_bar.place_forget()
            return
        self.win.update_idletasks()
        x, y, w, h = self.table.grid_bbox(0, self.me_row, 5, self.me_row)
        self.me_bar.place(x=self.table.winfo_x() + x, y=self.table.winfo_y() + y, width=w, height=h)

    def fit(self):
        self.ui.update_idletasks()
        size = (self.ui.winfo_reqwidth(), self.ui.winfo_reqheight())
        if size != self.fitted:
            self.fitted = size
            self.root.geometry("%dx%d" % size)

    def apply_on_top(self):
        for w in (self.root, self.win):
            w.attributes("-topmost", self.on_top)

    def toggle_on_top(self):
        self.on_top = not self.on_top
        self.apply_on_top()
        self.refresh()

    def open_profile(self, e):
        url = getattr(self.root.winfo_containing(e.x_root, e.y_root), "profile_url", None)
        if url:
            webbrowser.open(url)

    def set_mode(self, pid):
        self.mode, self.manual = pid, True
        self.refresh()

    def set_opacity(self, percent):
        self.slider.set(percent)
        self.root.attributes("-alpha", percent / 100)

    def poll(self):
        changed = False
        try:
            while True:
                item = self.q.get_nowait()
                changed = True
                kind = item[0]
                if kind == "status":
                    self.status = item[1]
                elif kind == "clear":
                    self.players, self.stats, self.manual = {}, {}, False
                elif kind == "menu":
                    me = self.players.get(self.me)
                    self.players = {self.me: dict(me, team=0)} if me else {}
                    self.stats = {pid: s for pid, s in self.stats.items() if pid in self.players}
                    self.mode, self.manual = 11, False
                elif kind == "closed":
                    self.me = None
                    self.set_opacity(100)
                elif kind == "roster":
                    self.on_roster(item[1])
                elif kind == "me":
                    self.me = item[1]
                elif kind == "stats":
                    _, pid, result = item
                    if pid in self.stats:
                        self.stats[pid] = result
                        if result.get("retry"):
                            self.root.after((BACKOFF + 2) * 1000, lambda p=pid: self.retry(p))
                        self.want_image(result.get("avatar"), "avatar")
                        for e in result.get("playlists", {}).values():
                            self.want_image(e.get("icon"), "icon")
                elif kind == "image":
                    self.on_image(item[1], item[2])
        except queue.Empty:
            pass
        if changed:
            self.refresh()
        self.root.after(100, self.poll)

    def on_roster(self, roster):
        self.players = roster
        for pid in roster:
            if pid not in self.stats:
                self.request(pid)
        if not self.manual:
            self.mode = guess_playlist(roster)

    def request(self, pid):
        target = lookup_target(pid, self.players[pid]["name"])
        self.stats[pid] = None if target else {"bot": True}
        if target:
            self.pool.submit(self.fetch_profile, pid, *target)

    def retry(self, pid):
        s = self.stats.get(pid)
        if pid in self.players and s and s.get("retry"):
            self.request(pid)
            self.refresh()

    def fetch_profile(self, pid, platform, identifier):
        try:
            result = self.tracker.lookup(platform, identifier)
        except Exception as e:
            result = {"error": type(e).__name__, "retry": True}
        self.q.put(("stats", pid, result))

    def want_image(self, url, shape):
        key = (url, shape)
        if url and key not in self.icons and key not in self.icon_pending:
            self.icon_pending.add(key)
            self.icon_pool.submit(lambda: self.q.put(("image", key, self.tracker.image(url))))

    def on_image(self, key, data):
        self.icon_pending.discard(key)
        try:
            img = Image.open(BytesIO(data)).convert("RGBA")
            if key[1] == "avatar":
                img = ImageOps.fit(img, (ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                big = ICON_SIZE * 4
                mask = Image.new("L", (big, big), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
                img.putalpha(mask.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS))
            else:
                img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
            self.icons[key] = ImageTk.PhotoImage(img)
        except Exception:
            self.icons[key] = self.blank

    def image_for(self, url, shape):
        if not url:
            return self.blank
        if (url, shape) not in self.icons:
            self.want_image(url, shape)
            return self.blank
        return self.icons[(url, shape)]

    def style_button(self, button, on):
        button.configure(bg=BTN_ON if on else BTN_BG, fg=BG if on else DIM)

    def refresh(self):
        for pid, b in self.buttons.items():
            self.style_button(b, pid == self.mode)
        self.style_button(self.pin_btn, self.on_top)
        self.status_lbl.set(self.status)
        self.draw_table()
        self.fit()
        self.place_highlight()

    def draw_table(self):
        self.me_row = None
        for w in self.table.winfo_children():
            w.destroy()
        for c, h in enumerate(("", "", "Player", "MMR", "Peak", "Wins")):
            OutlinedText(self.table, h, DIM, FONT_SMALL, "e" if c >= 3 else "w").grid(
                row=0, column=c, sticky="ew", padx=6, pady=(0, 4))
        if not self.players:
            OutlinedText(self.table, "No match yet", DIM, FONT).grid(
                row=1, column=0, columnspan=6, pady=14)
            return

        me = self.me if self.me in self.players else None
        my_team = self.players[me]["team"] if me else 0
        rows = sorted(self.players.items(),
                      key=lambda kv: (kv[0] != me, kv[1]["team"] != my_team, kv[1]["name"].lower()))
        r, prev_team = 1, None
        for pid, p in rows:
            if prev_team is not None and p["team"] != prev_team:
                tk.Frame(self.table, bg=SEP, height=2).grid(row=r, column=0, columnspan=6, sticky="ew", pady=5)
                r += 1
            prev_team = p["team"]
            if pid == me:
                self.me_row = r
            self.add_row(r, pid, p, pid == me)
            r += 1

    def add_row(self, r, pid, p, is_me):
        s = self.stats.get(pid)
        entry = s["playlists"].get(self.mode, {}) if s and "playlists" in s else {}

        tk.Label(self.table, image=self.image_for(entry.get("icon"), "icon"), bg=KEY).grid(
            row=r, column=0, sticky="nsew", ipadx=4, ipady=2)
        avatar = s.get("avatar") if s else None
        tk.Label(self.table, image=self.image_for(avatar, "avatar"), bg=KEY).grid(
            row=r, column=1, sticky="nsew", ipadx=2, ipady=2)
        name = OutlinedText(self.table, p["name"], BLUE if p["team"] == 0 else ORANGE,
                            FONT_BOLD if is_me else FONT)
        name.grid(row=r, column=2, sticky="nsew", ipadx=6)
        target = lookup_target(pid, p["name"])
        if target:
            name.profile_url = PROFILE_URL.format(platform=target[0], identifier=quote(target[1], safe=""))
            name.configure(cursor="hand2")

        if s is None:
            note, color = "loading…", DIM
        elif s.get("bot"):
            note, color = "bot", DIM
        elif "error" in s:
            note, color = s["error"], FG
        else:
            note = None
        if note:
            OutlinedText(self.table, note, color, FONT_SMALL, "e").grid(
                row=r, column=3, columnspan=3, sticky="nsew", ipadx=6)
            return
        for c, v in enumerate((entry.get("mmr"), entry.get("peak"), s.get("wins")), start=3):
            OutlinedText(self.table, fmt_int(v), FG, FONT, "e").grid(
                row=r, column=c, sticky="nsew", ipadx=6)


def main():
    ap = argparse.ArgumentParser(description="Live Rocket League lobby ranks from tracker.gg")
    ap.add_argument("--test", nargs=2, metavar=("PLATFORM", "ID"),
                    help="show one profile without the game running, e.g. --test steam 7656119...")
    ap.add_argument("--host", default=STATS_HOST)
    ap.add_argument("--port", type=int, default=STATS_PORT)
    args = ap.parse_args()
    if args.test and args.test[0].lower() not in PLATFORMS:
        ap.error(f"PLATFORM must be one of: {', '.join(PLATFORMS)}")

    root = tk.Tk()
    app = App(root)
    if args.test:
        platform, identifier = args.test
        pid = f"{platform}|{identifier}|0"
        app.q.put(("status", "Test mode"))
        app.q.put(("roster", {pid: {"name": identifier, "team": 0}}))
        app.q.put(("me", pid))
    else:
        threading.Thread(target=stream_worker, args=(app.q, args.host, args.port), daemon=True).start()
    root.mainloop()
    os._exit(0)


if __name__ == "__main__":
    main()
