#!/usr/bin/env python3
"""Unified PDF redactor GUI + CLI.

This single-file version bundles the helper classes and command
line interface from the various versions into one executable
script. All configuration files are stored in a folder sharing the
script name.
"""

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
import time
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageTk, ImageDraw
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# ---------------------------------------------------------------------------
# JSONStore helper
# ---------------------------------------------------------------------------
class JSONStore:
    """Filesystem helper for timestamped JSON, atomic writes, and prefs."""

    APP_STEM = Path(__file__).stem
    DATA_DIR = Path(__file__).with_suffix('')
    TIMESTAMP_FMT = "%Y-%m-%d-%H%M"
    _TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{4})")
    PREFS_FILE = DATA_DIR / f"{APP_STEM}_prefs.json"

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write_atomic(path: Path, obj):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, 'w') as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)

    @staticmethod
    def get_timestamped_filename(stem: str, purpose: str) -> Path:
        ts = datetime.now().strftime(JSONStore.TIMESTAMP_FMT)
        return JSONStore.DATA_DIR / f"{stem}_{purpose}_{ts}.json"

    @staticmethod
    def find_latest_file(stem: str, purpose: str) -> Path | None:
        autosave = JSONStore.DATA_DIR / f"{stem}_{purpose}_autosave.json"
        if autosave.exists():
            return autosave
        files = list(JSONStore.DATA_DIR.glob(f"{stem}_{purpose}_*.json"))
        if not files:
            return None
        def _ts(p: Path):
            m = JSONStore._TS_RE.search(p.stem)
            if m:
                try:
                    return datetime.strptime(m.group(1), JSONStore.TIMESTAMP_FMT)
                except ValueError:
                    pass
            return datetime.fromtimestamp(p.stat().st_mtime)
        return max(files, key=_ts)


# ---------------------------------------------------------------------------
# RegionStore - manage per PDF regions with undo/redo and autosave
# ---------------------------------------------------------------------------
@dataclass
class RegionStore:
    pdf_stem: str
    regions: dict[str, list] = field(default_factory=dict)
    protect: dict[str, list] = field(default_factory=dict)
    history: list = field(default_factory=list)
    future: list = field(default_factory=list)
    last_autosave: float = 0.0

    MAX_HISTORY: int = 50

    def _snapshot(self):
        state = {
            'regions': json.loads(json.dumps(self.regions)),
            'protect': json.loads(json.dumps(self.protect)),
        }
        self.history.append(state)
        if len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)
        self.future.clear()

    def add(self, page: int, bbox: list[float], kind: str = 'redact'):
        self._snapshot()
        if kind == 'protect':
            self.protect.setdefault(str(page), []).append(bbox)
        else:
            self.regions.setdefault(str(page), []).append(bbox)
        self.autosave()

    def remove(self, page: int, index: int, kind: str = 'redact') -> bool:
        """Remove a region by page and index."""
        self._snapshot()
        key = str(page)
        items = self.protect if kind == 'protect' else self.regions
        arr = items.get(key, [])
        if 0 <= index < len(arr):
            arr.pop(index)
            self.autosave(force=True)
            return True
        return False

    def undo(self):
        if not self.history:
            return False
        self.future.append({'regions': self.regions, 'protect': self.protect})
        state = self.history.pop()
        self.regions = state['regions']
        self.protect = state['protect']
        return True

    def redo(self):
        if not self.future:
            return False
        self.history.append({'regions': self.regions, 'protect': self.protect})
        state = self.future.pop()
        self.regions = state['regions']
        self.protect = state['protect']
        return True

    def autosave(self, force: bool = False):
        """Write regions to an autosave file if more than five seconds have
        passed since the last save or when ``force`` is ``True``."""
        now = time.time()
        if force or now - self.last_autosave > 5:
            path = JSONStore.DATA_DIR / f"{self.pdf_stem}_regions_autosave.json"
            JSONStore.write_atomic(path, {'regions': self.regions, 'protect': self.protect})
            self.last_autosave = now

    # load/save snapshot to timestamped files
    def save(self):
        fname = JSONStore.get_timestamped_filename(self.pdf_stem, 'regions')
        JSONStore.write_atomic(fname, {'regions': self.regions, 'protect': self.protect})

    @classmethod
    def load(cls, pdf_stem: str):
        path = JSONStore.find_latest_file(pdf_stem, 'regions')
        obj = cls(pdf_stem)
        if path and path.exists():
            data = json.loads(path.read_text())
            obj.regions = data.get('regions', {})
            obj.protect = data.get('protect', {})
        return obj


