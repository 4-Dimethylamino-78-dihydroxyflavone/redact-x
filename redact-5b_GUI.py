#!/usr/bin/env python3
"""
redact_gui.py - PDF Redaction GUI

A unified, robust PDF redaction tool with:
- Pan, Text-select, Draw Redact/Exclude/Protect, Edit Region tools
- Undo/Redo history
- Autosave & manual save
- Configurable text patterns and exclusions
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import fitz  # PyMuPDF
from PIL import Image, ImageTk, ImageDraw
from enum import Enum, auto
from dataclasses import dataclass, asdict
import copy
import json
from pathlib import Path
from datetime import datetime

# --- Section 1: Tool Enumeration ---
class Tool(Enum):
    PAN = auto()
    TEXT_SELECT = auto()
    DRAW_REDACT = auto()
    DRAW_EXCLUDE = auto()
    DRAW_PROTECT = auto()
    EDIT_REGION = auto()

# --- Section 2: Data Models & History Manager ---
@dataclass
class Region:
    page: int
    bbox: tuple[float, float, float, float]
    kind: str  # 'redact', 'exclude', or 'protect'
    canvas_id: int | None = None

class HistoryManager:
    def __init__(self, depth=50):
        self.stack: list = []
        self.redo_stack: list = []
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

# --- Section 3: JSON Store & Autosave Helper ---
class JSONStore:
    APP_NAME = Path(__file__).stem
    DATA_DIR = Path(__file__).with_suffix('')
    TIMESTAMP_FMT = "%Y-%m-%d-%H%M"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write_atomic(path: Path, obj):
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(json.dumps(obj, indent=2))
        tmp.replace(path)

    @staticmethod
    def get_timestamped_filename(stem: str, purpose: str) -> Path:
        ts = datetime.now().strftime(JSONStore.TIMESTAMP_FMT)
        return JSONStore.DATA_DIR / f"{stem}_{purpose}_{ts}.json"

# --- Section 4: Main GUI Application ---
class PDFRedactorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF Redactor")

        # State variables
        self.current_tool: Tool = Tool.PAN
        self.history = HistoryManager()
        self.doc = None        # fitz.Document
        self.current_page = 0
        self.scale_factor = 1.0
        self.regions: list[Region] = []
        self.patterns = {"keywords": [], "passages": []}
        self.exclusions: list[str] = []

        # Temporary drawing state
        self.drag_info = {}
        self.temp_rect_id = None

        # UI setup
        self.setup_ui()
        self.bind_events()

        # Load prefs
        self.prefs = {}
        self.load_prefs()

        # Open last PDF if any
        last_pdf = self.prefs.get('last_pdf')
        if last_pdf and Path(last_pdf).exists():
            self.open_pdf(path=last_pdf)

    def setup_ui(self):
        # Menubar
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open PDF...", command=self.open_pdf)
        file_menu.add_command(label="Save Redacted PDF...", command=self.save_redacted_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        # Toolbar
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(toolbar, text="Open", command=self.open_pdf).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Save", command=self.save_redacted_pdf).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Tool buttons
        self.tool_var = tk.StringVar(value=self.current_tool.name)
        for text, tool in [("Pan", Tool.PAN), ("Text", Tool.TEXT_SELECT),
                           ("Redact", Tool.DRAW_REDACT), ("Exclude", Tool.DRAW_EXCLUDE),
                           ("Protect", Tool.DRAW_PROTECT)]:
            rb = ttk.Radiobutton(toolbar, text=text, variable=self.tool_var,
                                 value=tool.name, command=self.on_tool_change)
            rb.pack(side=tk.LEFT)

        ttk.Checkbutton(toolbar, text="Preview", command=self.display_page).pack(side=tk.LEFT, padx=5)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)
        ttk.Button(toolbar, text="Undo", command=self.undo_action).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Redo", command=self.redo_action).pack(side=tk.LEFT)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Page navigation
        ttk.Button(toolbar, text="< Prev", command=self.prev_page).pack(side=tk.LEFT)
        self.page_label = ttk.Label(toolbar, text="Page 0/0")
        self.page_label.pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Next >", command=self.next_page).pack(side=tk.LEFT)

        # Main PanedWindow
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # Canvas frame
        canvas_frame = ttk.Frame(main_pane)
        self.canvas = tk.Canvas(canvas_frame, bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        main_pane.add(canvas_frame, weight=3)

        # Side Notebook
        notebook = ttk.Notebook(main_pane)
        self.create_patterns_tab(notebook)
        self.create_exclusions_tab(notebook)
        main_pane.add(notebook, weight=1)

        # Status bar
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor='w')
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def bind_events(self):
        # Keyboard shortcuts
        self.root.bind('<Control-o>', lambda e: self.open_pdf())
        self.root.bind('<Control-s>', lambda e: self.save_redacted_pdf())
        self.root.bind('<Control-z>', lambda e: self.undo_action())
        self.root.bind('<Control-y>', lambda e: self.redo_action())

        # Canvas events
        self.canvas.bind('<ButtonPress-1>', self.on_canvas_press)
        self.canvas.bind('<B1-Motion>', self.on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_canvas_release)
        self.canvas.bind('<Double-Button-1>', self.on_canvas_double)

    # --- Tool Management ---
    def on_tool_change(self):
        self.current_tool = Tool[self.tool_var.get()]
        self.status_bar.config(text=f"Tool: {self.current_tool.name}")

    # --- Page Navigation ---
    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()

    def next_page(self):
        if self.doc and self.current_page < len(self.doc)-1:
            self.current_page += 1
            self.display_page()

    # --- PDF Loading & Display ---
    def open_pdf(self, path=None):
        filename = path or filedialog.askopenfilename(filetypes=[("PDF files","*.pdf")])
        if not filename:
            return
        try:
            self.doc = fitz.open(filename)
            self.current_page = 0
            self.pdf_path = filename
            self.prefs['last_pdf'] = filename
            self.display_page()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def display_page(self):
        if not self.doc:
            return
        page = self.doc[self.current_page]
        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Preview text redactions
        if hasattr(self, 'preview') and self.preview.get():
            draw = ImageDraw.Draw(img)
            for pat in self.patterns['keywords'] + self.patterns['passages']:
                for area in page.search_for(pat):
                    draw.rectangle(list(area * mat), fill="black")

        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(0,0, anchor='nw', image=self.photo)
        self.page_label.config(text=f"Page {self.current_page+1}/{len(self.doc)}")
        self.display_regions()

    # --- Region Drawing & Editing ---
    def on_canvas_press(self, event):
        if not self.doc: return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.drag_info = {'x0': x, 'y0': y}
        self.temp_rect_id = self.canvas.create_rectangle(x,y,x,y, outline='red', dash=(2,2))

    def on_canvas_drag(self, event):
        if not self.temp_rect_id: return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.coords(self.temp_rect_id, self.drag_info['x0'], self.drag_info['y0'], x, y)

    def on_canvas_release(self, event):
        if not self.temp_rect_id: return
        x1,y1 = self.drag_info['x0'], self.drag_info['y0']
        x2,y2 = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if abs(x2-x1)>5 and abs(y2-y1)>5:
            mat = fitz.Matrix(1/self.scale_factor, 1/self.scale_factor)
            rect = fitz.Rect(x1,y1,x2,y2) * mat
            kind = self.current_tool.name.split('_')[1].lower()
            self.history.push(self.regions.copy())
            self.regions.append(Region(self.current_page, (rect.x0,rect.y0,rect.x1,rect.y1), kind))
        self.canvas.delete(self.temp_rect_id)
        self.temp_rect_id = None
        self.display_regions()

    def on_canvas_double(self, event):
        # Could implement region edit on double-click
        pass

    def display_regions(self):
        if not self.doc: return
        mat = fitz.Matrix(self.scale_factor, self.scale_factor)
        for r in self.regions:
            if r.page == self.current_page:
                x0,y0,x1,y1 = r.bbox
                x0,y0,x1,y1 = mat.transform_rect(fitz.Rect(r.bbox))
                self.canvas.create_rectangle(x0,y0,x1,y1, outline='blue')

    # --- Undo/Redo ---
    def undo_action(self):
        self.regions = self.history.undo(self.regions)
        self.display_regions()

    def redo_action(self):
        self.regions = self.history.redo(self.regions)
        self.display_regions()

    # --- Save Redacted PDF ---
    def save_redacted_pdf(self):
        if not self.doc: return
        out = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF','*.pdf')])
        if not out: return
        try:
            doc = fitz.open(self.pdf_path)
            # apply regions
            for r in self.regions:
                doc[r.page].add_redact_annot(r.bbox, fill=(0,0,0))
            for page in doc:
                page.apply_redactions()
            doc.save(out, garbage=4, deflate=True)
            messagebox.showinfo("Saved","Redacted PDF saved")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # --- Preferences ---
    def load_prefs(self):
        try:
            data = json.loads((JSONStore.DATA_DIR/ 'prefs.json').read_text())
            self.prefs = data
            geom = data.get('window_geometry')
            if geom:
                self.root.geometry(geom)
        except:
            pass

    def save_prefs(self):
        self.prefs['window_geometry'] = self.root.geometry()
        (JSONStore.DATA_DIR/ 'prefs.json').write_text(json.dumps(self.prefs))

    # --- Patterns/Exclusions Tabs ---
    def create_patterns_tab(self, notebook):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text='Patterns')
        ttk.Label(frame, text='Keywords:').pack(anchor='w')
        self.keywords_list = tk.Listbox(frame, height=5)
        self.keywords_list.pack(fill='x')
        ttk.Label(frame, text='Passages:').pack(anchor='w')
        self.passages_text = scrolledtext.ScrolledText(frame, height=5)
        self.passages_text.pack(fill='both', expand=True)
        ttk.Button(frame, text='Save', command=self.update_passages_from_edit).pack()

    def create_exclusions_tab(self, notebook):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text='Exclusions')
        ttk.Label(frame, text='Exclusions:').pack(anchor='w')
        self.excl_list = tk.Listbox(frame, height=10)
        self.excl_list.pack(fill='both', expand=True)
        ttk.Button(frame, text='Save', command=self.update_exclusions_from_edit).pack()

    def update_passages_from_edit(self):
        text = self.passages_text.get('1.0','end').strip()
        self.patterns['passages'] = [p.strip() for p in text.split('---') if p.strip()]

    def update_exclusions_from_edit(self):
        self.exclusions = list(self.excl_list.get(0,'end'))


def main():
    root = tk.Tk()
    app = PDFRedactorGUI(root)
    root.protocol('WM_DELETE_WINDOW', lambda: (app.save_prefs(), root.destroy()))
    root.mainloop()

if __name__ == '__main__':
    main()
