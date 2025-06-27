#!/usr/bin/env python3
"""
redact-5_GUI.py - Visual PDF Redaction System with a unified tool model, autosave, and undo/redo.

A complete GUI for managing PDF redactions, refactored for robustness and usability.
- **Unified Tool Model**: Pan, Text Select, Draw Redact/Exclude/Protect, and Edit modes.
- **Surgical-Strike Roadmap Features**:
  - Single source of truth for the active tool (Enum-based).
  - Dirty-flag with a 3-second autosave cache to a single file.
  - Unified undo/redo stack for all state changes (regions, patterns, etc.).
  - Listbox UX fixes: Delete key support and in-place editing.
  - Refined rectangle drawing and a dedicated "flameshot-lite" edit mode.
  - Preview renders directly from in-memory state, ensuring it's always up-to-date.
  - Text selection tool is now a primary tool, color-coded.
- Visual region selection, modification, and resizing.
- Dynamic text pattern management.
- Versioned configs on manual save.
- Remembers last opened PDF and zoom level.

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
class Region:
    page: int
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    kind: str  # "redact" | "exclude" | "protect"
    canvas_id: int | None = None  # id of the outer rectangle


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
    APP_NAME = Path(__file__).stem
    DATA_DIR = Path(__file__).with_suffix('')
    TIMESTAMP_FMT = "%Y-%m-%d-%H%M"
    _TS_RE = re.compile(r'(\d{4}-\d{2}-\d{2}-\d{4})')

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PREFS_FILE = DATA_DIR / f"{APP_NAME}_prefs.json"

    @staticmethod
    def write_atomic(path: Path, obj):
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        try:
            tmp_path.write_text(json.dumps(obj, indent=2))
            tmp_path.replace(path)
        except Exception as e:
            print(f"Error during atomic write: {e}")
            if tmp_path.exists():
                tmp_path.unlink()

    @staticmethod
    def get_timestamped_filename(stem: str, purpose: str) -> str:
        ts = datetime.now().strftime(JSONStore.TIMESTAMP_FMT)
        return str(JSONStore.DATA_DIR / f"{stem}_{purpose}_{ts}.json")

    @staticmethod
    def find_latest_file(stem: str, purpose: str) -> str | None:
        files = list(JSONStore.DATA_DIR.glob(f"{stem}_{purpose}_*.json"))
        if not files:
            autosave_file = JSONStore.DATA_DIR / f"{stem}_{purpose}_autosave.json"
            if autosave_file.exists():
                return str(autosave_file)
            return None

        def _extract_ts(p: Path) -> datetime:
            m = JSONStore._TS_RE.search(p.stem)
            if m:
                try:
                    return datetime.strptime(m.group(1), JSONStore.TIMESTAMP_FMT)
                except ValueError:
                    pass
            return datetime.fromtimestamp(p.stat().st_mtime)

        latest = max(files, key=_extract_ts, default=None)
        return str(latest) if latest else None


class PDFRedactorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(Path(__file__).name)

        # --- State Variables ---
        self.current_pdf = None
        self.pdf_stem = ""
        self.current_page = 0
        self.doc = None
        self.scale_factor = 1.0

        # --- Refactored State Management ---
        self.current_tool: Tool = Tool.PAN
        self.history = HistoryManager()
        self.dirty = False

        # In-memory state (the "source of truth")
        self.patterns = {"keywords": [], "passages": []}
        self.exclusions = []
        self.regions: list[Region] = []

        # Region drawing/editing state
        self.drag_info = {}
        self.edit_region: Region | None = None
        self.temp_rect_id = None

        # --- Load Prefs and Configs ---
        self.prefs = self.load_prefs()
        self.root.geometry(self.prefs.get("window_geometry", "1200x800"))
        self.load_app_configs()

        # --- Setup UI and Bindings ---
        self.setup_ui()
        self.bind_shortcuts()
        self.set_tool(Tool.PAN)  # Set initial tool and cursor

        # --- Open last PDF if available ---
        last_pdf = self.prefs.get("last_pdf")
        if last_pdf and os.path.exists(last_pdf):
            self.open_pdf(path=last_pdf)
            self.scale_factor = self.prefs.get("last_zoom", 1.0)
            self.display_page()

    # --- Section 1 & 8: Tool Management & GUI Indicator ---
    def set_tool(self, tool: Tool):
        if self.edit_region:  # Finalize any ongoing region edit
            self._exit_edit_mode()

        self.current_tool = tool

        tool_colors = {
            "PAN": ("grey", "Pan/Move"), "TEXT_SELECT": ("#f2e55c", "Select Text"),
            "DRAW_REDACT": ("#ff7878", "Draw Redact"), "DRAW_EXCLUDE": ("#78a0ff", "Draw Exclude"),
            "DRAW_PROTECT": ("#78ff8f", "Draw Protect"), "EDIT_REGION": ("#b0b0b0", "Edit Region"),
        }
        color, text = tool_colors.get(tool.name, ("white", "Unknown"))

        self.status_lbl.config(bg=color, text=text)

        cursor_map = {
            "PAN": "hand2", "TEXT_SELECT": "ibeam", "DRAW_REDACT": "tcross",
            "DRAW_EXCLUDE": "dot", "DRAW_PROTECT": "diamond_cross", "EDIT_REGION": "fleur",
        }
        self.canvas.config(cursor=cursor_map.get(tool.name, "arrow"))

    # --- Section 2 & 3: Dirty Flag, Autosave, and History ---
    def _collect_state(self) -> dict:
        return {
            "patterns": self.patterns,
            "exclusions": self.exclusions,
            "regions": [asdict(r) for r in self.regions]
        }

    def _apply_state(self, state: dict):
        self.patterns = state.get("patterns", {"keywords": [], "passages": []})
        self.exclusions = state.get("exclusions", [])
        self.regions = [Region(**r) for r in state.get("regions", [])]

        # Refresh UI elements reflecting the new state
        self._update_patterns_ui()
        self._update_exclusions_ui()
        self.display_page()

    def _mark_dirty(self, record_undo: bool = True):
        if record_undo:
            # Push state *before* the change that will be made
            self.history.push(self._collect_state())

        if not self.dirty:
            self.dirty = True
            self.root.after(3000, self._flush_cache_if_dirty)

    def _autosave_path(self) -> Path | None:
        if not self.pdf_stem: return None
        return JSONStore.DATA_DIR / f"{self.pdf_stem}_full_autosave.json"

    def _flush_cache_if_dirty(self):
        if self.dirty and self.pdf_stem:
            path = self._autosave_path()
            if path:
                JSONStore.write_atomic(path, self._collect_state())
            self.dirty = False  # Reset flag for the next cycle
            self.status_bar.config(text=f"Autosaved at {datetime.now().strftime('%H:%M:%S')}")

    # --- Config and Preference Management ---
    def load_prefs(self):
        if JSONStore.PREFS_FILE.exists():
            try:
                return json.loads(JSONStore.PREFS_FILE.read_text())
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save_prefs(self):
        self.prefs['window_geometry'] = self.root.geometry()
        if self.current_pdf:
            self.prefs['last_pdf'] = self.current_pdf
            self.prefs['last_zoom'] = self.scale_factor
        try:
            JSONStore.write_atomic(JSONStore.PREFS_FILE, self.prefs)
        except IOError:
            print(f"Warning: Could not save preferences to {JSONStore.PREFS_FILE}")

    def on_closing(self):
        self._flush_cache_if_dirty()  # Final save before closing
        self.save_prefs()
        self.root.destroy()

    def load_app_configs(self):
        """Loads general patterns and exclusions, not document-specific regions."""
        latest_patterns = JSONStore.find_latest_file("app_wide", 'patterns')
        self.patterns = json.load(open(latest_patterns)) if latest_patterns else {"keywords": [], "passages": []}
        latest_exclusions = JSONStore.find_latest_file("app_wide", 'exclusions')
        self.exclusions = json.load(open(latest_exclusions)) if latest_exclusions else []

    def save_app_configs(self, patterns=True, exclusions=True):
        """Saves general patterns and exclusions to timestamped files."""
        if patterns:
            fname_patterns = JSONStore.get_timestamped_filename("app_wide", 'patterns')
            with open(fname_patterns, 'w') as f: json.dump(self.patterns, f, indent=2)
        if exclusions:
            fname_exclusions = JSONStore.get_timestamped_filename("app_wide", 'exclusions')
            with open(fname_exclusions, 'w') as f: json.dump(self.exclusions, f, indent=2)
        messagebox.showinfo("Success", "Configuration saved as new timestamped file.", parent=self.root)

    # --- Keyboard and Mouse Bindings ---
    def bind_shortcuts(self):
        self.root.bind('<Left>', lambda e: self.prev_page())
        self.root.bind('<Right>', lambda e: self.next_page())
        self.root.bind('<Prior>', lambda e: self.prev_page())
        self.root.bind('<Next>', lambda e: self.next_page())
        self.root.bind('<Control-s>', lambda e: self.save_redacted_pdf())
        self.root.bind('<Control-o>', lambda e: self.open_pdf())
        self.root.bind('<Control-p>', lambda e: self.toggle_preview())
        self.root.bind('<Control-z>', self.undo_action)
        self.root.bind('<Control-y>', self.redo_action)
        self.root.bind('<Control-Shift-Z>', self.redo_action)
        self.root.bind('<Delete>', self.delete_selected_item)
        self.root.bind('<BackSpace>', self.delete_selected_item)
        self.root.bind('<Escape>', lambda e: self.set_tool(Tool.PAN))
        self.root.bind('<space>', lambda e: self.set_tool(Tool.PAN))
        self.root.bind('<r>', lambda e: self.set_tool(Tool.DRAW_REDACT))
        self.root.bind('<e>', lambda e: self.set_tool(Tool.DRAW_EXCLUDE))
        self.root.bind('<p>', lambda e: self.set_tool(Tool.DRAW_PROTECT))
        self.root.bind('<t>', lambda e: self.set_tool(Tool.TEXT_SELECT))
        self.root.bind('<Return>', self._handle_return_key)

        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self.on_shift_wheel)
        self.canvas.bind("<Control-MouseWheel>", self.on_ctrl_wheel)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _handle_return_key(self, event=None):
        """ Exit edit mode on Return key press """
        if self.current_tool == Tool.EDIT_REGION:
            self.set_tool(Tool.PAN)

    # --- UI Setup ---
    def setup_ui(self):
        # ... Menubar setup (remains mostly the same) ...
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

        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        ttk.Button(toolbar, text="Open PDF", command=self.open_pdf).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="< Prev", command=self.prev_page).pack(side=tk.LEFT, padx=2)
        self.page_label = ttk.Label(toolbar, text="No PDF loaded", width=20, anchor='center')
        self.page_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Next >", command=self.next_page).pack(side=tk.LEFT, padx=2)

        self.preview_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Preview (Ctrl+P)", variable=self.preview_var, command=self.display_page).pack(
            side=tk.LEFT, padx=5)

        self.status_lbl = tk.Label(toolbar, width=12, relief="sunken", anchor='center')
        self.status_lbl.pack(side=tk.LEFT, padx=10, ipady=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="Apply & Save PDF", command=self.save_redacted_pdf).pack(side=tk.LEFT, padx=5)

        main_frame = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        canvas_container = ttk.Frame(main_frame)
        main_frame.add(canvas_container, weight=3)
        self.canvas = tk.Canvas(canvas_container, bg="gray")
        v_scrollbar = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)

        right_panel = ttk.Notebook(main_frame)
        main_frame.add(right_panel, weight=1)
        self.create_patterns_tab(right_panel)
        self.create_exclusions_tab(right_panel)

        self.status_bar = ttk.Label(self.root, text="Ready. Use Ctrl+O to open a PDF.", relief=tk.SUNKEN, anchor='w')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, ipady=2)

    def create_patterns_tab(self, parent_notebook):
        parent = ttk.Frame(parent_notebook)
        parent_notebook.add(parent, text="Text Patterns")
        # Keywords Listbox
        ttk.Label(parent, text="Keywords to Redact:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)
        keywords_frame = ttk.Frame(parent)
        keywords_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.keywords_listbox = tk.Listbox(keywords_frame, height=10)
        self.keywords_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        keywords_scrollbar = ttk.Scrollbar(keywords_frame, command=self.keywords_listbox.yview)
        keywords_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.keywords_listbox.config(yscrollcommand=keywords_scrollbar.set)
        # Passages Text
        ttk.Label(parent, text="Passages to Redact (separate with ---):", font=("", 10, "bold")).pack(anchor=tk.W,
                                                                                                      padx=5,
                                                                                                      pady=(10, 5))
        self.passages_text = scrolledtext.ScrolledText(parent, height=10, width=40)
        self.passages_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._setup_listbox_editing(self.keywords_listbox, self.update_pattern_from_edit)
        self.passages_text.bind("<FocusOut>", self.update_passages_from_edit)
        self._update_patterns_ui()

    def create_exclusions_tab(self, parent_notebook):
        parent = ttk.Frame(parent_notebook)
        parent_notebook.add(parent, text="Exclusions")
        ttk.Label(parent, text="Text to Preserve:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)
        exclusions_frame = ttk.Frame(parent)
        exclusions_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.exclusions_listbox = tk.Listbox(exclusions_frame)
        self.exclusions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        exclusions_scrollbar = ttk.Scrollbar(exclusions_frame, command=self.exclusions_listbox.yview)
        exclusions_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.exclusions_listbox.config(yscrollcommand=exclusions_scrollbar.set)

        self._setup_listbox_editing(self.exclusions_listbox, self.update_exclusion_from_edit)
        self._update_exclusions_ui()

    def _update_patterns_ui(self):
        self.keywords_listbox.delete(0, tk.END)
        for keyword in self.patterns.get("keywords", []):
            self.keywords_listbox.insert(tk.END, keyword)
        self.passages_text.delete(1.0, tk.END)
        self.passages_text.insert(tk.END, "\n---\n".join(self.patterns.get("passages", [])))

    def _update_exclusions_ui(self):
        self.exclusions_listbox.delete(0, tk.END)
        for exclusion in self.exclusions:
            self.exclusions_listbox.insert(tk.END, exclusion)

    # --- Section 4: List-box UX fixes ---
    def _setup_listbox_editing(self, lb, commit_callback):
        lb.bind("<Double-Button-1>", lambda e, l=lb, cb=commit_callback: self._start_listbox_edit(e, l, cb))

    def _start_listbox_edit(self, event, lb, commit_callback):
        selection = lb.curselection()
        if not selection: return

        idx = selection[0]
        text = lb.get(idx)
        x, y, w, h = lb.bbox(idx)

        entry = ttk.Entry(lb)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, text)
        entry.select_range(0, 'end')
        entry.focus_set()

        def commit_edit(e):
            new_text = entry.get().strip()
            entry.destroy()
            if new_text and new_text != text:
                commit_callback(idx, new_text)

        def cancel_edit(e):
            entry.destroy()

        entry.bind("<Return>", commit_edit)
        entry.bind("<FocusOut>", cancel_edit)
        entry.bind("<Escape>", cancel_edit)

    def update_pattern_from_edit(self, index, new_text):
        self._mark_dirty()
        self.patterns['keywords'][index] = new_text
        self._update_patterns_ui()

    def update_exclusion_from_edit(self, index, new_text):
        self._mark_dirty()
        self.exclusions[index] = new_text
        self._update_exclusions_ui()

    def update_passages_from_edit(self, event=None):
        passages_text = self.passages_text.get(1.0, tk.END).strip()
        new_passages = [p.strip() for p in passages_text.split('---') if p.strip()]
        if new_passages != self.patterns.get("passages", []):
            self._mark_dirty()
            self.patterns["passages"] = new_passages

    def delete_selected_item(self, event=None):
        widget = self.root.focus_get()
        if widget == self.keywords_listbox:
            self._delete_from_list(self.keywords_listbox, self.patterns['keywords'])
        elif widget == self.exclusions_listbox:
            self._delete_from_list(self.exclusions_listbox, self.exclusions)
        elif widget == self.canvas and self.edit_region:
            self._delete_region(self.edit_region)
            self.set_tool(Tool.PAN)
        return "break"

    def _delete_from_list(self, listbox, data_list):
        selection = listbox.curselection()
        if not selection: return
        self._mark_dirty()
        # Iterate backwards to avoid index shifting issues
        for index in sorted(selection, reverse=True):
            del data_list[index]
        self._update_patterns_ui()  # Refresh both lists
        self._update_exclusions_ui()

    # --- Event Handlers for Zoom, Pan, etc. ---
    def toggle_preview(self):
        self.preview_var.set(not self.preview_var.get())
        self.display_page()

    def on_mouse_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 or event.num == 4 else 1, "units")

    def on_shift_wheel(self, event):
        self.canvas.xview_scroll(-1 if event.delta > 0 or event.num == 4 else 1, "units")

    def on_ctrl_wheel(self, event):
        zoom_factor = 1.1 if event.delta > 0 or event.num == 4 else 1 / 1.1
        self.scale_factor = max(0.2, min(self.scale_factor * zoom_factor, 10.0))
        self.display_page()

    # --- PDF and Page Management ---
    def open_pdf(self, path=None):
        filename = path or filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not filename or not os.path.exists(filename):
            if path: self.status_bar.config(text=f"Could not find last PDF: {path}")
            return

        try:
            self.doc = fitz.open(filename)
            self.current_pdf = filename
            self.pdf_stem = Path(self.current_pdf).stem
            self.current_page = 0
            if not path: self.scale_factor = 1.0

            # Load document-specific state (regions, etc.)
            state_file = self._autosave_path()
            if not state_file or not state_file.exists():
                state_file = JSONStore.find_latest_file(self.pdf_stem, 'full')

            if state_file:
                loaded_state = json.loads(Path(state_file).read_text())
                # Only load regions, not app-wide patterns/exclusions
                self.regions = [Region(**r) for r in loaded_state.get("regions", [])]
            else:
                self.regions = []  # No state file found, start fresh

            self.history.clear()
            self.dirty = False
            self.display_page()
            self.save_prefs()
            self.status_bar.config(text=f"Opened: {os.path.basename(self.current_pdf)}")
        except Exception as e:
            messagebox.showerror("Error Opening PDF", f"Could not open or process the file:\n{e}")
            self.doc = None

    def display_page(self):
        if not self.doc:
            self.canvas.delete("all")
            self.page_label.config(text="No PDF loaded")
            return

        self.canvas.delete("all")
        page = self.doc[self.current_page]
        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # --- Section 6: Preview must include memory state ---
        if self.preview_var.get():
            draw = ImageDraw.Draw(img)
            # Preview text redactions
            all_patterns = self.patterns.get("keywords", []) + self.patterns.get("passages", [])
            for pattern in all_patterns:
                if not pattern: continue
                for area in page.search_for(pattern, quads=False):
                    if not any(
                            excl.lower() in page.get_text("text", clip=area.irect).lower() for excl in self.exclusions):
                        draw.rectangle((area * mat).irect, fill="black")
            # Preview region redactions
            for r in self.regions:
                if r.page == self.current_page and r.kind == "redact":
                    draw.rectangle(list(fitz.Rect(r.bbox) * mat), fill="black")

        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo, tags="bg")
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

        # Draw interactive regions if not in preview
        if not self.preview_var.get():
            self._draw_all_regions()

        self.page_label.config(text=f"Page {self.current_page + 1} / {len(self.doc)}")

    def _draw_all_regions(self):
        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        region_colors = {"redact": ("#ff7878", "#cc0000"), "exclude": ("#78a0ff", "#0033cc"),
                         "protect": ("#78ff8f", "#009933")}
        for r in self.regions:
            r.canvas_id = None  # Clear old ID
            if r.page == self.current_page:
                fill, outline = region_colors.get(r.kind, ("grey", "black"))
                bbox_scaled = list(fitz.Rect(r.bbox) * mat)
                r.canvas_id = self.canvas.create_rectangle(*bbox_scaled, fill=fill, outline=outline, width=2,
                                                           stipple="gray50", tags="region")

        if self.edit_region:
            self._draw_edit_handles()

    def _draw_edit_handles(self):
        self.canvas.delete("handle")
        if not self.edit_region or self.edit_region.canvas_id is None: return

        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        r = fitz.Rect(self.edit_region.bbox) * mat
        s = 5  # handle size

        # Make the main rectangle solid
        self.canvas.itemconfig(self.edit_region.canvas_id, stipple="")

        # Corner and edge handles
        coords = {
            "nw": (r.x0, r.y0), "n": (r.center.x, r.y0), "ne": (r.x1, r.y0),
            "w": (r.x0, r.center.y), "e": (r.x1, r.center.y),
            "sw": (r.x0, r.y1), "s": (r.center.x, r.y1), "se": (r.x1, r.y1),
        }
        for tag, (x, y) in coords.items():
            self.canvas.create_rectangle(x - s, y - s, x + s, y + s, fill="white", outline="black",
                                         tags=("handle", tag))

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()

    def next_page(self):
        if self.doc and self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self.display_page()

    # --- Undo/Redo System ---
    def undo_action(self, event=None):
        new_state = self.history.undo(self._collect_state())
        self._apply_state(new_state)

    def redo_action(self, event=None):
        new_state = self.history.redo(self._collect_state())
        self._apply_state(new_state)

    # --- Section 5 & 7: Region/Text Drawing and Modification ---
    def on_canvas_press(self, event):
        if self.preview_var.get(): return
        self.drag_info.clear()

        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        if self.current_tool == Tool.PAN:
            self.canvas.scan_mark(event.x, event.y)
            return
        elif self.current_tool == Tool.EDIT_REGION and self.edit_region:
            handle_tags = self.canvas.gettags(self.canvas.find_closest(canvas_x, canvas_y)[0])
            handle_type = next((t for t in handle_tags if t in "n s e w nw ne sw se".split()), None)

            if handle_type:  # Clicked a handle
                self.drag_info = {"type": "resize", "handle": handle_type, "region": self.edit_region}
            elif self.edit_region.canvas_id and self.canvas.find_closest(canvas_x, canvas_y)[
                0] == self.edit_region.canvas_id:
                self.drag_info = {"type": "move", "region": self.edit_region,
                                  "start_x": canvas_x / self.scale_factor, "start_y": canvas_y / self.scale_factor}
            else:  # Clicked outside, exit edit mode
                self.set_tool(Tool.PAN)
            return

        # Start drawing a new region or text selection
        self.drag_info = {"start_x": canvas_x, "start_y": canvas_y, "tool": self.current_tool}
        outline_color = {"TEXT_SELECT": "yellow", "DRAW_REDACT": "red", "DRAW_EXCLUDE": "blue",
                         "DRAW_PROTECT": "green"}.get(self.current_tool.name)
        self.temp_rect_id = self.canvas.create_rectangle(canvas_x, canvas_y, canvas_x, canvas_y, outline=outline_color,
                                                         dash=(3, 5))

    def on_canvas_drag(self, event):
        if not self.drag_info or self.preview_var.get(): return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        if self.current_tool == Tool.PAN:
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        elif self.current_tool == Tool.EDIT_REGION and self.edit_region:
            self._resize_or_move_region(canvas_x, canvas_y)
        elif self.temp_rect_id:
            self.canvas.coords(self.temp_rect_id, self.drag_info["start_x"], self.drag_info["start_y"], canvas_x,
                               canvas_y)

    def on_canvas_release(self, event):
        if not self.drag_info or self.preview_var.get() or self.current_tool == Tool.PAN: return

        if self.current_tool == Tool.EDIT_REGION:
            if "region" in self.drag_info:
                self._mark_dirty()
            self.drag_info.clear()
            return

        if self.temp_rect_id: self.canvas.delete(self.temp_rect_id); self.temp_rect_id = None

        x0, y0 = self.drag_info["start_x"], self.drag_info["start_y"]
        x1, y1 = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        if abs(x1 - x0) < 5 or abs(y1 - y0) < 5: return  # Ignore tiny drags

        if self.current_tool == Tool.TEXT_SELECT:
            is_exclusion = (event.state & 0x0001) != 0  # Shift key
            self._process_text_selection(x0, y0, x1, y1, is_exclusion)
        elif self.current_tool in [Tool.DRAW_REDACT, Tool.DRAW_EXCLUDE, Tool.DRAW_PROTECT]:
            pdf_x0 = min(x0, x1) / self.scale_factor
            pdf_y0 = min(y0, y1) / self.scale_factor
            pdf_x1 = max(x0, x1) / self.scale_factor
            pdf_y1 = max(y0, y1) / self.scale_factor

            kind = self.current_tool.name.split('_')[1].lower()
            new_region = Region(page=self.current_page, bbox=(pdf_x0, pdf_y0, pdf_x1, pdf_y1), kind=kind)

            self._mark_dirty()
            self.regions.append(new_region)
            self.display_page()

        self.drag_info.clear()

    def on_canvas_double_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        clicked_id = self.canvas.find_closest(canvas_x, canvas_y)[0]

        for r in self.regions:
            if r.page == self.current_page and r.canvas_id == clicked_id:
                self.edit_region = r
                self.set_tool(Tool.EDIT_REGION)
                self.display_page()  # Redraw to show handles
                break

    def _exit_edit_mode(self):
        self.edit_region = None
        self.display_page()  # Redraw to remove handles
        self.drag_info.clear()

    def _resize_or_move_region(self, canvas_x, canvas_y):
        if not self.edit_region: return

        mat = fitz.Matrix(1 / self.scale_factor, 1 / self.scale_factor)
        r = list(self.edit_region.bbox)

        if self.drag_info.get("type") == "resize":
            handle = self.drag_info["handle"]
            px, py = canvas_x * mat.a, canvas_y * mat.d
            if "n" in handle: r[1] = py
            if "s" in handle: r[3] = py
            if "w" in handle: r[0] = px
            if "e" in handle: r[2] = px
            # Normalize rect
            self.edit_region.bbox = tuple(fitz.Rect(r).normalize())
        elif self.drag_info.get("type") == "move":
            dx = (canvas_x / self.scale_factor) - self.drag_info["start_x"]
            dy = (canvas_y / self.scale_factor) - self.drag_info["start_y"]
            r[0] += dx;
            r[2] += dx
            r[1] += dy;
            r[3] += dy
            self.edit_region.bbox = tuple(r)
            self.drag_info["start_x"] += dx
            self.drag_info["start_y"] += dy

        self.display_page()  # Live update

    def _delete_region(self, region_to_delete: Region):
        self._mark_dirty()
        self.regions.remove(region_to_delete)
        self.display_page()

    def _process_text_selection(self, x0, y0, x1, y1, is_for_exclusion):
        if not self.doc: return
        page = self.doc[self.current_page]
        rect_pdf = fitz.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y1, y0)) * fitz.Matrix(1 / self.scale_factor,
                                                                                               1 / self.scale_factor)

        selected_text = page.get_textbox(rect_pdf).strip()
        if not selected_text:
            self.status_bar.config(text="No text found in selection.")
            return

        selected_text = re.sub(r'\s+', ' ', selected_text)
        self._mark_dirty()
        if is_for_exclusion:
            if selected_text not in self.exclusions:
                self.exclusions.append(selected_text)
                self._update_exclusions_ui()
                self.status_bar.config(text=f"Added to exclusions: '{selected_text[:40]}...'")
        else:  # Add to passages for redaction
            current_passages = self.patterns.get("passages", [])
            if selected_text not in current_passages:
                current_passages.append(selected_text)
                self.patterns["passages"] = current_passages
                self._update_patterns_ui()
                self.status_bar.config(text=f"Added to redaction passages: '{selected_text[:40]}...'")

    # --- Save, Apply Redactions ---
    def save_redacted_pdf(self):
        if not self.doc:
            messagebox.showerror("Error", "No PDF loaded")
            return

        self._flush_cache_if_dirty()  # Ensure latest changes are saved to cache before this manual save

        # Save the full state to a timestamped file
        state_fname = JSONStore.get_timestamped_filename(self.pdf_stem, 'full')
        JSONStore.write_atomic(Path(state_fname), self._collect_state())

        output_file = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")],
            initialfile=f"{self.pdf_stem}_redacted.pdf", title="Save Redacted PDF As"
        )
        if not output_file: return

        try:
            self.apply_all_redactions(output_file)
            messagebox.showinfo("Success", f"Redacted PDF saved to:\n{output_file}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save redacted PDF:\n{e}")
            import traceback
            traceback.print_exc()

    def apply_all_redactions(self, output_file):
        output_doc = fitz.open(self.current_pdf)

        # Apply region redactions
        for r in self.regions:
            if r.kind == "redact" and 0 <= r.page < len(output_doc):
                output_doc[r.page].add_redact_annot(r.bbox, fill=(0, 0, 0))

        # Apply text redactions
        all_patterns = self.patterns.get("keywords", []) + self.patterns.get("passages", [])
        for page_num, page in enumerate(output_doc):
            regions_on_page = [r.bbox for r in self.regions if r.page == page_num]
            exclude_bboxes = [r for r in regions_on_page if self.regions[regions_on_page.index(r)].kind == "exclude"]
            protect_bboxes = [r for r in regions_on_page if self.regions[regions_on_page.index(r)].kind == "protect"]

            for pattern in all_patterns:
                if not pattern: continue
                for area in page.search_for(pattern, quads=False):
                    if any(fitz.Rect(bbox).contains(area) for bbox in protect_bboxes): continue
                    if any(fitz.Rect(bbox).contains(area) for bbox in exclude_bboxes): continue
                    if not any(excl.lower() in page.get_textbox(area.irect).lower() for excl in self.exclusions):
                        page.add_redact_annot(area, fill=(0, 0, 0))

        for page in output_doc:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        output_doc.save(output_file, garbage=4, deflate=True, clean=True)
        output_doc.close()
        self.status_bar.config(text=f"Saved to {output_file}")


def main():
    root = tk.Tk()
    app = PDFRedactorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()