# ---------------------------------------------------------------------------
# PDFCanvas - display a fitz.Page with zoom/pan and draw overlays
# ---------------------------------------------------------------------------
class PDFCanvas(tk.Canvas):
    def __init__(self, master):
        super().__init__(master, bg="grey")
        self.hbar = tk.Scrollbar(master, orient='horizontal', command=self.xview)
        self.vbar = tk.Scrollbar(master, orient='vertical', command=self.yview)
        self.config(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.hbar.grid(row=1, column=0, sticky='ew')
        self.vbar.grid(row=0, column=1, sticky='ns')
        self.grid(row=0, column=0, sticky='nsew')
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        self.page = None
        self.img = None
        self.scale = 2.0

    def display(self, page: fitz.Page, regions: list[list], protect: list[list], scale: float = 2.0,
                patterns: dict | None = None, exclusions: list | None = None, preview: bool = False):
        self.scale = scale
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img, 'RGBA')
        for x1, y1, x2, y2 in regions:
            draw.rectangle([x1*scale, y1*scale, x2*scale, y2*scale], fill=(255,0,0,80), outline='red', width=2)
        for x1, y1, x2, y2 in protect:
            draw.rectangle([x1*scale, y1*scale, x2*scale, y2*scale], fill=(0,255,0,80), outline='green', width=2)
        if preview:
            for x1, y1, x2, y2 in regions:
                draw.rectangle([x1*scale, y1*scale, x2*scale, y2*scale], fill='black')
            if patterns:
                patt_list = patterns.get('keywords', []) + patterns.get('passages', [])
                for pat in patt_list:
                    if exclusions and any(excl.lower() in pat.lower() for excl in exclusions):
                        continue
                    for area in page.search_for(pat, quads=False):
                        draw.rectangle([area.x0*scale, area.y0*scale, area.x1*scale, area.y1*scale], fill='black')
        self.img = ImageTk.PhotoImage(img)
        self.delete('all')
        self.create_image(0, 0, image=self.img, anchor='nw')
        self.config(scrollregion=self.bbox('all'))

    # panning helpers
    def start_pan(self, event):
        self.scan_mark(event.x, event.y)

    def drag_pan(self, event):
        self.scan_dragto(event.x, event.y, gain=1)


