#!/usr/bin/env python3
"""
redact-6_GUI.py - Visual PDF Redaction with explicit tool buttons and fixed panning.

A complete GUI for managing PDF redactions, further refined for usability.
- **NEW: Dedicated Tool Buttons**: A toolbar with radio buttons for Pan, Text, Redact,
  Exclude, and Protect modes makes the current tool obvious and easy to change.
- **FIXED: Mouse Panning**: Left-click-and-drag panning is restored and robust.
- **Unified Tool Model**: Single source of truth for the active tool.
- **Autosave & Dirty Flag**: Prevents data loss with a 3-second cache.
- **Undo/Redo Stack**: Ctrl+Z/Y for all major state changes.
- **Listbox UX**: Delete key support and in-place editing.
- **Flameshot-lite Editing**: Double-click a region to enter a resize/move mode.
- **Instant Preview**: Previews render directly from in-memory state.

Requirements:
    pip install pymupdf pillow
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import fitz
from PIL import Image, ImageTk, ImageDraw
import json
import os
from datetime import datetime
from pathlib import Path
import re
import copy
from enum import Enum, auto
from dataclasses import dataclass, asdict


# --- Section 1: Single Source of Truth for “what tool is active?” ---
class Tool(Enum):
    PAN = auto()
    TEXT_SELECT = auto()
    DRAW_REDACT = auto()
    DRAW_EXCLUDE = auto()
    DRAW_PROTECT = auto()
    EDIT_REGION = auto()


# --- Section 5: Rectangle drawing & *flameshot-lite* editing (Data Model) ---
@dataclass
class RegionStore:
    """Keeps redaction / exclusion / protect rectangles **and** undo history
    for one PDF.  No GUI code lives here."""

    MAX_HISTORY = 50
    AUTOSAVE_SEC = 300   # five-minute heartbeat

    def __init__(self, pdf_stem: str):
        self.stem = pdf_stem
        self.regions: list[dict] = []        # each: {"page":int,"bbox":tuple,"kind":str}
        self.history: list[list] = []
        self.future: list[list] = []
        self.dirty = False
        self._autosave_timer: Timer | None = None

        # try to load last session
        fname = JSONStore.find_latest_file(self.stem, "regions")
        if fname:
            try:
                self.regions = json.loads(Path(fname).read_text())
            except Exception as e:
                print("RegionStore: couldn’t load", fname, e)

    # ---------- mutation API ----------
    def add(self, page: int, bbox: tuple, kind: str):
        self._checkpoint()
        self.regions.append({"page": page, "bbox": bbox, "kind": kind})
        self._mark_dirty()

    def remove(self, region_dict):
        self._checkpoint()
        self.regions.remove(region_dict)
        self._mark_dirty()

    # ---------- undo/redo ----------
    def undo(self):
        if self.history:
            self.future.append(deepcopy(self.regions))
            self.regions = self.history.pop()
            return True
        return False

    def redo(self):
        if self.future:
            self.history.append(deepcopy(self.regions))
            self.regions = self.future.pop()
            return True
        return False

    # ---------- private helpers ----------
    def _checkpoint(self):
        self.history.append(deepcopy(self.regions))
        if len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)
        self.future.clear()          # new branch => clear redo

    def _mark_dirty(self):
        self.dirty = True
        self._schedule_autosave()

    def _schedule_autosave(self):
        if self._autosave_timer:
            self._autosave_timer.cancel()
        self._autosave_timer = Timer(self.AUTOSAVE_SEC, self._autosave)
        self._autosave_timer.daemon = True
        self._autosave_timer.start()

    def _autosave(self):
        if self.dirty:
            path = Path(JSONStore.DATA_DIR /
                        f"{self.stem}_regions_autosave.json")
            JSONStore.write_atomic(path, self.regions)
            self.dirty = False

# --- Section 3: Unified undo/redo stack ---
class HistoryManager:
    def __init__(self, depth=50):
        self.stack, self.redo_stack = [], []
        self.depth = depth

    def push(self, state):
        self.stack.append(copy.deepcopy(state))
        if len(self.stack) > self.depth:
            self.stack.pop(0)
        self.redo_stack.clear()

    def undo(self, current_state):
        if self.stack:
            self.redo_stack.append(copy.deepcopy(current_state))
            return self.stack.pop()
        return current_state

    def redo(self, current_state):
        if self.redo_stack:
            self.stack.append(copy.deepcopy(current_state))
            return self.redo_stack.pop()
        return current_state

    def clear(self):
        self.stack.clear()
        self.redo_stack.clear()


# --- Section 9: JSONStore helpers ---
class JSONStore:
    """Filesystem helper for timestamped JSON, atomic writes, and prefs."""
    APP_NAME       = Path(__file__).stem            # e.g. redact-3_GUI
    DATA_DIR       = Path(__file__).with_suffix('') # ./redact-3_GUI/
    TIMESTAMP_FMT  = "%Y-%m-%d-%H%M"
    _TS_RE         = re.compile(r'(\d{4}-\d{2}-\d{2}-\d{4})')
    PREFS_FILE     = DATA_DIR / f"{APP_NAME}_prefs.json"

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- basics ----------
    @staticmethod
    def write_atomic(path: Path, obj):
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(obj, indent=2))
            tmp.replace(path)                       # atomic on NT-/POSIX
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    @staticmethod
    def get_timestamped_filename(stem: str, purpose: str) -> str:
        """Return `<DATA_DIR>/<stem>_<purpose>_<YYYY-MM-DD-HHMM>.json`."""
        ts = datetime.now().strftime(JSONStore.TIMESTAMP_FMT)
        return str(JSONStore.DATA_DIR / f"{stem}_{purpose}_{ts}.json")  # :contentReference[oaicite:0]{index=0}

    @staticmethod
    def find_latest_file(stem: str, purpose: str) -> str | None:
        """Return autosave first, else most recent timestamped config, else None."""
        autosave = JSONStore.DATA_DIR / f"{stem}_{purpose}_autosave.json"
        if autosave.exists():
            return str(autosave)

        files = list(JSONStore.DATA_DIR.glob(f"{stem}_{purpose}_*.json"))
        if not files:
            return None

        def _ts(p: Path):
            m = JSONStore._TS_RE.search(p.stem)
            if m:
                try:
                    return datetime.strptime(m.group(1), JSONStore.TIMESTAMP_FMT)
                except ValueError: pass
            return datetime.fromtimestamp(p.stat().st_mtime)

        return str(max(files, key=_ts))

# pdf_canvas.py
import tkinter as tk, fitz
from PIL import Image, ImageTk, ImageDraw

class PDFCanvas(tk.Canvas):
    """A scrollable, zoomable Tk.Canvas that knows how to display a PDF page
    (PyMuPDF `fitz.Page`) and draw region overlays."""

    def __init__(self, master, **kw):
        super().__init__(master, background="#222", **kw)
        self.hbar = tk.Scrollbar(master, orient="horizontal",
                                 command=self.xview)
        self.vbar = tk.Scrollbar(master, orient="vertical",
                                 command=self.yview)
        self.configure(xscrollcommand=self.hbar.set,
                       yscrollcommand=self.vbar.set)

        # layout
        self.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        # state
        self.page: fitz.Page | None = None
        self.photo = None            # keep reference to avoid GC
        self.scale = 2.0             # default 2× render
        self.region_colours = {"redact": ("#ff7878", "#cc0000"),
                               "exclude": ("#78a0ff", "#0033cc"),
                               "protect": ("#78ff8f", "#009933")}

    # ---------- public API ----------
    def display(self, page: fitz.Page, regions: list[dict]):
        self.page = page
        pix = page.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # overlay
        draw = ImageDraw.Draw(img, "RGBA")
        for r in regions:
            if r["page"] != page.number: continue
            (fill, outline) = self.region_colours.get(r["kind"], ("grey", "black"))
            x0, y0, x1, y1 = [v * self.scale for v in r["bbox"]]
            draw.rectangle([x0, y0, x1, y1], fill=fill + "80", outline=outline, width=2)

        self.photo = ImageTk.PhotoImage(img)
        self.delete("all")
        self.create_image(0, 0, image=self.photo, anchor="nw")
        self.config(scrollregion=self.bbox("all"))

    # ---------- high-resolution panning ----------
    def start_pan(self, event):
        self.scan_mark(event.x, event.y)

    def drag_pan(self, event):
        self.scan_dragto(event.x, event.y, gain=1)


class PDFRedactorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(Path(__file__).name)

        # --- State Variables ---
        self.current_pdf = None
        self.pdf_stem = ""  # Stem of the current PDF file name, used for saving
        self.current_page = 0
        self.doc = None  # PyMuPDF document object
        self.scale_factor = 1.0  # Current zoom level

        # --- Refactored State Management ---
        self.current_tool: Tool = Tool.PAN  # Active tool enum
        self.history = HistoryManager()  # Undo/redo manager
        self.dirty = False  # Flag indicating unsaved changes in current session

        # In-memory state (the "source of truth") for configuration and regions
        self.patterns = {"keywords": [], "passages": []}  # Text patterns for redaction
        self.exclusions = []  # Text exclusions (prevent redaction)
        self.regions: list[Region] = []  # Manually drawn regions

        # UI and Interaction State variables
        self.tool_var = tk.StringVar(value=Tool.PAN.name)  # Tkinter variable for Radiobutton group
        self.drag_info = {}  # Dictionary to store state during drag operations (start coords, type, etc.)
        self.edit_region: Region | None = None  # The Region object currently being edited/resized
        self.temp_rect_id = None  # Canvas ID for temporary drawing rectangles (e.g., selection box)

        # --- Load Prefs and Configs ---
        self.prefs = self.load_prefs()  # Load application preferences (window geometry, last PDF)
        self.root.geometry(self.prefs.get("window_geometry", "1200x800"))
        self.load_app_configs()  # Load global (app-wide) patterns and exclusions

        # --- Setup UI and Bindings ---
        self.setup_ui()
        self.bind_shortcuts()
        # Trace changes to tool_var to sync with internal state (e.g., if a radio button is clicked)
        self.tool_var.trace_add("write", self.on_tool_var_change)
        self.set_tool(Tool.PAN)  # Set initial tool, cursor, and status label

        # --- Open last PDF if available ---
        last_pdf = self.prefs.get("last_pdf")
        if last_pdf and os.path.exists(last_pdf):
            self.open_pdf(path=last_pdf)
            self.scale_factor = self.prefs.get("last_zoom", 1.0)
            self.display_page()  # Display the loaded PDF page

    # --- Tool Management & UI Sync ---
    def on_tool_var_change(self, *args):
        """Callback for when the tool_var (e.g., from a Radiobutton) changes."""
        try:
            tool_enum = Tool[self.tool_var.get()]  # Convert string name back to Enum
            # Only change the tool if it's different from the current one to prevent infinite recursion
            if self.current_tool != tool_enum:
                self.set_tool(tool_enum)
        except KeyError:
            print(f"Warning: Unknown tool name in tool_var: {self.tool_var.get()}")

    def set_tool(self, tool: Tool):
        """The single point of control for changing the active tool. Updates UI elements."""
        if self.current_tool == tool:
            return  # No change needed if already active

        # If currently in EDIT_REGION mode, finalize it before switching
        if self.edit_region:
            self._exit_edit_mode()

        self.current_tool = tool  # Update internal state
        self.tool_var.set(tool.name)  # Sync Tkinter variable (e.g., highlight the correct radio button)

        # Define tool colors and descriptive text for the status label
        tool_colors = {
            "PAN": ("#cccccc", "Pan (Space)"),
            "TEXT_SELECT": ("#f2e55c", "Select Text (t)"),
            "DRAW_REDACT": ("#ff7878", "Draw Redact (r)"),
            "DRAW_EXCLUDE": ("#78a0ff", "Draw Exclude (e)"),
            "DRAW_PROTECT": ("#78ff8f", "Draw Protect (p)"),
            "EDIT_REGION": ("#b0b0b0", "Edit Region"),
        }
        color, text = tool_colors.get(tool.name, ("white", "Unknown Tool"))

        self.status_lbl.config(bg=color, text=text)  # Update status label background and text

        # Define cursor shapes for each tool
        cursor_map = {
            "PAN": "hand2",
            "TEXT_SELECT": "ibeam",
            "DRAW_REDACT": "tcross",
            "DRAW_EXCLUDE": "dot",
            "DRAW_PROTECT": "diamond_cross",
            "EDIT_REGION": "fleur",
        }
        self.canvas.config(cursor=cursor_map.get(tool.name, "arrow"))  # Update canvas cursor

    # --- Dirty Flag, Autosave, and History ---
    def _collect_state(self) -> dict:
        """Collects the current in-memory state for saving or undo/redo."""
        return {
            "patterns": self.patterns,
            "exclusions": self.exclusions,
            # Convert Region dataclass objects to dictionaries for JSON serialization
            "regions": [asdict(r) for r in self.regions]
        }

    def _apply_state(self, state: dict):
        """Applies a given state to the in-memory data and refreshes the UI."""
        self.patterns = state.get("patterns", {"keywords": [], "passages": []})
        self.exclusions = state.get("exclusions", [])
        # Convert dictionaries back to Region dataclass objects
        self.regions = [Region(**r) for r in state.get("regions", [])]

        # Refresh UI elements to reflect the new state
        self._update_patterns_ui()
        self._update_exclusions_ui()
        self.display_page()  # Redraw canvas to show region changes

    def _mark_dirty(self, record_undo: bool = True):
        """Marks the current state as dirty and schedules an autosave if not already scheduled."""
        if record_undo:
            # Push state *before* the change is applied, so undo reverts to this point
            self.history.push(self._collect_state())

        if not self.dirty:
            self.dirty = True
            # Schedule the flush only if it's the first dirtying action in this cycle
            self.root.after(3000, self._flush_cache_if_dirty)  # Schedule after 3 seconds

    def _autosave_path(self) -> Path | None:
        """Returns the Path object for the document-specific autosave file."""
        if not self.pdf_stem: return None
        return JSONStore.DATA_DIR / f"{self.pdf_stem}_full_autosave.json"

    def _flush_cache_if_dirty(self):
        """Writes the current state to the autosave file if the dirty flag is set."""
        if self.dirty and self.pdf_stem:  # Ensure there's a document loaded and changes exist
            path = self._autosave_path()
            if path:  # Ensure path is not None
                JSONStore.write_atomic(path, self._collect_state())
            self.dirty = False  # Reset flag for the next cycle of changes
            self.status_bar.config(text=f"Autosaved at {datetime.now().strftime('%H:%M:%S')}")

    # --- Config and Preference Management ---
    def load_prefs(self):
        """Loads user preferences (window geometry, last opened PDF) from disk."""
        if JSONStore.PREFS_FILE.exists():
            try:
                return json.loads(JSONStore.PREFS_FILE.read_text())
            except (json.JSONDecodeError, IOError):
                # Handle corrupted or unreadable preferences file
                print(f"Warning: Could not read preferences file, starting with defaults: {JSONStore.PREFS_FILE}")
                return {}
        return {}

    def save_prefs(self):
        """Saves current user preferences to disk."""
        self.prefs['window_geometry'] = self.root.geometry()
        if self.current_pdf:
            self.prefs['last_pdf'] = self.current_pdf
            self.prefs['last_zoom'] = self.scale_factor
        JSONStore.write_atomic(JSONStore.PREFS_FILE, self.prefs)

    def on_closing(self):
        """Handles application closing event, saving unsaved work and preferences."""
        self._flush_cache_if_dirty()  # Ensure any pending changes are autosaved
        self.save_prefs()
        self.root.destroy()  # Close the Tkinter window

    def load_app_configs(self):
        """Loads global (app-wide) patterns and exclusions from their latest files."""
        # --- FIX: Ensure file existence before attempting to open ---
        latest_patterns_path = JSONStore.find_latest_file("app_wide", 'patterns')
        if latest_patterns_path and Path(latest_patterns_path).exists():
            try:
                with open(latest_patterns_path, 'r') as f:
                    self.patterns = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                print(f"Warning: Could not load app_wide patterns from {latest_patterns_path}, starting with defaults.")
                self.patterns = {"keywords": [], "passages": []}
        else:
            self.patterns = {"keywords": [], "passages": []}

        latest_exclusions_path = JSONStore.find_latest_file("app_wide", 'exclusions')
        if latest_exclusions_path and Path(latest_exclusions_path).exists():
            try:
                with open(latest_exclusions_path, 'r') as f:
                    self.exclusions = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                print(
                    f"Warning: Could not load app_wide exclusions from {latest_exclusions_path}, starting with defaults.")
                self.exclusions = []
        else:
            self.exclusions = []

    def save_app_configs(self, patterns=True, exclusions=True):
        """Saves current global patterns and/or exclusions to new timestamped files."""
        if patterns:
            fname_patterns = JSONStore.get_timestamped_filename("app_wide", 'patterns')
            with open(fname_patterns, 'w') as f: json.dump(self.patterns, f, indent=2)
        if exclusions:
            fname_exclusions = JSONStore.get_timestamped_filename("app_wide", 'exclusions')
            with open(fname_exclusions, 'w') as f: json.dump(self.exclusions, f, indent=2)
        messagebox.showinfo("Success", "Configuration saved as new timestamped file.", parent=self.root)

    # --- Keyboard and Mouse Bindings ---
    def bind_shortcuts(self):
        """Binds global keyboard shortcuts and canvas mouse events."""
        # Page Navigation shortcuts
        for key in ('<Left>', '<Right>', '<Prior>', '<Next>'):
            self.root.bind(key, lambda e: self.prev_page() if e.keysym in ('Left', 'Prior') else self.next_page())

        # File/Edit Actions shortcuts
        self.root.bind('<Control-s>', lambda e: self.save_redacted_pdf())
        self.root.bind('<Control-o>', lambda e: self.open_pdf())
        self.root.bind('<Control-p>', lambda e: self.toggle_preview())
        self.root.bind('<Control-z>', self.undo_action)
        self.root.bind('<Control-y>', self.redo_action)
        self.root.bind('<Control-Shift-Z>', self.redo_action)  # Common alternative for redo
        for key in ('<Delete>', '<BackSpace>'):
            self.root.bind(key, self.delete_selected_item)  # Bind to a unified delete handler

        # Tool Switching shortcuts (global, but Space only works when canvas is focused)
        self.root.bind('<Escape>', lambda e: self.set_tool(Tool.PAN))  # Escape always reverts to Pan
        # Bind space to pan tool only if canvas is the active widget (prevents interfering with text entry)
        self.root.bind('<space>', lambda e: self.set_tool(Tool.PAN) if self.root.focus_get() == self.canvas else None)
        self.root.bind('<r>', lambda e: self.set_tool(Tool.DRAW_REDACT))
        self.root.bind('<e>', lambda e: self.set_tool(Tool.DRAW_EXCLUDE))
        self.root.bind('<p>', lambda e: self.set_tool(Tool.DRAW_PROTECT))
        self.root.bind('<t>', lambda e: self.set_tool(Tool.TEXT_SELECT))
        self.root.bind('<Return>', self._handle_return_key)  # For committing edits or exiting modes

        # Canvas Mouse Actions (for scrolling and zooming)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)  # Windows/macOS scroll
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)  # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)  # Linux scroll down
        self.canvas.bind("<Shift-MouseWheel>", self.on_shift_wheel)  # Horizontal scroll
        self.canvas.bind("<Control-MouseWheel>", self.on_ctrl_wheel)  # Zoom

        # Protocol for graceful window closing (e.g., X button)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _handle_return_key(self, event=None):
        """Handles the Return key press, primarily for exiting region edit mode."""
        if self.current_tool == Tool.EDIT_REGION:
            self.set_tool(Tool.PAN)  # Exit edit mode to Pan tool
        return "break"  # Prevent default behavior (e.g., adding a newline in a focused text widget)

    # --- UI Setup ---
    def setup_ui(self):
        """Initializes the main window GUI elements (menus, toolbars, canvas, side panels)."""
        # Menubar setup
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open PDF (Ctrl+O)", command=self.open_pdf)
        file_menu.add_command(label="Save Redacted PDF (Ctrl+S)", command=self.save_redacted_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Save Config Now", command=lambda: self.save_app_configs())
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo (Ctrl+Z)", command=self.undo_action)
        edit_menu.add_command(label="Redo (Ctrl+Y)", command=self.redo_action)
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selected (Del)", command=self.delete_selected_item)

        # Top Toolbar Frame (contains tool buttons, preview, status, and navigation)
        top_frame = ttk.Frame(self.root)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # --- NEW: Tool Buttons Toolbar ---
        tool_frame = ttk.LabelFrame(top_frame, text="Tools")  # LabelFrame for better visual grouping
        tool_frame.pack(side=tk.LEFT, padx=5)

        style = ttk.Style()
        style.configure("Tool.TRadiobutton", padding=5, anchor='center')  # Custom style for radio buttons

        tool_buttons_data = [
            ("Pan (Space)", Tool.PAN),
            ("Text (t)", Tool.TEXT_SELECT),
            ("Redact (r)", Tool.DRAW_REDACT),
            ("Exclude (e)", Tool.DRAW_EXCLUDE),
            ("Protect (p)", Tool.DRAW_PROTECT)
        ]
        # Create a Radiobutton for each tool
        for text, tool_enum in tool_buttons_data:
            rb = ttk.Radiobutton(tool_frame, text=text, variable=self.tool_var,
                                 value=tool_enum.name, style="Tool.TRadiobutton")
            rb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, pady=2)

        # Preview Checkbutton and Status Label
        control_frame = ttk.Frame(top_frame)
        control_frame.pack(side=tk.LEFT, padx=10)
        self.preview_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(control_frame, text="Preview (Ctrl+P)", variable=self.preview_var,
                        command=self.display_page).pack(side=tk.LEFT, pady=5)
        # Status label to show active tool and color-code it
        self.status_lbl = tk.Label(control_frame, width=15, relief="sunken", anchor='center')
        self.status_lbl.pack(side=tk.LEFT, padx=10, ipady=2)

        # Page Navigation Buttons
        nav_frame = ttk.Frame(top_frame)
        nav_frame.pack(side=tk.RIGHT, padx=5)
        ttk.Button(nav_frame, text="< Prev", command=self.prev_page).pack(side=tk.LEFT)
        self.page_label = ttk.Label(nav_frame, text="No PDF", width=12, anchor='center')
        self.page_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="Next >", command=self.next_page).pack(side=tk.LEFT)

        # Main Content Frame (PanedWindow for resizable sections - Canvas and Side Panels)
        main_frame = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Canvas and Scrollbars Container
        canvas_container = ttk.Frame(main_frame)
        main_frame.add(canvas_container, weight=3)  # Canvas takes 3 parts of space
        self.canvas = tk.Canvas(canvas_container, bg="gray")
        v_scrollbar = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        # Use grid layout for canvas and scrollbars within their container
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)

        # Canvas Mouse Interaction Bindings
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)

        # Right Panel Notebook (Tabs for Patterns/Exclusions)
        right_panel = ttk.Notebook(main_frame)
        main_frame.add(right_panel, weight=1)  # Right panel takes 1 part of space
        self.create_patterns_tab(right_panel)
        self.create_exclusions_tab(right_panel)

        # Status Bar at the bottom
        self.status_bar = ttk.Label(self.root, text="Ready. Use Ctrl+O to open a PDF.", relief=tk.SUNKEN, anchor='w')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, ipady=2)

    def create_patterns_tab(self, parent_notebook):
        """Creates the 'Redaction Text' tab for managing keywords and passages."""
        parent = ttk.Frame(parent_notebook)
        parent_notebook.add(parent, text="Redaction Text")

        # Keywords Listbox
        ttk.Label(parent, text="Keywords:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)
        keywords_frame = ttk.Frame(parent)
        keywords_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.keywords_listbox = tk.Listbox(keywords_frame, height=10)
        self.keywords_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Manual scrollbar packing as a temporary workaround for issue with ttk.Scrollbar in Tkinter 8.6
        keywords_scrollbar = ttk.Scrollbar(keywords_frame, command=self.keywords_listbox.yview)
        keywords_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.keywords_listbox.config(yscrollcommand=keywords_scrollbar.set)

        # Passages Text Area
        ttk.Label(parent, text="Passages (separate with ---):", font=("", 10, "bold")).pack(anchor=tk.W, padx=5,
                                                                                            pady=(10, 5))
        self.passages_text = scrolledtext.ScrolledText(parent, height=10, width=40)
        self.passages_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        # Bindings for in-place editing on listbox items
        self._setup_listbox_editing(self.keywords_listbox, self.update_pattern_from_edit)
        # Bind FocusOut to save passages when the text area loses focus
        self.passages_text.bind("<FocusOut>", self.update_passages_from_edit)
        self._update_patterns_ui()  # Populate initial data from loaded config

    def create_exclusions_tab(self, parent_notebook):
        """Creates the 'Exclusion Text' tab for managing exclusion terms."""
        parent = ttk.Frame(parent_notebook)
        parent_notebook.add(parent, text="Exclusion Text")

        ttk.Label(parent, text="Text to Preserve:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)
        exclusions_frame = ttk.Frame(parent)
        exclusions_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.exclusions_listbox = tk.Listbox(exclusions_frame)
        self.exclusions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Manual scrollbar packing
        exclusions_scrollbar = ttk.Scrollbar(exclusions_frame, command=self.exclusions_listbox.yview)
        exclusions_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.exclusions_listbox.config(yscrollcommand=exclusions_scrollbar.set)

        # Bindings for in-place editing
        self._setup_listbox_editing(self.exclusions_listbox, self.update_exclusion_from_edit)
        self._update_exclusions_ui()  # Populate initial data from loaded config

    def _update_patterns_ui(self):
        """Refreshes the keywords listbox and passages text area with current patterns data."""
        self.keywords_listbox.delete(0, tk.END)
        for keyword in self.patterns.get("keywords", []): self.keywords_listbox.insert(tk.END, keyword)

        self.passages_text.delete(1.0, tk.END)
        self.passages_text.insert(tk.END, "\n---\n".join(self.patterns.get("passages", [])))

    def _update_exclusions_ui(self):
        """Refreshes the exclusions listbox with current exclusions data."""
        self.exclusions_listbox.delete(0, tk.END)
        for exclusion in self.exclusions: self.exclusions_listbox.insert(tk.END, exclusion)

    def _setup_listbox_editing(self, lb, commit_callback):
        """Configures in-place editing for a given listbox on double-click."""
        lb.bind("<Double-Button-1>", lambda e, l=lb, cb=commit_callback: self._start_listbox_edit(e, l, cb))

    def _start_listbox_edit(self, event, lb, commit_callback):
        """Initiates an in-place edit for a listbox item by creating a temporary Entry widget."""
        selection = lb.curselection()
        if not selection: return
        idx, text = selection[0], lb.get(selection[0])
        x, y, w, h = lb.bbox(idx)  # Get coordinates of the listbox item

        # Create a temporary Entry widget over the listbox item
        entry = ttk.Entry(lb)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, text)
        entry.select_range(0, 'end')  # Select all text for easy replacement
        entry.focus_set()  # Give focus to the entry widget

        # Define commit/cancel actions for the entry widget
        def commit_edit(e):
            new_text = entry.get().strip()
            entry.destroy()  # Remove the entry widget
            if new_text and new_text != text:  # Only commit if text changed and is not empty
                commit_callback(idx, new_text)  # Call the specific callback to update data

        def cancel_edit(e):
            entry.destroy()  # Simply remove the entry widget without saving

        # Bind events to the Entry widget
        entry.bind("<Return>", commit_edit)  # Commit on Enter key
        entry.bind("<FocusOut>", cancel_edit)  # Cancel on losing focus
        entry.bind("<Escape>", cancel_edit)  # Cancel on Escape key

    def update_pattern_from_edit(self, index, new_text):
        """Updates a keyword pattern in self.patterns['keywords'] after in-place editing."""
        if new_text and new_text != self.patterns['keywords'][index]:
            self._mark_dirty()  # Mark as dirty to trigger autosave/undo history
            self.patterns['keywords'][index] = new_text
            self._update_patterns_ui()  # Refresh UI to show the updated keyword

    def update_exclusion_from_edit(self, index, new_text):
        """Updates an exclusion term in self.exclusions after in-place editing."""
        if new_text and new_text != self.exclusions[index]:
            self._mark_dirty()
            self.exclusions[index] = new_text
            self._update_exclusions_ui()

    def update_passages_from_edit(self, event=None):
        """Updates passages in self.patterns['passages'] after the ScrolledText widget loses focus."""
        new_passages = [p.strip() for p in self.passages_text.get(1.0, tk.END).strip().split('---') if p.strip()]
        if new_passages != self.patterns.get("passages", []):
            self._mark_dirty()
            self.patterns["passages"] = new_passages

    def delete_selected_item(self, event=None):
        """Handles deletion of selected items from listboxes or the active region from the canvas."""
        widget = self.root.focus_get()  # Get the currently focused widget
        if widget == self.keywords_listbox:
            self._delete_from_list(self.keywords_listbox, self.patterns['keywords'])
        elif widget == self.exclusions_listbox:
            self._delete_from_list(self.exclusions_listbox, self.exclusions)
        elif widget == self.canvas and self.edit_region:  # If canvas is focused and a region is being edited
            self._delete_region(self.edit_region)  # Delete the edited region
            self.set_tool(Tool.PAN)  # Exit edit mode to Pan tool after deletion
        return "break"  # Prevent further event propagation (e.g., from Delete key triggering system dialogs)

    def _delete_from_list(self, listbox, data_list):
        """Helper to delete selected items from a generic listbox and its backing data list."""
        selection = listbox.curselection()
        if not selection: return
        self._mark_dirty()  # Mark dirty as data is changing
        # Iterate backwards through selected indices to avoid index shifting issues when deleting
        for index in sorted(selection, reverse=True):
            del data_list[index]
        self._update_patterns_ui()  # Refresh both pattern lists (in case of cross-tab interaction)
        self._update_exclusions_ui()  # Refresh exclusion list

    # --- Event Handlers for Zoom, Pan, etc. ---
    def toggle_preview(self):
        """Toggles the redaction preview mode on/off."""
        self.preview_var.set(not self.preview_var.get())
        self.display_page()  # Redraw page to apply/remove preview

    def on_mouse_wheel(self, event):
        """Handles vertical scrolling with mouse wheel."""
        # Normalize event.delta for Windows/macOS, event.num for Linux (4=up, 5=down)
        self.canvas.yview_scroll(-1 if event.delta > 0 or event.num == 4 else 1, "units")

    def on_shift_wheel(self, event):
        """Handles horizontal scrolling with Shift + mouse wheel."""
        self.canvas.xview_scroll(-1 if event.delta > 0 or event.num == 4 else 1, "units")

    def on_ctrl_wheel(self, event):
        """Handles zoom in/out with Ctrl + mouse wheel."""
        zoom_factor = 1.1 if event.delta > 0 or event.num == 4 else 1 / 1.1  # 1.1 for zoom in, 1/1.1 for zoom out
        self.scale_factor = max(0.2, min(self.scale_factor * zoom_factor, 10.0))  # Clamp zoom factor
        self.display_page()  # Redraw page with new zoom level

    # --- PDF and Page Management ---
    def open_pdf(self, path=None):
        """Opens a PDF document, loads its associated state, and displays the first page."""
        filename = path or filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if not filename or not os.path.exists(filename):
            if path: self.status_bar.config(text=f"Could not find last PDF: {path}")
            return

        try:
            self.doc = fitz.open(filename)
            self.current_pdf = filename
            self.pdf_stem = Path(self.current_pdf).stem  # Extract stem for file-specific saves
            self.current_page = 0
            if not path:  # Reset zoom to 1.0 only when opening a new file manually (not from last session)
                self.scale_factor = 1.0

            # Load document-specific state (regions) from autosave or latest full save
            state_file_path_str = self._autosave_path()  # Get autosave Path object
            if state_file_path_str is None or not Path(state_file_path_str).exists():
                # If no autosave, try looking for a timestamped full save file
                state_file_path_str = JSONStore.find_latest_file(self.pdf_stem, 'full')

            # --- FIX: Ensure state_file_path_str is not None before using Path() ---
            if state_file_path_str is not None and Path(state_file_path_str).exists():
                try:
                    loaded_state = json.loads(Path(state_file_path_str).read_text())
                    # Only load regions from this file; patterns/exclusions are app-wide
                    self.regions = [Region(**r) for r in loaded_state.get("regions", [])]
                except (json.JSONDecodeError, FileNotFoundError):
                    print(f"Warning: Could not load state from {state_file_path_str}, starting with no regions.")
                    self.regions = []
            else:
                self.regions = []  # No state file found for this PDF, start with no regions

            self.history.clear()  # Clear undo/redo history for the new document
            self.dirty = False  # Reset dirty flag as state is freshly loaded
            self.display_page()  # Display the first page of the loaded PDF
            self.save_prefs()  # Save last opened PDF to preferences
            self.status_bar.config(text=f"Opened: {os.path.basename(self.current_pdf)}")
        except Exception as e:
            messagebox.showerror("Error Opening PDF", f"Could not open or process the file:\n{e}")
            self.doc = None  # Clear document if opening failed
            self.current_pdf = None

    def display_page(self):
        """Renders the current PDF page on the canvas, including regions and preview effects."""
        if not self.doc:
            self.canvas.delete("all")  # Clear canvas if no document
            self.page_label.config(text="No PDF loaded")
            return

        self.canvas.delete("all")  # Clear existing content on canvas
        page = self.doc[self.current_page]

        # Get pixmap (rasterized image) of the page with current scale factor
        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        pix = page.get_pixmap(matrix=mat, alpha=False)  # alpha=False for RGB, faster
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Apply preview redactions to the image if preview mode is active
        if self.preview_var.get():
            draw = ImageDraw.Draw(img)  # Create a drawing object for the PIL image

            # Apply text redactions based on patterns and exclusions
            all_patterns = self.patterns.get("keywords", []) + self.patterns.get("passages", [])
            for pattern in all_patterns:
                if not pattern: continue  # Skip empty patterns

                # Search for all occurrences of the pattern on the page
                for area in page.search_for(pattern):
                    # Check if this text area falls within a "protect" region (drawn by user)
                    is_protected_by_region = False
                    for r in self.regions:
                        if r.page == self.current_page and r.kind == "protect" and fitz.Rect(r.bbox).intersects(area):
                            is_protected_by_region = True
                            break
                    if is_protected_by_region: continue  # Skip redaction if protected

                    # Check if this text is explicitly in the exclusions list (text-based)
                    # Get text in a slightly larger context to handle partial matches or surrounding words
                    context_rect = area.irect  # BBox of the found text
                    context_rect.x0 = max(0, context_rect.x0 - 5)  # Expand slightly
                    context_rect.y0 = max(0, context_rect.y0 - 5)
                    context_rect.x1 = min(page.rect.width, context_rect.x1 + 5)
                    context_rect.y1 = min(page.rect.height, context_rect.y1 + 5)

                    context_text = page.get_textbox(context_rect)

                    if not any(excl.lower() in context_text.lower() for excl in self.exclusions):
                        # If not protected by a region and not explicitly excluded by text, draw black rectangle
                        draw.rectangle((area * mat).irect, fill="black")

                        # Apply drawn region redactions (only for "redact" kind) to the image
            for r in self.regions:
                if r.page == self.current_page and r.kind == "redact":
                    draw.rectangle(list(fitz.Rect(r.bbox) * mat), fill="black")

        # Convert PIL image to Tkinter PhotoImage and display on canvas
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo, tags="bg_image")
        self.canvas.config(scrollregion=self.canvas.bbox("all"))  # Set scrollable area

        # Draw interactive regions (redact, exclude, protect outlines) if not in preview mode
        if not self.preview_var.get():
            self._draw_all_regions()

        # Update page number label
        self.page_label.config(text=f"Page {self.current_page + 1}/{len(self.doc)}")

    def _draw_all_regions(self):
        """Draws all regions for the current page on the canvas with their respective colors."""
        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        # Colors for filled rectangle (lighter) and outline (darker) for each kind of region
        region_colors = {
            "redact": {"fill": "#ff7878", "outline": "#cc0000"},  # Red for redaction
            "exclude": {"fill": "#78a0ff", "outline": "#0033cc"},  # Blue for exclusion
            "protect": {"fill": "#78ff8f", "outline": "#009933"}  # Green for protection
        }
        for r in self.regions:
            r.canvas_id = None  # Clear old canvas ID to ensure fresh drawing and prevent ghosting
            if r.page == self.current_page:  # Only draw regions for the current page
                colors = region_colors.get(r.kind, {"fill": "grey", "outline": "black"})
                bbox_scaled = list(fitz.Rect(r.bbox) * mat)  # Scale PDF bbox to canvas pixels

                # Use stipple (dotted pattern) for non-selected regions to make them less opaque
                stipple = "" if r == self.edit_region else "gray50"
                r.canvas_id = self.canvas.create_rectangle(*bbox_scaled, fill=colors["fill"],
                                                           outline=colors["outline"], width=2,
                                                           stipple=stipple, tags="region")  # Assign "region" tag

        # If in edit mode, redraw handles for the currently selected region
        if self.edit_region:
            self._draw_edit_handles()

    def _draw_edit_handles(self):
        """Draws resize handles (small squares) for the currently edited region."""
        self.canvas.delete("handle")  # Clear existing handles before redrawing
        if not self.edit_region or self.edit_region.canvas_id is None: return  # No region to edit or not drawn yet

        # Make the active region's main rectangle solid (remove stipple)
        self.canvas.itemconfig(self.edit_region.canvas_id, stipple="")

        # Calculate scaled rectangle for handles
        r = fitz.Rect(self.edit_region.bbox) * fitz.Matrix(self.scale_factor, self.scale_factor)
        s = 5  # Handle size in pixels

        # Coordinates for all 8 corner and midpoint handles
        coords = {
            "nw": (r.x0, r.y0), "n": (r.center.x, r.y0), "ne": (r.x1, r.y0),
            "w": (r.x0, r.center.y), "e": (r.x1, r.center.y),
            "sw": (r.x0, r.y1), "s": (r.center.x, r.y1), "se": (r.x1, r.y1),
        }
        for tag, (x, y) in coords.items():
            # Create a small rectangle for each handle
            self.canvas.create_rectangle(x - s, y - s, x + s, y + s, fill="white", outline="black",
                                         tags=("handle", tag))

    def prev_page(self):
        """Navigates to the previous page if available."""
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()

    def next_page(self):
        """Navigates to the next page if available."""
        if self.doc and self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self.display_page()

    # --- Undo/Redo System ---
    def undo_action(self, event=None):
        """Performs an undo operation, restoring the previous application state."""
        new_state = self.history.undo(self._collect_state())
        if new_state is not self._collect_state():  # Only apply if a change actually occurred
            self._apply_state(new_state)

    def redo_action(self, event=None):
        """Performs a redo operation, restoring a previously undone state."""
        new_state = self.history.redo(self._collect_state())
        if new_state is not self._collect_state():  # Only apply if a change actually occurred
            self._apply_state(new_state)

    # --- Section 5 & 7: Region/Text Drawing and Modification ---

    def on_canvas_press(self, event):
        """Mouse-down: decide whether we’re panning or drawing."""
        if self.preview_var.get():     # preview mode blocks edits
            return

        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.drag_info.clear()

        if self.current_tool == Tool.PAN:
            self.canvas.scan_mark(event.x, event.y)   # <— TK native pan
            return

        # … existing edit-region logic unchanged …

        # starting a new rectangle
        self.drag_info["start_x"] = cx
        self.drag_info["start_y"] = cy
        colour = {"TEXT_SELECT": "yellow",
                  "DRAW_REDACT": "red",
                  "DRAW_EXCLUDE": "blue",
                  "DRAW_PROTECT": "green"}.get(self.current_tool.name)
        if colour:
            self.temp_rect_id = self.canvas.create_rectangle(
                cx, cy, cx, cy, outline=colour, dash=(3, 4)
            )

    def on_canvas_drag(self, event):
        """Mouse-move while button held."""
        if self.preview_var.get() or not self.drag_info:
            return

        if self.current_tool == Tool.PAN:
            self.canvas.scan_dragto(event.x, event.y, gain=1)  # <— TK native pan
            return

        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        if self.current_tool == Tool.EDIT_REGION and self.edit_region:
            self._resize_or_move_region(cx, cy)
        elif self.temp_rect_id:
            self.canvas.coords(self.temp_rect_id,
                               self.drag_info["start_x"], self.drag_info["start_y"],
                               cx, cy)

    def on_canvas_release(self, event):
        """Handles mouse button release events on the canvas, finalizing drawing or editing."""
        if not self.drag_info or self.preview_var.get(): return  # Ignore if no drag in progress or in preview

        if self.current_tool == Tool.PAN:
            self.drag_info.clear()  # End panning operation
            return

        if self.current_tool == Tool.EDIT_REGION:
            if "region" in self.drag_info:  # If a resize/move operation was in progress
                self._mark_dirty()  # Record the final state after manipulation
            self.drag_info.clear()  # Clear drag info
            return  # Exit, as edit operations are finalized

        # If a temporary rectangle was drawn, remove it
        if self.temp_rect_id: self.canvas.delete(self.temp_rect_id); self.temp_rect_id = None

        x0, y0 = self.drag_info["start_x"], self.drag_info["start_y"]
        x1, y1 = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        # Ignore very small drag gestures (e.g., accidental clicks)
        if abs(x1 - x0) < 5 and abs(y1 - y0) < 5: return

        if self.current_tool == Tool.TEXT_SELECT:
            is_exclusion = (event.state & 0x0001) != 0  # Check for Shift key press (state bit 0 is Shift)
            self._process_text_selection(x0, y0, x1, y1, is_exclusion)
        elif self.current_tool in [Tool.DRAW_REDACT, Tool.DRAW_EXCLUDE, Tool.DRAW_PROTECT]:
            # Convert canvas coordinates to PDF coordinates for storing the region
            mat = fitz.Matrix(1 / self.scale_factor, 1 / self.scale_factor)
            bbox = tuple(fitz.Rect(x0, y0, x1, y1).normalize() * mat)  # Normalize ensures x0<x1, y0<y1

            kind = self.current_tool.name.split('_')[1].lower()  # Extract kind (e.g., "redact")
            new_region = Region(page=self.current_page, bbox=bbox, kind=kind)

            self._mark_dirty()  # Mark state as dirty (adds to undo history and schedules autosave)
            self.regions.append(new_region)  # Add new region to the in-memory list
            self.display_page()  # Redraw canvas to show the new region
        self.drag_info.clear()  # Clear drag state

    def on_canvas_double_click(self, event):
        """Handles double-click events on the canvas, primarily for entering region edit mode."""
        # Find the canvas item directly under the mouse that has the "region" tag
        clicked_items = self.canvas.find_withtag("current")  # "current" is the item under the mouse
        if clicked_items and "region" in self.canvas.gettags(clicked_items[0]):
            clicked_id = clicked_items[0]
            # Find the corresponding Region object in our data model
            for r in self.regions:
                if r.page == self.current_page and r.canvas_id == clicked_id:
                    self.edit_region = r  # Set this region as the one to be edited
                    self.set_tool(Tool.EDIT_REGION)  # Switch to edit tool
                    self.display_page()  # Redraw to show handles on the selected region
                    break

    def _exit_edit_mode(self):
        """Exits the region editing mode, clearing the edit_region and redrawing the canvas."""
        self.edit_region = None
        self.display_page()  # Redraw to remove handles and revert region appearance
        self.drag_info.clear()  # Clear any drag-related info

    def _resize_or_move_region(self, canvas_x, canvas_y):
        """Adjusts the size or position of the `edit_region` during a drag operation."""
        if not self.edit_region: return  # Should not happen if logic is sound

        # Convert canvas coordinates back to PDF coordinates for calculation
        mat = fitz.Matrix(1 / self.scale_factor, 1 / self.scale_factor)
        r = list(self.edit_region.bbox)  # Get mutable list from immutable tuple bbox

        if self.drag_info.get("type") == "resize":
            handle = self.drag_info["handle"]
            px, py = canvas_x * mat.a, canvas_y * mat.d  # Current mouse pos in PDF coords

            if "n" in handle: r[1] = py  # North: adjust top edge (y1)
            if "s" in handle: r[3] = py  # South: adjust bottom edge (y2)
            if "w" in handle: r[0] = px  # West: adjust left edge (x1)
            if "e" in handle: r[2] = px  # East: adjust right edge (x2)

            self.edit_region.bbox = tuple(fitz.Rect(r).normalize())  # Update and normalize bbox (x1<x2, y1<y2)
        elif self.drag_info.get("type") == "move":
            # Calculate displacement from the original start of the drag (in PDF coords)
            dx = (canvas_x / self.scale_factor) - self.drag_info["start_x"]
            dy = (canvas_y / self.scale_factor) - self.drag_info["start_y"]

            r[0] += dx;
            r[2] += dx  # Move horizontally
            r[1] += dy;
            r[3] += dy  # Move vertically
            self.edit_region.bbox = tuple(r)

            # Update drag_info's start_x/y to accumulate movement for the next drag event
            self.drag_info["start_x"] += dx
            self.drag_info["start_y"] += dy

        self.display_page()  # Redraw for live visual update during drag

    def _delete_region(self, region_to_delete: Region):
        """Removes a specified region from the list and refreshes the display."""
        self._mark_dirty()  # Mark dirty (adds to undo history)
        self.regions.remove(region_to_delete)  # Remove from in-memory list
        self.display_page()  # Redraw to update canvas

    def _process_text_selection(self, x0, y0, x1, y1, is_for_exclusion):
        """Extracts text from a selected canvas area and adds it to patterns/exclusions lists."""
        if not self.doc: return
        page = self.doc[self.current_page]

        # Convert canvas coordinates to PDF coordinates for text extraction
        rect_pdf = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y1, y0)) * fitz.Matrix(1 / self.scale_factor,
                                                                                               1 / self.scale_factor)

        # Get text from the PDF page within the selected rectangle
        selected_text = page.get_textbox(rect_pdf).strip()
        selected_text = re.sub(r'\s+', ' ', selected_text)  # Normalize whitespace (remove multiple spaces)

        if not selected_text:
            self.status_bar.config(text="No text found in selection.")
            return

        self._mark_dirty()  # Mark state as dirty as text patterns/exclusions are changing
        if is_for_exclusion:
            if selected_text not in self.exclusions:
                self.exclusions.append(selected_text)
                self._update_exclusions_ui()  # Refresh listbox
                self.status_bar.config(text=f"Added to exclusions: '{selected_text[:40]}...'")
            else:
                self.status_bar.config(text=f"'{selected_text[:40]}...' already in exclusions.")
        else:  # Add to passages for redaction
            current_passages = self.patterns.get("passages", [])
            if selected_text not in current_passages:
                current_passages.append(selected_text)
                self.patterns["passages"] = current_passages  # Update the patterns dict directly
                self._update_patterns_ui()  # Refresh text area
                self.status_bar.config(text=f"Added to passages: '{selected_text[:40]}...'")
            else:
                self.status_bar.config(text=f"'{selected_text[:40]}...' already in passages.")

    # --- Save, Apply Redactions ---
    def save_redacted_pdf(self):
        """Initiates the process of saving the PDF with all applied redactions."""
        if not self.doc: return messagebox.showerror("Error", "No PDF loaded")

        self._flush_cache_if_dirty()  # Ensure latest in-memory changes are autosaved before explicit save

        # Save the full state (patterns, exclusions, regions) to a timestamped file for future loading
        state_fname = JSONStore.get_timestamped_filename(self.pdf_stem, 'full')
        JSONStore.write_atomic(Path(state_fname), self._collect_state())

        output_file = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")],
            initialfile=f"{self.pdf_stem}_redacted.pdf", title="Save Redacted PDF As"
        )
        if not output_file: return  # User cancelled save dialog

        try:
            self.apply_all_redactions(output_file)  # Perform the actual PDF redaction
            messagebox.showinfo("Success", f"Redacted PDF saved to:\n{output_file}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save redacted PDF:\n{e}")
            import traceback  # Print full traceback to console for detailed debugging
            traceback.print_exc()

    def apply_all_redactions(self, output_file):
        """Applies all redacction regions and text patterns to a new PDF document."""
        output_doc = fitz.open(self.current_pdf)  # Open a fresh copy of the original PDF

        # Combine keywords and passages for text redaction
        all_patterns = self.patterns.get("keywords", []) + self.patterns.get("passages", [])

        # 1. Apply redaction annotations from manually drawn "redact" regions
        for r in self.regions:
            if r.kind == "redact" and 0 <= r.page < len(output_doc):
                # Ensure page index is valid before adding annotation
                output_doc[r.page].add_redact_annot(r.bbox, fill=(0, 0, 0))  # Black fill for redaction

        # 2. Process and apply text redactions based on patterns and exclusions
        for page_num, page in enumerate(output_doc):
            # Collect "protect" region bboxes for the current page
            protect_bboxes = [r.bbox for r in self.regions if r.page == page_num and r.kind == "protect"]

            for pattern in all_patterns:
                if not pattern: continue  # Skip empty patterns

                # Search for all occurrences of the pattern on the current page
                for area in page.search_for(pattern):
                    # Check if this text area falls within a "protect" region
                    if any(fitz.Rect(bbox).contains(area) for bbox in protect_bboxes):
                        continue  # Skip redaction if text is within a protected region

                    # Check if this text (within context) matches any explicit exclusion terms
                    # Use a slightly expanded area to get more context for the exclusion check
                    context_rect = area.irect
                    context_rect.x0 = max(0, context_rect.x0 - 5)
                    context_rect.y0 = max(0, context_rect.y0 - 5)
                    context_rect.x1 = min(page.rect.width, context_rect.x1 + 5)
                    context_rect.y1 = min(page.rect.height, context_rect.y1 + 5)

                    context_text = page.get_textbox(context_rect)

                    if not any(excl.lower() in context_text.lower() for excl in self.exclusions):
                        # If not protected by a region and not explicitly excluded by text, add redaction annotation
                        page.add_redact_annot(area, fill=(0, 0, 0))

        # 3. Apply all pending redaction annotations to each page
        for page in output_doc:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)  # This performs the actual blacking out

        # Save the final redacted document
        output_doc.save(output_file, garbage=4, deflate=True, clean=True)  # Optimize PDF size
        output_doc.close()
        self.status_bar.config(text=f"Redacted PDF saved to {Path(output_file).name}")


def main():
    """Main entry point for the application."""
    root = tk.Tk()
    app = PDFRedactorGUI(root)
    root.mainloop()  # Start the Tkinter event loop


if __name__ == "__main__":
    main()