# ---------------------------------------------------------------------------
# PDFRedactorGUI - main application window
# ---------------------------------------------------------------------------
class PDFRedactorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(JSONStore.APP_STEM)
        self.root.geometry('1200x800')
        self.doc = None
        self.current_page = 0
        self.region_store = None

        # drawing mode state ("redact" or "protect")
        self.current_tool = 'redact'

        self.patterns = {'keywords': [], 'passages': []}
        self.exclusions = []
        self.load_app_configs()
        self.load_prefs()

        self.setup_ui()
        self.root.bind('<Control-z>', self.undo)
        self.root.bind('<Control-y>', self.redo)
        self.root.bind('<Left>', self.prev_page)
        self.root.bind('<Right>', self.next_page)

    # --------------------- config handling --------------------
    def load_app_configs(self):
        pat = JSONStore.find_latest_file('app_wide', 'patterns')
        exc = JSONStore.find_latest_file('app_wide', 'exclusions')
        if pat and pat.exists():
            self.patterns = json.loads(pat.read_text())
        if exc and exc.exists():
            self.exclusions = json.loads(exc.read_text())

    def save_app_configs(self):
        fn1 = JSONStore.get_timestamped_filename('app_wide', 'patterns')
        JSONStore.write_atomic(fn1, self.patterns)
        fn2 = JSONStore.get_timestamped_filename('app_wide', 'exclusions')
        JSONStore.write_atomic(fn2, self.exclusions)
        messagebox.showinfo('Saved', 'Configs saved to data folder.', parent=self.root)

    def load_prefs(self):
        if JSONStore.PREFS_FILE.exists():
            try:
                data = json.loads(JSONStore.PREFS_FILE.read_text())
                geom = data.get('window_geometry')
                if geom:
                    self.root.geometry(geom)
                self.last_pdf = data.get('last_pdf')
            except Exception:
                pass

    def save_prefs(self):
        data = {
            'window_geometry': self.root.geometry(),
            'last_pdf': getattr(self, 'last_pdf', '')
        }
        JSONStore.write_atomic(JSONStore.PREFS_FILE, data)

    # ---------------------- UI setup ---------------------------
    def setup_ui(self):
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(toolbar, text='Open PDF', command=self.open_pdf).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text='Save Regions', command=self.save_regions).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text='Save Redacted', command=self.save_redacted).pack(side=tk.LEFT, padx=5)
        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Button(toolbar, text='< Prev', command=self.prev_page).pack(side=tk.LEFT)
        ttk.Button(toolbar, text='Next >', command=self.next_page).pack(side=tk.LEFT)
        self.page_label = ttk.Label(toolbar, text='')
        self.page_label.pack(side=tk.LEFT, padx=10)
        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Button(toolbar, text='Undo', command=self.undo).pack(side=tk.LEFT)
        ttk.Button(toolbar, text='Redo', command=self.redo).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)
        self.preview_var = tk.BooleanVar()
        ttk.Checkbutton(toolbar, text='Preview', variable=self.preview_var, command=self.display_page).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)
        ttk.Button(toolbar, text='Help', command=self.show_help).pack(side=tk.RIGHT, padx=5)
        # drawing mode toggle
        self.mode_var = tk.StringVar(value=self.current_tool)
        for mode in ('redact', 'protect'):
            ttk.Radiobutton(toolbar, text=mode.capitalize(), variable=self.mode_var,
                            value=mode, command=self.on_mode_change).pack(side=tk.LEFT)

        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1)

        # canvas area
        canvas_frame = ttk.Frame(main)
        canvas_frame.grid(row=0, column=0, sticky='nsew')
        self.canvas = PDFCanvas(canvas_frame)
        self.canvas.bind('<ButtonPress-1>', self.start_draw)
        self.canvas.bind('<B1-Motion>', self.update_draw)
        self.canvas.bind('<ButtonRelease-1>', self.end_draw)
        self.canvas.bind('<ButtonPress-2>', self.canvas.start_pan)
        self.canvas.bind('<B2-Motion>', self.canvas.drag_pan)

        # side notebook
        notebook = ttk.Notebook(main)
        notebook.grid(row=0, column=1, sticky='nsew')
        tab_pats = ttk.Frame(notebook)
        tab_exc = ttk.Frame(notebook)
        notebook.add(tab_pats, text='Patterns')
        notebook.add(tab_exc, text='Exclusions')
        self.create_patterns_tab(tab_pats)
        self.create_exclusions_tab(tab_exc)

    def create_patterns_tab(self, parent):
        ttk.Label(parent, text='Keywords:').pack(anchor='w')
        self.keywords_lb = tk.Listbox(parent, height=5)
        self.keywords_lb.pack(fill=tk.BOTH, expand=True, padx=5)
        for kw in self.patterns.get('keywords', []):
            self.keywords_lb.insert(tk.END, kw)
        ent = ttk.Entry(parent)
        ent.pack(fill=tk.X, padx=5, pady=5)
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text='Add', command=lambda: self._add_listbox_item(ent, self.keywords_lb)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text='Delete', command=lambda: self._del_listbox_item(self.keywords_lb)).pack(side=tk.LEFT, padx=2)

        ttk.Label(parent, text='Passages:').pack(anchor='w', pady=(10,0))
        self.passages_txt = scrolledtext.ScrolledText(parent, height=8)
        self.passages_txt.pack(fill=tk.BOTH, expand=True, padx=5)
        self.passages_txt.insert(tk.END, '\n---\n'.join(self.patterns.get('passages', [])))
        ttk.Button(parent, text='Save', command=self.save_patterns).pack(pady=5)

    def create_exclusions_tab(self, parent):
        ttk.Label(parent, text='Exclusion strings:').pack(anchor='w')
        self.excl_lb = tk.Listbox(parent)
        self.excl_lb.pack(fill=tk.BOTH, expand=True, padx=5)
        for ex in self.exclusions:
            self.excl_lb.insert(tk.END, ex)
        ent = ttk.Entry(parent)
        ent.pack(fill=tk.X, padx=5, pady=5)
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text='Add', command=lambda: self._add_listbox_item(ent, self.excl_lb)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text='Delete', command=lambda: self._del_listbox_item(self.excl_lb)).pack(side=tk.LEFT, padx=2)
        ttk.Button(parent, text='Save', command=self.save_exclusions).pack(pady=5)

    def _add_listbox_item(self, entry: ttk.Entry, listbox: tk.Listbox):
        text = entry.get().strip()
        if text:
            listbox.insert(tk.END, text)
            entry.delete(0, tk.END)

    def _del_listbox_item(self, listbox: tk.Listbox):
        sel = list(listbox.curselection())
        for i in reversed(sel):
            listbox.delete(i)

    def on_mode_change(self):
        self.current_tool = self.mode_var.get()

    # --------------------- Navigation & Undo -------------------
    def prev_page(self, *args):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()

    def next_page(self, *args):
        if self.doc and self.current_page < len(self.doc)-1:
            self.current_page += 1
            self.display_page()

    def undo(self, *args):
        if self.region_store and self.region_store.undo():
            self.display_page()

    def redo(self, *args):
        if self.region_store and self.region_store.redo():
            self.display_page()

    def save_regions(self):
        if self.region_store:
            self.region_store.save()
            messagebox.showinfo('Saved', 'Regions saved', parent=self.root)

    def show_help(self):
        msg = ('Open a PDF then draw rectangles to redact or protect.\n'
               'Use Prev/Next to change pages. Middle mouse pans.\n'
               'Toggle Preview to see blacked out areas. Save Regions to store JSON files.')
        messagebox.showinfo('Help', msg, parent=self.root)

    # --------------------- PDF Handling ------------------------
    def open_pdf(self, path=None):
        filename = path or filedialog.askopenfilename(filetypes=[('PDF files','*.pdf')])
        if not filename:
            return
        self.doc = fitz.open(filename)
        self.current_page = 0
        stem = Path(filename).stem
        self.region_store = RegionStore.load(stem)
        self.page_label.config(text=f"1 / {len(self.doc)}")
        self.last_pdf = filename
        self.display_page()

    def display_page(self):
        if not self.doc:
            return
        p = self.doc[self.current_page]
        regs = self.region_store.regions.get(str(self.current_page), []) if self.region_store else []
        prot = self.region_store.protect.get(str(self.current_page), []) if self.region_store else []
        self.canvas.display(p, regs, prot, patterns=self.patterns, exclusions=self.exclusions, preview=self.preview_var.get())
        self.page_label.config(text=f"{self.current_page+1} / {len(self.doc)}")

    # drawing
    def start_draw(self, event):
        self.start_x = self.canvas.canvasx(event.x)/self.canvas.scale
        self.start_y = self.canvas.canvasy(event.y)/self.canvas.scale
        color = 'red' if self.current_tool == 'redact' else 'green'
        self.temp_rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline=color)

    def update_draw(self, event):
        if hasattr(self, 'temp_rect'):
            self.canvas.coords(self.temp_rect,
                                self.start_x*self.canvas.scale,
                                self.start_y*self.canvas.scale,
                                self.canvas.canvasx(event.x),
                                self.canvas.canvasy(event.y))

    def end_draw(self, event):
        if hasattr(self, 'temp_rect'):
            x2 = self.canvas.canvasx(event.x)/self.canvas.scale
            y2 = self.canvas.canvasy(event.y)/self.canvas.scale
            rect = [min(self.start_x,x2), min(self.start_y,y2), max(self.start_x,x2), max(self.start_y,y2)]
            if self.region_store:
                self.region_store.add(self.current_page, rect, kind=self.current_tool)
            self.canvas.delete(self.temp_rect)
            del self.temp_rect
            self.display_page()

    # ------------------------- Save ----------------------------
    def save_patterns(self):
        kws = list(self.keywords_lb.get(0, tk.END))
        passages = [p.strip() for p in self.passages_txt.get(1.0, tk.END).split('\n---\n') if p.strip()]
        self.patterns = {'keywords': kws, 'passages': passages}
        self.save_app_configs()

    def save_exclusions(self):
        self.exclusions = list(self.excl_lb.get(0, tk.END))
        self.save_app_configs()

    def save_redacted(self):
        if not self.doc:
            return
        self.region_store.save()
        output = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF','*.pdf')])
        if not output:
            return
        apply_redactions(self.doc.name, output, self.region_store.regions, self.patterns, self.exclusions)
        messagebox.showinfo('Done', f'Saved to {output}', parent=self.root)


# ---------------------------------------------------------------------------
# CLI helpers for configs
# ---------------------------------------------------------------------------
def load_patterns(path: str | None = None) -> dict:
    if path:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
        return {'keywords': [], 'passages': []}
    pat = JSONStore.find_latest_file('app_wide', 'patterns')
    if pat and pat.exists():
        return json.loads(pat.read_text())
    return {'keywords': [], 'passages': []}


def save_patterns(data: dict, path: str | None = None):
    if path:
        JSONStore.write_atomic(Path(path), data)
    else:
        fn = JSONStore.get_timestamped_filename('app_wide', 'patterns')
        JSONStore.write_atomic(fn, data)


def load_exclusions(path: str | None = None) -> list:
    if path:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
        return []
    exc = JSONStore.find_latest_file('app_wide', 'exclusions')
    if exc and exc.exists():
        return json.loads(exc.read_text())
    return []


def save_exclusions(data: list, path: str | None = None):
    if path:
        JSONStore.write_atomic(Path(path), data)
    else:
        fn = JSONStore.get_timestamped_filename('app_wide', 'exclusions')
        JSONStore.write_atomic(fn, data)


def load_region_store(pdf: str) -> RegionStore:
    stem = Path(pdf).stem
    return RegionStore.load(stem)


def print_json(data):
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Core redaction logic (headless)
# ---------------------------------------------------------------------------
def apply_redactions(input_pdf: str, output_pdf: str, regions: dict[str,list], patterns: dict, exclusions: list):
    doc = fitz.open(input_pdf)

    # region redactions
    for page_num, regs in regions.items():
        page = doc[int(page_num)]
        for x1,y1,x2,y2 in regs:
            page.add_redact_annot(fitz.Rect(x1,y1,x2,y2), fill=(0,0,0))

    # text patterns
    all_patterns = patterns.get('keywords', []).copy()
    all_patterns += patterns.get('passages', [])

    for page in doc:
        for pattern in all_patterns:
            if any(excl.lower() in pattern.lower() for excl in exclusions):
                continue
            for area in page.search_for(pattern, quads=False):
                page.add_redact_annot(area, fill=(0,0,0))

    for page in doc:
        page.apply_redactions()
    doc.save(output_pdf, garbage=4)
    doc.close()


# ---------------------------------------------------------------------------
# CLI interface / entrypoint
# ---------------------------------------------------------------------------
def run_gui():
    root = tk.Tk()
    app = PDFRedactorGUI(root)
    root.protocol('WM_DELETE_WINDOW', lambda: (app.save_prefs(), root.destroy()))
    if getattr(app, 'last_pdf', None) and Path(app.last_pdf).exists():
        app.open_pdf(app.last_pdf)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Unified PDF redactor')
    parser.add_argument('--gui', action='store_true', help='Launch GUI')
    parser.add_argument('input', nargs='?', help='Input PDF for CLI apply mode')
    parser.add_argument('output', nargs='?', help='Output PDF for CLI apply mode')
    parser.add_argument('--patterns', help='Path to JSON patterns file')
    parser.add_argument('--exclusions', help='Path to JSON exclusions file')
    parser.add_argument('--regions', help='Path to JSON region file')
    parser.add_argument('--apply', action='store_true', help='Apply redactions (default when input and output provided)')
    parser.add_argument('--list-patterns', action='store_true', help='List saved patterns')
    parser.add_argument('--add-pattern', nargs=2, metavar=('TYPE','TEXT'), help='Add a keyword or passage pattern')
    parser.add_argument('--remove-pattern', nargs=2, metavar=('TYPE','TEXT'), help='Remove a keyword or passage pattern')
    parser.add_argument('--list-exclusions', action='store_true', help='List saved exclusions')
    parser.add_argument('--add-exclusion', metavar='TEXT', help='Add an exclusion string')
    parser.add_argument('--remove-exclusion', metavar='TEXT', help='Remove an exclusion string')
    parser.add_argument('--list-regions', nargs='?', const='ALL', metavar='PAGE', help='List regions for PDF (use --input to specify pdf)')
    parser.add_argument('--add-region', nargs=5, metavar=('PAGE','X1','Y1','X2','Y2'), help='Add region box to PDF')
    parser.add_argument('--remove-region', nargs=2, metavar=('PAGE','INDEX'), help='Remove region by page and index')
    parser.add_argument('--undo-region', action='store_true', help='Undo last region edit')
    parser.add_argument('--redo-region', action='store_true', help='Redo last undone region edit')
    parser.add_argument('--region-type', choices=['redact','protect'], default='redact', help='Type for --add-region/remove-region')
    args = parser.parse_args()

    ops = [args.list_patterns, args.add_pattern, args.remove_pattern,
           args.list_exclusions, args.add_exclusion, args.remove_exclusion,
           args.list_regions != None, args.add_region, args.remove_region,
           args.undo_region, args.redo_region]

    if args.input and not args.output and not any(ops) and not args.apply:
        parser.error('output PDF required in CLI mode')

    if args.gui or (not args.input and not any(ops) and not args.apply):
        run_gui()
        return

    # pattern operations
    if args.list_patterns:
        pats = load_patterns(args.patterns)
        print_json(pats)
        return
    if args.add_pattern:
        kind, text = args.add_pattern
        if kind not in ('keyword','passage'):
            parser.error('pattern type must be keyword or passage')
        pats = load_patterns(args.patterns)
        key = 'keywords' if kind == 'keyword' else 'passages'
        if text in pats.get(key, []):
            parser.error('pattern already exists')
        pats.setdefault(key, []).append(text)
        save_patterns(pats, args.patterns)
        print('Pattern added')
        return
    if args.remove_pattern:
        kind, text = args.remove_pattern
        if kind not in ('keyword','passage'):
            parser.error('pattern type must be keyword or passage')
        pats = load_patterns(args.patterns)
        key = 'keywords' if kind == 'keyword' else 'passages'
        try:
            pats[key].remove(text)
        except (KeyError, ValueError):
            parser.error('pattern not found')
        save_patterns(pats, args.patterns)
        print('Pattern removed')
        return

    # exclusion operations
    if args.list_exclusions:
        exc = load_exclusions(args.exclusions)
        print_json(exc)
        return
    if args.add_exclusion:
        exc = load_exclusions(args.exclusions)
        if args.add_exclusion in exc:
            parser.error('exclusion already exists')
        exc.append(args.add_exclusion)
        save_exclusions(exc, args.exclusions)
        print('Exclusion added')
        return
    if args.remove_exclusion:
        exc = load_exclusions(args.exclusions)
        try:
            exc.remove(args.remove_exclusion)
        except ValueError:
            parser.error('exclusion not found')
        save_exclusions(exc, args.exclusions)
        print('Exclusion removed')
        return

    # region operations require input PDF
    if args.list_regions is not None or args.add_region or args.remove_region or args.undo_region or args.redo_region:
        if not args.input:
            parser.error('input PDF required for region operations')
        store = load_region_store(args.input)
        if args.list_regions is not None:
            page = args.list_regions
            if page == 'ALL':
                print_json({'regions': store.regions, 'protect': store.protect})
            else:
                page_regions = store.regions.get(str(page), [])
                page_prot = store.protect.get(str(page), [])
                print_json({'regions': page_regions, 'protect': page_prot})
            return
        if args.add_region:
            page,x1,y1,x2,y2 = args.add_region
            store.add(int(page), [float(x1),float(y1),float(x2),float(y2)], kind=args.region_type)
            store.save()
            print('Region added')
            return
        if args.remove_region:
            page, idx = args.remove_region
            ok = store.remove(int(page), int(idx), kind=args.region_type)
            if not ok:
                parser.error('no region at that index')
            store.save()
            print('Region removed')
            return
        if args.undo_region:
            if not store.undo():
                parser.error('nothing to undo')
            store.save()
            print('Undo done')
            return
        if args.redo_region:
            if not store.redo():
                parser.error('nothing to redo')
            store.save()
            print('Redo done')
            return

    # apply redactions
    if args.apply or (args.input and args.output):
        input_pdf = args.input if args.input else args.apply[0] if isinstance(args.apply, list) else None
        output_pdf = args.output if args.output else args.apply[1] if isinstance(args.apply, list) else None
        if not input_pdf or not output_pdf:
            parser.error('input and output required for apply')
        patterns = load_patterns(args.patterns)
        exclusions = load_exclusions(args.exclusions)
        if args.regions:
            region_file = Path(args.regions)
            if region_file.exists():
                data = json.loads(region_file.read_text())
                regions = data.get('regions', {})
            else:
                regions = {}
        else:
            store = load_region_store(input_pdf)
            regions = store.regions
        apply_redactions(input_pdf, output_pdf, regions, patterns, exclusions)
        print(f'Saved to {output_pdf}')
        return

    parser.print_help()


if __name__ == '__main__':
    main()
