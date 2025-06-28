#!/usr/bin/env python3
"""Enhanced PDF redactor GUI + CLI with OCR support, presets, and improved zoom.

This enhanced version includes:
- Fixed Ctrl+MouseWheel zoom functionality
- OCR support for scanned PDFs
- Preset workflows for common redaction tasks
- Improved error handling and robustness
- Better packaging support for standalone executables
- Extended unit test coverage
"""

import argparse
import json
import os
import re
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from dataclasses import dataclass, field
from datetime import datetime
import time
from pathlib import Path
from enum import Enum, auto
from typing import Optional, Dict, List, Tuple, Any
import threading
import queue

import fitz  # PyMuPDF
from PIL import Image, ImageTk, ImageDraw

# Optional OCR support
try:
    import pytesseract
    import cv2
    import numpy as np

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("OCR support not available. Install pytesseract and opencv-python for OCR features.")


# Tool modes enumeration
class ToolMode(Enum):
    PAN = auto()
    TEXT_SELECT = auto()
    DRAW_REDACT = auto()
    DRAW_PROTECT = auto()


# Preset definitions for common redaction workflows
REDACTION_PRESETS = {
    "Personal Information": {
        "name": "Personal Information",
        "description": "Redact names, addresses, phone numbers, emails, and SSNs",
        "patterns": {
            "keywords": [],
            "passages": []
        },
        "regex_patterns": [
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone numbers
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
            r"\b\d{5}(?:-\d{4})?\b",  # ZIP codes
        ]
    },
    "Financial Data": {
        "name": "Financial Data",
        "description": "Redact account numbers, credit card info, and financial details",
        "patterns": {
            "keywords": ["account", "balance", "credit card", "bank"],
            "passages": []
        },
        "regex_patterns": [
            r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # Credit card
            r"\$[\d,]+\.?\d*",  # Dollar amounts
            r"\b\d{8,17}\b",  # Account numbers
        ]
    },
    "Medical Records": {
        "name": "Medical Records",
        "description": "Redact patient names, medical record numbers, and diagnoses",
        "patterns": {
            "keywords": ["patient", "diagnosis", "treatment", "medication"],
            "passages": []
        },
        "regex_patterns": [
            r"MRN[\s:]*\d+",  # Medical record numbers
            r"DOB[\s:]*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",  # Date of birth
        ]
    },
    "Legal Documents": {
        "name": "Legal Documents",
        "description": "Redact case numbers, client names, and sensitive legal info",
        "patterns": {
            "keywords": ["confidential", "attorney-client", "privileged"],
            "passages": []
        },
        "regex_patterns": [
            r"Case\s*No\.?\s*:?\s*\d+",  # Case numbers
            r"\b(?:Plaintiff|Defendant|Witness)\s*:?\s*[A-Z][a-z]+\s+[A-Z][a-z]+",
        ]
    }
}


# ---------------------------------------------------------------------------
# OCR Helper Functions
# ---------------------------------------------------------------------------
class OCRProcessor:
    """Handle OCR processing for scanned PDFs."""

    def __init__(self):
        self.ocr_available = OCR_AVAILABLE

    def preprocess_image(self, img: Image.Image) -> Image.Image:
        """Preprocess image for better OCR results."""
        if not self.ocr_available:
            return img

        # Convert PIL to OpenCV format
        open_cv_image = np.array(img)

        # Convert to grayscale
        gray = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2GRAY)

        # Apply thresholding to get better OCR results
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Denoise
        denoised = cv2.fastNlMeansDenoising(thresh)

        # Convert back to PIL
        return Image.fromarray(denoised)

    def extract_text_with_positions(self, page: fitz.Page) -> List[Tuple[str, fitz.Rect]]:
        """Extract text with positions using OCR."""
        if not self.ocr_available:
            return []

        # Get page as image
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x scale for better OCR
        img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)

        # Preprocess
        img = self.preprocess_image(img)

        # Get OCR data with positions
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        results = []
        n_boxes = len(data['text'])

        for i in range(n_boxes):
            if data['text'][i].strip():
                # Scale coordinates back to original
                x = data['left'][i] / 2
                y = data['top'][i] / 2
                w = data['width'][i] / 2
                h = data['height'][i] / 2

                rect = fitz.Rect(x, y, x + w, y + h)
                results.append((data['text'][i], rect))

        return results

    def is_scanned_pdf(self, doc: fitz.Document) -> bool:
        """Check if PDF appears to be scanned (image-based)."""
        if len(doc) == 0:
            return False

        # Check first few pages
        pages_to_check = min(3, len(doc))

        for i in range(pages_to_check):
            page = doc[i]
            # If page has very little text but has images, likely scanned
            text = page.get_text().strip()
            images = page.get_images()

            if len(text) < 50 and len(images) > 0:
                return True

        return False


# ---------------------------------------------------------------------------
# JSONStore helper (enhanced with preset support)
# ---------------------------------------------------------------------------
class JSONStore:
    """Filesystem helper for timestamped JSON, atomic writes, prefs, and presets."""

    APP_STEM = Path(__file__).stem
    DATA_DIR = Path(__file__).with_suffix('')
    TIMESTAMP_FMT = "%Y-%m-%d-%H%M"
    _TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{4})")
    PREFS_FILE = DATA_DIR / f"{APP_STEM}_prefs.json"
    PRESETS_FILE = DATA_DIR / f"{APP_STEM}_presets.json"

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

    @staticmethod
    def find_all_json_files() -> list[Path]:
        """Find all JSON files in the current directory and data directory."""
        json_files = []
        # Check script directory
        script_dir = Path(__file__).parent
        json_files.extend(script_dir.glob("*.json"))
        # Check data directory
        if JSONStore.DATA_DIR.exists():
            json_files.extend(JSONStore.DATA_DIR.glob("*.json"))
        return json_files

    @staticmethod
    def load_presets() -> Dict[str, Any]:
        """Load saved presets or return defaults."""
        if JSONStore.PRESETS_FILE.exists():
            try:
                user_presets = json.loads(JSONStore.PRESETS_FILE.read_text())
                # Merge with defaults
                all_presets = REDACTION_PRESETS.copy()
                all_presets.update(user_presets)
                return all_presets
            except:
                pass
        return REDACTION_PRESETS.copy()

    @staticmethod
    def save_presets(presets: Dict[str, Any]):
        """Save user presets."""
        # Only save user-defined presets
        user_presets = {k: v for k, v in presets.items()
                        if k not in REDACTION_PRESETS}
        if user_presets:
            JSONStore.write_atomic(JSONStore.PRESETS_FILE, user_presets)


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

    def update(self, page: int, index: int, bbox: list[float], kind: str = 'redact') -> bool:
        """Update an existing region's coordinates."""
        self._snapshot()
        key = str(page)
        items = self.protect if kind == 'protect' else self.regions
        arr = items.get(key, [])
        if 0 <= index < len(arr):
            arr[index] = bbox
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
        self.tool_mode = ToolMode.PAN

        # Text selection state
        self.selection_start = None
        self.selection_rect = None

        # OCR support
        self.ocr_processor = OCRProcessor()
        self.ocr_results = []

    def display(self, page: fitz.Page, regions: list[list], protect: list[list], scale: float = 2.0,
                patterns: dict | None = None, exclusions: list | None = None,
                excluded_passages: list | None = None, preview: bool = False,
                use_ocr: bool = False, regex_patterns: list | None = None):
        self.scale = scale
        self.page = page
        self.ocr_results = []

        # Run OCR if requested
        if use_ocr and self.ocr_processor.ocr_available:
            self.ocr_results = self.ocr_processor.extract_text_with_positions(page)

        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img, 'RGBA')

        # Draw regions
        for x1, y1, x2, y2 in regions:
            draw.rectangle([x1 * scale, y1 * scale, x2 * scale, y2 * scale], fill=(255, 0, 0, 80), outline='red',
                           width=2)
        for x1, y1, x2, y2 in protect:
            draw.rectangle([x1 * scale, y1 * scale, x2 * scale, y2 * scale], fill=(0, 255, 0, 80), outline='green',
                           width=2)

        if preview:
            # Apply region redactions in preview
            for x1, y1, x2, y2 in regions:
                draw.rectangle([x1 * scale, y1 * scale, x2 * scale, y2 * scale], fill='black')

            # Apply text pattern redactions in preview
            if patterns:
                patt_list = patterns.get('keywords', []) + patterns.get('passages', [])
                all_exclusions = (exclusions or []) + (excluded_passages or [])

                # Search in regular text
                for pat in patt_list:
                    # Skip if pattern matches any exclusion
                    if any(excl.lower() in pat.lower() for excl in all_exclusions):
                        continue

                    for area in page.search_for(pat, quads=False):
                        if self._should_redact_area(area, protect, all_exclusions, page):
                            draw.rectangle([area.x0 * scale, area.y0 * scale, area.x1 * scale, area.y1 * scale],
                                           fill='black')

                # Search in OCR text if available
                if self.ocr_results:
                    for text, rect in self.ocr_results:
                        for pat in patt_list:
                            if pat.lower() in text.lower():
                                if self._should_redact_area(rect, protect, all_exclusions, page):
                                    draw.rectangle([rect.x0 * scale, rect.y0 * scale,
                                                    rect.x1 * scale, rect.y1 * scale], fill='black')

            # Apply regex pattern redactions
            if regex_patterns:
                text = page.get_text()
                for pattern in regex_patterns:
                    try:
                        for match in re.finditer(pattern, text, re.IGNORECASE):
                            # Try to find the match location on the page
                            matched_text = match.group(0)
                            for area in page.search_for(matched_text, quads=False):
                                if self._should_redact_area(area, protect, all_exclusions, page):
                                    draw.rectangle([area.x0 * scale, area.y0 * scale,
                                                    area.x1 * scale, area.y1 * scale], fill='black')
                    except re.error:
                        continue

        self.img = ImageTk.PhotoImage(img)
        self.delete('all')
        self.create_image(0, 0, image=self.img, anchor='nw')
        self.config(scrollregion=self.bbox('all'))

    def _should_redact_area(self, area: fitz.Rect, protect: list, exclusions: list, page: fitz.Page) -> bool:
        """Check if an area should be redacted based on protection and exclusions."""
        # Check if area is protected
        for px1, py1, px2, py2 in protect:
            if (area.x0 >= px1 and area.y0 >= py1 and
                    area.x1 <= px2 and area.y1 <= py2):
                return False

        # Check context for exclusions
        expanded = fitz.Rect(area)
        expanded.x0 -= 20
        expanded.x1 += 20
        try:
            context = page.get_textbox(expanded)
            if any(excl.lower() in context.lower() for excl in exclusions):
                return False
        except:
            pass

        return True

    def set_tool_mode(self, mode: ToolMode):
        self.tool_mode = mode
        # Update cursor based on mode
        if mode == ToolMode.PAN:
            self.config(cursor="hand2")
        elif mode == ToolMode.TEXT_SELECT:
            self.config(cursor="crosshair")
        else:
            self.config(cursor="tcross")

    # Panning helpers
    def start_pan(self, event):
        self.scan_mark(event.x, event.y)

    def drag_pan(self, event):
        self.scan_dragto(event.x, event.y, gain=1)

    # Text selection helpers
    def start_text_selection(self, event):
        if self.selection_rect:
            self.delete(self.selection_rect)
        self.selection_start = (self.canvasx(event.x), self.canvasy(event.y))
        self.selection_rect = self.create_rectangle(
            self.selection_start[0], self.selection_start[1],
            self.selection_start[0], self.selection_start[1],
            outline='blue', dash=(3, 3), width=2
        )

    def update_text_selection(self, event):
        if self.selection_rect and self.selection_start:
            x, y = self.canvasx(event.x), self.canvasy(event.y)
            self.coords(self.selection_rect, self.selection_start[0], self.selection_start[1], x, y)

    def end_text_selection(self, event):
        if self.selection_rect and self.selection_start and self.page:
            x, y = self.canvasx(event.x), self.canvasy(event.y)
            # Convert canvas coordinates to page coordinates
            x0 = min(self.selection_start[0], x) / self.scale
            y0 = min(self.selection_start[1], y) / self.scale
            x1 = max(self.selection_start[0], x) / self.scale
            y1 = max(self.selection_start[1], y) / self.scale

            # Get text in selection
            rect = fitz.Rect(x0, y0, x1, y1)
            text = self.page.get_textbox(rect)

            # Also check OCR results if available
            if not text.strip() and self.ocr_results:
                for ocr_text, ocr_rect in self.ocr_results:
                    if rect.intersects(ocr_rect):
                        text += " " + ocr_text

            # Clean up
            self.delete(self.selection_rect)
            self.selection_rect = None
            self.selection_start = None

            return text.strip()
        return None


# ---------------------------------------------------------------------------
# PDFRedactorGUI - main application window (enhanced)
# ---------------------------------------------------------------------------
class PDFRedactorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(JSONStore.APP_STEM)
        self.root.geometry('1200x800')
        self.doc = None
        self.current_page = 0
        self.region_store = None

        # Current tool mode
        self.current_tool = ToolMode.PAN
        self.drawing_mode = 'redact'  # 'redact' or 'protect'

        self.patterns = {'keywords': [], 'passages': []}
        self.exclusions = []
        self.excluded_passages = []  # New: separate list for excluded passages
        self.regex_patterns = []  # For preset regex patterns

        # OCR settings
        self.use_ocr = tk.BooleanVar(value=False)
        self.is_scanned = False

        # Presets
        self.presets = JSONStore.load_presets()
        self.current_preset = None

        # Remember last pane position for resizable layout
        self.last_pane_position: int | None = None

        self.load_app_configs()
        self.auto_detect_json_files()  # New: auto-detect JSON files
        self.load_prefs()

        self.setup_ui()
        if hasattr(self, 'last_zoom'):
            self.canvas.scale = self.last_zoom
        self.bind_events()
        self.start_config_monitor()

        # Apply saved window state
        if hasattr(self, 'last_pdf') and self.last_pdf and Path(self.last_pdf).exists():
            self.open_pdf(self.last_pdf)

    def bind_events(self):
        """Bind keyboard shortcuts"""
        # Use bind_all so shortcuts work regardless of focus widget
        self.root.bind_all('<Control-z>', self.undo, add='+')
        self.root.bind_all('<Control-y>', self.redo, add='+')
        self.root.bind('<Left>', self.prev_page)
        self.root.bind('<Right>', self.next_page)
        self.root.bind('<Control-o>', lambda e: self.open_pdf())
        self.root.bind('<Control-s>', lambda e: self.save_redacted())
        self.root.bind('<Control-i>', lambda e: self.import_config())
        self.root.bind('<Control-e>', lambda e: self.export_config())

        # Fixed zoom shortcuts - bind to multiple variations
        self.root.bind('<Control-plus>', lambda e: self.zoom_in())
        self.root.bind('<Control-KP_Add>', lambda e: self.zoom_in())  # Numpad +
        self.root.bind('<Control-equal>', lambda e: self.zoom_in())  # = key (shift + = gives +)

        self.root.bind('<Control-minus>', lambda e: self.zoom_out())
        self.root.bind('<Control-KP_Subtract>', lambda e: self.zoom_out())  # Numpad -
        self.root.bind('<Control-underscore>', lambda e: self.zoom_out())  # _ key

        self.root.bind('<Control-0>', lambda e: self.zoom_reset())
        self.root.bind('<Control-KP_0>', lambda e: self.zoom_reset())  # Numpad 0

        # Ctrl+MouseWheel for zooming
        self.root.bind('<Control-MouseWheel>', self.on_ctrl_mousewheel)
        self.root.bind('<Control-Button-4>', self.on_ctrl_mousewheel)  # Linux
        self.root.bind('<Control-Button-5>', self.on_ctrl_mousewheel)  # Linux

        # Tool switching shortcuts
        self.root.bind('<space>', lambda e: self.set_tool_mode(ToolMode.PAN))
        self.root.bind('t', lambda e: self.set_tool_mode(ToolMode.TEXT_SELECT))
        self.root.bind('r', lambda e: self.set_tool_mode(ToolMode.DRAW_REDACT))
        self.root.bind('p', lambda e: self.set_tool_mode(ToolMode.DRAW_PROTECT))

    def on_ctrl_mousewheel(self, event):
        """Handle Ctrl+MouseWheel for zooming"""
        if event.delta:
            # Windows/Mac
            if event.delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            # Linux
            if event.num == 4:
                self.zoom_in()
            elif event.num == 5:
                self.zoom_out()

    def auto_detect_json_files(self):
        """Auto-detect and offer to load JSON files from launch directory"""
        json_files = JSONStore.find_all_json_files()

        # Filter for likely config files
        pattern_files = [f for f in json_files if 'pattern' in f.name.lower()]
        exclusion_files = [f for f in json_files if 'exclusion' in f.name.lower()]

        # If we find likely config files, offer to load them
        if pattern_files or exclusion_files:
            msg = "Found configuration files in directory:\n\n"
            if pattern_files:
                msg += "Pattern files:\n"
                msg += "\n".join(f"  - {f.name}" for f in pattern_files[:3])
                if len(pattern_files) > 3:
                    msg += f"\n  ... and {len(pattern_files) - 3} more"
                msg += "\n\n"
            if exclusion_files:
                msg += "Exclusion files:\n"
                msg += "\n".join(f"  - {f.name}" for f in exclusion_files[:3])
                if len(exclusion_files) > 3:
                    msg += f"\n  ... and {len(exclusion_files) - 3} more"

            msg += "\n\nWould you like to load the most recent ones?"

            # Delay the dialog to ensure main window is created
            self.root.after(100, lambda: self._ask_load_configs(msg, pattern_files, exclusion_files))

    def _ask_load_configs(self, msg, pattern_files, exclusion_files):
        """Ask user if they want to load auto-detected configs"""
        if messagebox.askyesno("Configuration Files Found", msg):
            if pattern_files:
                # Load most recent pattern file
                latest_pattern = max(pattern_files, key=lambda f: f.stat().st_mtime)
                try:
                    self.patterns = json.loads(latest_pattern.read_text())
                    self.update_patterns_ui()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to load patterns: {e}")

            if exclusion_files:
                # Load most recent exclusion file
                latest_exclusion = max(exclusion_files, key=lambda f: f.stat().st_mtime)
                try:
                    data = json.loads(latest_exclusion.read_text())
                    if isinstance(data, list):
                        self.exclusions = data
                    elif isinstance(data, dict):
                        self.exclusions = data.get('keywords', [])
                        self.excluded_passages = data.get('passages', [])
                    self.update_exclusions_ui()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to load exclusions: {e}")

    def start_config_monitor(self):
        """Start polling configuration files for changes"""
        pat = JSONStore.find_latest_file('app_wide', 'patterns')
        exc = JSONStore.find_latest_file('app_wide', 'exclusions')
        self._pattern_mtime = pat.stat().st_mtime if pat and pat.exists() else 0
        self._exclusion_mtime = exc.stat().st_mtime if exc and exc.exists() else 0
        self.root.after(2000, self.check_config_files)

    def check_config_files(self):
        changed = False
        pat = JSONStore.find_latest_file('app_wide', 'patterns')
        if pat and pat.exists():
            m = pat.stat().st_mtime
            if m != getattr(self, '_pattern_mtime', None):
                try:
                    self.patterns = json.loads(pat.read_text())
                    self.update_patterns_ui()
                    changed = True
                except Exception:
                    pass
                self._pattern_mtime = m

        exc = JSONStore.find_latest_file('app_wide', 'exclusions')
        if exc and exc.exists():
            m = exc.stat().st_mtime
            if m != getattr(self, '_exclusion_mtime', None):
                try:
                    data = json.loads(exc.read_text())
                    if isinstance(data, list):
                        self.exclusions = data
                        self.excluded_passages = []
                    else:
                        self.exclusions = data.get('keywords', [])
                        self.excluded_passages = data.get('passages', [])
                    self.update_exclusions_ui()
                    changed = True
                except Exception:
                    pass
                self._exclusion_mtime = m

        if changed:
            self.schedule_preview_update()
        self.root.after(2000, self.check_config_files)

    # --------------------- config handling --------------------
    def load_app_configs(self):
        pat = JSONStore.find_latest_file('app_wide', 'patterns')
        exc = JSONStore.find_latest_file('app_wide', 'exclusions')
        if pat and pat.exists():
            self.patterns = json.loads(pat.read_text())
        if exc and exc.exists():
            data = json.loads(exc.read_text())
            if isinstance(data, list):
                self.exclusions = data
            elif isinstance(data, dict):
                self.exclusions = data.get('keywords', [])
                self.excluded_passages = data.get('passages', [])

    def save_app_configs(self):
        fn1 = JSONStore.get_timestamped_filename('app_wide', 'patterns')
        JSONStore.write_atomic(fn1, self.patterns)

        # Save exclusions with both keywords and passages
        fn2 = JSONStore.get_timestamped_filename('app_wide', 'exclusions')
        exclusion_data = {
            'keywords': self.exclusions,
            'passages': self.excluded_passages
        }
        JSONStore.write_atomic(fn2, exclusion_data)

        messagebox.showinfo('Saved', 'Configs saved to data folder.', parent=self.root)

    def import_config(self):
        """Manually import configuration from JSON file"""
        filename = filedialog.askopenfilename(
            title="Import Configuration",
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')]
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)

                # Determine what type of config this is
                if 'keywords' in data or 'passages' in data:
                    # It's a patterns file
                    self.patterns = data
                    self.update_patterns_ui()
                    messagebox.showinfo("Success", "Patterns imported successfully")
                elif isinstance(data, list):
                    # It's a simple exclusions list
                    self.exclusions = data
                    self.update_exclusions_ui()
                    messagebox.showinfo("Success", "Exclusions imported successfully")
                elif 'exclusions' in data:
                    # It might be a full config export
                    if 'patterns' in data:
                        self.patterns = data['patterns']
                        self.update_patterns_ui()
                    if 'exclusions' in data:
                        self.exclusions = data['exclusions']
                        self.update_exclusions_ui()
                    messagebox.showinfo("Success", "Configuration imported successfully")
                else:
                    messagebox.showwarning("Warning", "Unrecognized configuration format")

            except Exception as e:
                messagebox.showerror("Error", f"Failed to import configuration:\n{e}")

    def export_config(self):
        """Export current configuration to JSON file"""
        filename = filedialog.asksaveasfilename(
            title="Export Configuration",
            defaultextension=".json",
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')],
            initialfile=f"redaction_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        if filename:
            try:
                config = {
                    'patterns': self.patterns,
                    'exclusions': self.exclusions,
                    'excluded_passages': self.excluded_passages,
                    'regex_patterns': self.regex_patterns,
                    'preset': self.current_preset,
                    'exported': datetime.now().isoformat()
                }
                with open(filename, 'w') as f:
                    json.dump(config, f, indent=2)
                messagebox.showinfo("Success", f"Configuration exported to:\n{filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export configuration:\n{e}")

    def load_prefs(self):
        if JSONStore.PREFS_FILE.exists():
            try:
                data = json.loads(JSONStore.PREFS_FILE.read_text())
                geom = data.get('window_geometry')
                if geom:
                    self.root.geometry(geom)
                self.last_pdf = data.get('last_pdf')
                self.last_pane_position = data.get('pane_position')
                self.last_zoom = data.get('last_zoom', 2.0)
            except Exception:
                pass

    def save_prefs(self):
        data = {
            'window_geometry': self.root.geometry(),
            'last_pdf': getattr(self, 'last_pdf', ''),
            'pane_position': self.last_pane_position,
            'last_zoom': getattr(self.canvas, 'scale', 2.0)
        }
        JSONStore.write_atomic(JSONStore.PREFS_FILE, data)

    def on_pane_motion(self, event=None):
        """Save pane position when the splitter is moved"""
        try:
            pos = self.main_paned.sashpos(0)
            if pos != self.last_pane_position:
                self.last_pane_position = pos
                # debounce save
                if hasattr(self, '_pane_timer'):
                    self.root.after_cancel(self._pane_timer)
                self._pane_timer = self.root.after(500, self.save_prefs)
        except Exception:
            pass

    def schedule_preview_update(self):
        """Refresh preview shortly if enabled"""
        if not self.preview_var.get():
            return
        if hasattr(self, '_preview_timer'):
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = self.root.after(300, self.display_page)

    # ---------------------- UI setup ---------------------------
    def setup_ui(self):
        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open PDF (Ctrl+O)", command=self.open_pdf)
        file_menu.add_command(label="Save Redacted (Ctrl+S)", command=self.save_redacted)
        file_menu.add_separator()
        file_menu.add_command(label="Import Config (Ctrl+I)", command=self.import_config)
        file_menu.add_command(label="Export Config (Ctrl+E)", command=self.export_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # Add Presets menu
        preset_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Presets", menu=preset_menu)
        for preset_name in self.presets:
            preset_menu.add_command(label=preset_name,
                                    command=lambda n=preset_name: self.apply_preset(n))
        preset_menu.add_separator()
        preset_menu.add_command(label="Save Current as Preset...", command=self.save_as_preset)
        preset_menu.add_command(label="Manage Presets...", command=self.manage_presets)

        # Toolbar
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text='Open PDF', command=self.open_pdf).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text='Save Regions', command=self.save_regions).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text='Save Redacted', command=self.save_redacted).pack(side=tk.LEFT, padx=5)

        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)

        # Tool mode buttons
        tool_frame = ttk.LabelFrame(toolbar, text="Tool Mode")
        tool_frame.pack(side=tk.LEFT, padx=5)

        self.tool_var = tk.StringVar(value=ToolMode.PAN.name)
        ttk.Radiobutton(tool_frame, text="Pan (Space)", variable=self.tool_var,
                        value=ToolMode.PAN.name, command=self.on_tool_change).pack(side=tk.LEFT)
        ttk.Radiobutton(tool_frame, text="Text (T)", variable=self.tool_var,
                        value=ToolMode.TEXT_SELECT.name, command=self.on_tool_change).pack(side=tk.LEFT)
        ttk.Radiobutton(tool_frame, text="Draw (R/P)", variable=self.tool_var,
                        value=ToolMode.DRAW_REDACT.name, command=self.on_tool_change).pack(side=tk.LEFT)

        # Drawing mode toggle (redact vs protect)
        draw_frame = ttk.LabelFrame(toolbar, text="Draw Mode")
        draw_frame.pack(side=tk.LEFT, padx=5)
        self.mode_var = tk.StringVar(value='redact')
        ttk.Radiobutton(draw_frame, text='Redact', variable=self.mode_var,
                        value='redact', command=self.on_mode_change).pack(side=tk.LEFT)
        ttk.Radiobutton(draw_frame, text='Protect', variable=self.mode_var,
                        value='protect', command=self.on_mode_change).pack(side=tk.LEFT)

        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)

        # Page navigation
        ttk.Button(toolbar, text='< Prev', command=self.prev_page).pack(side=tk.LEFT)
        ttk.Button(toolbar, text='Next >', command=self.next_page).pack(side=tk.LEFT)
        self.page_label = ttk.Label(toolbar, text='No PDF')
        self.page_label.pack(side=tk.LEFT, padx=10)

        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)

        ttk.Button(toolbar, text='Undo', command=self.undo).pack(side=tk.LEFT)
        ttk.Button(toolbar, text='Redo', command=self.redo).pack(side=tk.LEFT)

        ttk.Separator(toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=3)

        self.preview_var = tk.BooleanVar()
        ttk.Checkbutton(toolbar, text='Preview', variable=self.preview_var, command=self.display_page).pack(
            side=tk.LEFT)

        # OCR checkbox
        ttk.Checkbutton(toolbar, text='Use OCR', variable=self.use_ocr,
                        command=self.display_page,
                        state='normal' if OCR_AVAILABLE else 'disabled').pack(side=tk.LEFT)

        ttk.Button(toolbar, text='Help', command=self.show_help).pack(side=tk.RIGHT, padx=5)

        # Main area with resizable panes
        self.main_paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(self.main_paned)
        side_frame = ttk.Frame(self.main_paned)

        self.main_paned.add(canvas_frame, weight=3)
        self.main_paned.add(side_frame, weight=1)

        # Restore previous pane position
        if self.last_pane_position is not None:
            try:
                self.main_paned.sashpos(0, self.last_pane_position)
            except Exception:
                pass

        # Track pane movement
        self.main_paned.bind('<B1-Motion>', self.on_pane_motion)
        self.main_paned.bind('<ButtonRelease-1>', self.on_pane_motion)

        # Canvas area
        self.canvas = PDFCanvas(canvas_frame)

        # Bind canvas events
        self.canvas.bind('<ButtonPress-1>', self.on_canvas_press)
        self.canvas.bind('<B1-Motion>', self.on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_canvas_release)
        self.canvas.bind('<Button-3>', self.on_canvas_right_click)

        # Middle mouse for panning always
        self.canvas.bind('<ButtonPress-2>', self.canvas.start_pan)
        self.canvas.bind('<B2-Motion>', self.canvas.drag_pan)

        # Mouse wheel for scrolling
        self.canvas.bind('<MouseWheel>', self.on_mousewheel)
        self.canvas.bind('<Button-4>', self.on_mousewheel)
        self.canvas.bind('<Button-5>', self.on_mousewheel)

        # Side notebook
        notebook = ttk.Notebook(side_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_pats = ttk.Frame(notebook)
        tab_exc = ttk.Frame(notebook)
        tab_regs = ttk.Frame(notebook)
        tab_presets = ttk.Frame(notebook)

        notebook.add(tab_pats, text='Patterns')
        notebook.add(tab_exc, text='Exclusions')
        notebook.add(tab_regs, text='Regions')
        notebook.add(tab_presets, text='Presets')

        self.create_patterns_tab(tab_pats)
        self.create_exclusions_tab(tab_exc)
        self.create_regions_tab(tab_regs)
        self.create_presets_tab(tab_presets)

        # Status bar
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_patterns_tab(self, parent):
        ttk.Label(parent, text='Keywords:').pack(anchor='w')

        kw_frame = ttk.Frame(parent)
        kw_frame.pack(fill=tk.BOTH, expand=True, padx=5)

        self.keywords_lb = tk.Listbox(kw_frame, height=5)
        self.keywords_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        kw_scroll = ttk.Scrollbar(kw_frame, command=self.keywords_lb.yview)
        kw_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.keywords_lb.config(yscrollcommand=kw_scroll.set)

        # Entry and buttons for keywords
        kw_entry_frame = ttk.Frame(parent)
        kw_entry_frame.pack(fill=tk.X, padx=5, pady=5)

        self.kw_entry = ttk.Entry(kw_entry_frame)
        self.kw_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(kw_entry_frame, text='Add',
                   command=lambda: self._add_keyword()).pack(side=tk.LEFT, padx=2)
        ttk.Button(kw_entry_frame, text='Delete',
                   command=lambda: self._del_listbox_item(self.keywords_lb)).pack(side=tk.LEFT, padx=2)

        ttk.Label(parent, text='Passages (separate with ---):').pack(anchor='w', pady=(10, 0))
        self.passages_txt = scrolledtext.ScrolledText(parent, height=8)
        self.passages_txt.pack(fill=tk.BOTH, expand=True, padx=5)
        self.passages_txt.bind('<KeyRelease>',
                               lambda e: (self.update_patterns_from_ui(), self.schedule_preview_update()))

        ttk.Button(parent, text='Save Patterns', command=self.save_patterns).pack(pady=5)

        # Update UI with loaded data
        self.update_patterns_ui()

    def create_exclusions_tab(self, parent):
        ttk.Label(parent, text='Exclusion Keywords:').pack(anchor='w')

        exc_frame = ttk.Frame(parent)
        exc_frame.pack(fill=tk.BOTH, expand=True, padx=5)

        self.excl_lb = tk.Listbox(exc_frame)
        self.excl_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        exc_scroll = ttk.Scrollbar(exc_frame, command=self.excl_lb.yview)
        exc_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.excl_lb.config(yscrollcommand=exc_scroll.set)

        exc_entry_frame = ttk.Frame(parent)
        exc_entry_frame.pack(fill=tk.X, padx=5, pady=5)

        self.exc_entry = ttk.Entry(exc_entry_frame)
        self.exc_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(exc_entry_frame, text='Add',
                   command=lambda: self._add_exclusion()).pack(side=tk.LEFT, padx=2)
        ttk.Button(exc_entry_frame, text='Delete',
                   command=lambda: self._del_listbox_item(self.excl_lb)).pack(side=tk.LEFT, padx=2)

        ttk.Button(parent, text='Add Keyword from Selection',
                   command=self.add_exclusion_from_selection).pack(pady=5)

        ttk.Label(parent, text='Excluded Passages (--- separated):').pack(anchor='w', pady=(10, 0))
        self.excluded_passages_txt = scrolledtext.ScrolledText(parent, height=8)
        self.excluded_passages_txt.pack(fill=tk.BOTH, expand=True, padx=5)
        self.excluded_passages_txt.bind('<KeyRelease>',
                                        lambda e: (self.update_exclusions_from_ui(), self.schedule_preview_update()))

        pass_btn_frame = ttk.Frame(parent)
        pass_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(pass_btn_frame, text='Add Passage from Selection',
                   command=self.add_excluded_passage_from_selection).pack(side=tk.LEFT, padx=2)
        ttk.Button(pass_btn_frame, text='Clear Passages',
                   command=lambda: self.excluded_passages_txt.delete(1.0, tk.END)).pack(side=tk.LEFT, padx=2)

        ttk.Button(parent, text='Save Exclusions', command=self.save_exclusions).pack(pady=5)

        self.update_exclusions_ui()
        self.update_excluded_passages_ui()

    def create_regions_tab(self, parent):
        columns = ('page', 'x1', 'y1', 'x2', 'y2', 'kind')
        self.region_tree = ttk.Treeview(parent, columns=columns, show='headings', selectmode='browse', height=10)
        for col in columns:
            self.region_tree.heading(col, text=col.upper())
            self.region_tree.column(col, width=60, anchor='center')
        self.region_tree.pack(fill=tk.BOTH, expand=True)
        self.region_tree.bind('<<TreeviewSelect>>', self.on_region_select)
        self.region_tree.bind('<Delete>', lambda e: self.delete_selected_region())

        edit = ttk.Frame(parent)
        edit.pack(fill=tk.X, pady=5)
        self.reg_label = ttk.Label(edit, text='No selection')
        self.reg_label.pack(side=tk.LEFT, padx=5)

        self.x1_var = tk.DoubleVar()
        self.y1_var = tk.DoubleVar()
        self.x2_var = tk.DoubleVar()
        self.y2_var = tk.DoubleVar()
        for lbl, var in [('x1', self.x1_var), ('y1', self.y1_var), ('x2', self.x2_var), ('y2', self.y2_var)]:
            ttk.Label(edit, text=lbl).pack(side=tk.LEFT)
            ttk.Entry(edit, textvariable=var, width=6).pack(side=tk.LEFT)

        ttk.Button(edit, text='Update', command=self.update_selected_region).pack(side=tk.LEFT, padx=5)
        ttk.Button(edit, text='Delete', command=self.delete_selected_region).pack(side=tk.LEFT)

        self.refresh_region_tree()

    def create_presets_tab(self, parent):
        """Create the presets tab UI."""
        # Current preset label
        self.preset_label = ttk.Label(parent, text="No preset active",
                                      font=('TkDefaultFont', 10, 'bold'))
        self.preset_label.pack(pady=10)

        # Preset list
        ttk.Label(parent, text="Available Presets:").pack(anchor='w', padx=10)

        preset_frame = ttk.Frame(parent)
        preset_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.preset_listbox = tk.Listbox(preset_frame, height=10)
        self.preset_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        preset_scroll = ttk.Scrollbar(preset_frame, command=self.preset_listbox.yview)
        preset_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preset_listbox.config(yscrollcommand=preset_scroll.set)

        # Populate preset list
        self.update_preset_list()

        # Preset details
        details_frame = ttk.LabelFrame(parent, text="Preset Details")
        details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.preset_details = scrolledtext.ScrolledText(details_frame, height=8, wrap=tk.WORD)
        self.preset_details.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="Apply Preset",
                   command=self.apply_selected_preset).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Save Current as Preset",
                   command=self.save_as_preset).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete Preset",
                   command=self.delete_selected_preset).pack(side=tk.LEFT, padx=5)

        # Bind selection event
        self.preset_listbox.bind('<<ListboxSelect>>', self.on_preset_select)

    def update_preset_list(self):
        """Update the preset listbox."""
        self.preset_listbox.delete(0, tk.END)
        for name in sorted(self.presets.keys()):
            self.preset_listbox.insert(tk.END, name)

    def on_preset_select(self, event):
        """Handle preset selection."""
        selection = self.preset_listbox.curselection()
        if selection:
            preset_name = self.preset_listbox.get(selection[0])
            preset = self.presets.get(preset_name, {})

            # Show preset details
            details = f"Name: {preset.get('name', preset_name)}\n\n"
            details += f"Description: {preset.get('description', 'No description')}\n\n"

            patterns = preset.get('patterns', {})
            if patterns.get('keywords'):
                details += f"Keywords: {', '.join(patterns['keywords'][:5])}"
                if len(patterns['keywords']) > 5:
                    details += f" ... ({len(patterns['keywords'])} total)"
                details += "\n\n"

            if patterns.get('passages'):
                details += f"Passages: {len(patterns['passages'])} defined\n\n"

            if preset.get('regex_patterns'):
                details += f"Regex Patterns: {len(preset['regex_patterns'])} defined\n"
                for i, pattern in enumerate(preset['regex_patterns'][:3]):
                    details += f"  {i + 1}. {pattern}\n"
                if len(preset['regex_patterns']) > 3:
                    details += f"  ... ({len(preset['regex_patterns'])} total)\n"

            self.preset_details.delete(1.0, tk.END)
            self.preset_details.insert(1.0, details)

    def apply_preset(self, preset_name: str):
        """Apply a preset configuration."""
        preset = self.presets.get(preset_name)
        if not preset:
            return

        # Apply patterns
        self.patterns = preset.get('patterns', {'keywords': [], 'passages': []}).copy()
        self.regex_patterns = preset.get('regex_patterns', []).copy()

        # Update UI
        self.update_patterns_ui()
        self.current_preset = preset_name
        self.preset_label.config(text=f"Active preset: {preset_name}")

        # Update display
        self.schedule_preview_update()

        self.status_bar.config(text=f"Applied preset: {preset_name}")

    def apply_selected_preset(self):
        """Apply the currently selected preset."""
        selection = self.preset_listbox.curselection()
        if selection:
            preset_name = self.preset_listbox.get(selection[0])
            self.apply_preset(preset_name)

    def save_as_preset(self):
        """Save current configuration as a new preset."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Save as Preset")
        dialog.geometry("400x300")

        ttk.Label(dialog, text="Preset Name:").pack(padx=10, pady=5)
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.pack(padx=10, pady=5)

        ttk.Label(dialog, text="Description:").pack(padx=10, pady=5)
        desc_text = scrolledtext.ScrolledText(dialog, height=6, width=40)
        desc_text.pack(padx=10, pady=5)

        def save():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Error", "Please enter a preset name", parent=dialog)
                return

            # Create preset
            preset = {
                'name': name,
                'description': desc_text.get(1.0, tk.END).strip(),
                'patterns': self.patterns.copy(),
                'regex_patterns': self.regex_patterns.copy(),
                'created': datetime.now().isoformat()
            }

            # Save to presets
            self.presets[name] = preset
            JSONStore.save_presets(self.presets)

            # Update UI
            self.update_preset_list()

            messagebox.showinfo("Success", f"Saved preset: {name}", parent=dialog)
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Save", command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def delete_selected_preset(self):
        """Delete the selected preset."""
        selection = self.preset_listbox.curselection()
        if not selection:
            return

        preset_name = self.preset_listbox.get(selection[0])

        # Don't allow deleting built-in presets
        if preset_name in REDACTION_PRESETS:
            messagebox.showerror("Error", "Cannot delete built-in presets")
            return

        if messagebox.askyesno("Confirm Delete",
                               f"Delete preset '{preset_name}'?"):
            del self.presets[preset_name]
            JSONStore.save_presets(self.presets)
            self.update_preset_list()
            self.preset_details.delete(1.0, tk.END)

    def manage_presets(self):
        """Open preset management dialog."""
        # This could be expanded to allow importing/exporting presets
        messagebox.showinfo("Manage Presets",
                            "Use the Presets tab to manage your presets.\n\n"
                            "You can:\n"
                            "- Apply existing presets\n"
                            "- Save current settings as a new preset\n"
                            "- Delete custom presets\n\n"
                            "Built-in presets cannot be deleted.")

    def update_patterns_ui(self):
        """Update patterns UI elements"""
        self.keywords_lb.delete(0, tk.END)
        for kw in self.patterns.get('keywords', []):
            self.keywords_lb.insert(tk.END, kw)

        self.passages_txt.delete(1.0, tk.END)
        self.passages_txt.insert(tk.END, '\n---\n'.join(self.patterns.get('passages', [])))

    def update_exclusions_ui(self):
        """Update exclusions UI elements"""
        self.excl_lb.delete(0, tk.END)
        for ex in self.exclusions:
            self.excl_lb.insert(tk.END, ex)
        if hasattr(self, 'excluded_passages_txt'):
            self.excluded_passages_txt.delete(1.0, tk.END)
            self.excluded_passages_txt.insert(tk.END, '\n---\n'.join(self.excluded_passages))

    def update_excluded_passages_ui(self):
        """Update excluded passages UI"""
        self.excluded_passages_txt.delete(1.0, tk.END)
        self.excluded_passages_txt.insert(tk.END, '\n---\n'.join(self.excluded_passages))

    # -------- region management tab ---------
    def refresh_region_tree(self):
        if not hasattr(self, 'region_tree'):
            return
        self.region_tree.delete(*self.region_tree.get_children())
        if not self.region_store:
            return
        for kind, data in [('redact', self.region_store.regions), ('protect', self.region_store.protect)]:
            for page_str, regs in data.items():
                page = int(page_str)
                for idx, (x1, y1, x2, y2) in enumerate(regs):
                    iid = f"{kind}-{page}-{idx}"
                    self.region_tree.insert('', 'end', iid=iid,
                                            values=(page, f"{x1:.1f}", f"{y1:.1f}", f"{x2:.1f}", f"{y2:.1f}", kind))

    def on_region_select(self, event=None):
        sel = self.region_tree.selection()
        if not sel:
            self.reg_label.config(text='No selection')
            return
        item = self.region_tree.item(sel[0])
        page, x1, y1, x2, y2, kind = item['values']
        self.reg_label.config(text=f"Page {page} - {kind}")
        self.x1_var.set(float(x1))
        self.y1_var.set(float(y1))
        self.x2_var.set(float(x2))
        self.y2_var.set(float(y2))

    def update_selected_region(self):
        if not self.region_store:
            return
        sel = self.region_tree.selection()
        if not sel:
            return
        iid = sel[0]
        kind, page, index = iid.split('-')
        bbox = [self.x1_var.get(), self.y1_var.get(), self.x2_var.get(), self.y2_var.get()]
        if self.region_store.update(int(page), int(index), bbox, kind=kind):
            self.refresh_region_tree()
            self.display_page()

    def delete_selected_region(self):
        if not self.region_store:
            return
        sel = list(self.region_tree.selection())
        for iid in sel:
            kind, page, index = iid.split('-')
            self.region_store.remove(int(page), int(index), kind)
        self.refresh_region_tree()
        self.display_page()

    def update_patterns_from_ui(self):
        """Sync pattern data from widgets"""
        self.patterns = {
            'keywords': list(self.keywords_lb.get(0, tk.END)),
            'passages': [p.strip() for p in self.passages_txt.get(1.0, tk.END).split('\n---\n') if p.strip()]
        }

    def update_exclusions_from_ui(self):
        """Sync exclusion data from widgets"""
        self.exclusions = list(self.excl_lb.get(0, tk.END))
        self.excluded_passages = [p.strip() for p in self.excluded_passages_txt.get(1.0, tk.END).split('\n---\n') if
                                  p.strip()]

    def _add_keyword(self):
        text = self.kw_entry.get().strip()
        if text:
            self.keywords_lb.insert(tk.END, text)
            self.kw_entry.delete(0, tk.END)
            self.update_patterns_from_ui()
            self.schedule_preview_update()

    def _add_exclusion(self):
        text = self.exc_entry.get().strip()
        if text:
            self.excl_lb.insert(tk.END, text)
            self.exc_entry.delete(0, tk.END)
            self.update_exclusions_from_ui()
            self.schedule_preview_update()

    def _del_listbox_item(self, listbox: tk.Listbox):
        sel = list(listbox.curselection())
        for i in reversed(sel):
            listbox.delete(i)
        if listbox == self.keywords_lb:
            self.update_patterns_from_ui()
        elif listbox == self.excl_lb:
            self.update_exclusions_from_ui()
        self.schedule_preview_update()

    def add_exclusion_from_selection(self):
        """Add selected text to exclusions"""
        if self.current_tool != ToolMode.TEXT_SELECT:
            messagebox.showinfo("Info", "Switch to Text Selection mode (T) and select text first")
            return

        # Get last selected text if any
        if hasattr(self, 'last_selected_text') and self.last_selected_text:
            self.excl_lb.insert(tk.END, self.last_selected_text)
            self.status_bar.config(text=f"Added to exclusions: {self.last_selected_text[:50]}...")
            self.update_exclusions_from_ui()
            self.schedule_preview_update()
        else:
            messagebox.showinfo("Info", "No text selected. Use Text Selection tool to select text first.")

    def add_excluded_passage_from_selection(self):
        """Add selected text to excluded passages"""
        if self.current_tool != ToolMode.TEXT_SELECT:
            messagebox.showinfo("Info", "Switch to Text Selection mode (T) and select text first")
            return

        if hasattr(self, 'last_selected_text') and self.last_selected_text:
            # Add to text area with separator if not empty
            current = self.excluded_passages_txt.get(1.0, tk.END).strip()
            if current:
                self.excluded_passages_txt.insert(tk.END, '\n---\n')
            self.excluded_passages_txt.insert(tk.END, self.last_selected_text)
            self.status_bar.config(text=f"Added to excluded passages: {self.last_selected_text[:50]}...")
            self.update_exclusions_from_ui()
            self.schedule_preview_update()
        else:
            messagebox.showinfo("Info", "No text selected. Use Text Selection tool to select text first.")

    def set_tool_mode(self, mode: ToolMode):
        """Set the current tool mode"""
        self.current_tool = mode
        self.tool_var.set(mode.name)
        self.canvas.set_tool_mode(mode)

        # Update status bar
        mode_names = {
            ToolMode.PAN: "Pan Mode - Click and drag to move",
            ToolMode.TEXT_SELECT: "Text Selection Mode - Click and drag to select text",
            ToolMode.DRAW_REDACT: "Draw Mode - Click and drag to create regions",
            ToolMode.DRAW_PROTECT: "Draw Mode - Click and drag to create regions"
        }
        self.status_bar.config(text=mode_names.get(mode, ""))

    def on_tool_change(self):
        """Handle tool mode change from radio buttons"""
        mode_name = self.tool_var.get()
        mode = ToolMode[mode_name]

        # If switching to draw mode, set appropriate drawing mode
        if mode == ToolMode.DRAW_REDACT:
            self.mode_var.set('redact')
            self.drawing_mode = 'redact'
        elif mode == ToolMode.DRAW_PROTECT:
            self.mode_var.set('protect')
            self.drawing_mode = 'protect'

        self.set_tool_mode(mode)

    def on_mode_change(self):
        """Handle drawing mode change (redact vs protect)"""
        self.drawing_mode = self.mode_var.get()
        # Update tool mode to match
        if self.drawing_mode == 'redact':
            self.set_tool_mode(ToolMode.DRAW_REDACT)
        else:
            self.set_tool_mode(ToolMode.DRAW_PROTECT)

    # Canvas event handlers
    def on_canvas_press(self, event):
        if self.current_tool == ToolMode.PAN:
            self.canvas.start_pan(event)
        elif self.current_tool == ToolMode.TEXT_SELECT:
            self.canvas.start_text_selection(event)
        elif self.current_tool in (ToolMode.DRAW_REDACT, ToolMode.DRAW_PROTECT):
            self.start_draw(event)

    def on_canvas_drag(self, event):
        if self.current_tool == ToolMode.PAN:
            self.canvas.drag_pan(event)
        elif self.current_tool == ToolMode.TEXT_SELECT:
            self.canvas.update_text_selection(event)
        elif self.current_tool in (ToolMode.DRAW_REDACT, ToolMode.DRAW_PROTECT):
            self.update_draw(event)

    def on_canvas_release(self, event):
        if self.current_tool == ToolMode.TEXT_SELECT:
            text = self.canvas.end_text_selection(event)
            if text:
                self.last_selected_text = text
                self.status_bar.config(text=f"Selected: {text[:100]}...")
                # Optionally show a dialog asking what to do with the text
                self.show_text_action_dialog(text)
        elif self.current_tool in (ToolMode.DRAW_REDACT, ToolMode.DRAW_PROTECT):
            self.end_draw(event)

    def show_text_action_dialog(self, text):
        """Show dialog for text selection actions"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Text Selected")
        dialog.geometry("500x300")

        ttk.Label(dialog, text="Selected text:").pack(padx=10, pady=5)

        text_widget = scrolledtext.ScrolledText(dialog, height=6, wrap=tk.WORD)
        text_widget.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        text_widget.insert(1.0, text)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="Add to Patterns",
                   command=lambda: self._add_to_patterns(text_widget.get(1.0, tk.END).strip(), dialog)).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Add Keyword",
                   command=lambda: self._add_to_exclusions(text_widget.get(1.0, tk.END).strip(), dialog)).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Add Passage",
                   command=lambda: self._add_to_excluded_passages(text_widget.get(1.0, tk.END).strip(), dialog)).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel",
                   command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _add_to_patterns(self, text, dialog):
        self.keywords_lb.insert(tk.END, text)
        self.update_patterns_from_ui()
        self.schedule_preview_update()
        dialog.destroy()

    def _add_to_exclusions(self, text, dialog):
        self.excl_lb.insert(tk.END, text)
        self.update_exclusions_from_ui()
        self.schedule_preview_update()
        dialog.destroy()

    def _add_to_excluded_passages(self, text, dialog):
        current = self.excluded_passages_txt.get(1.0, tk.END).strip()
        if current:
            self.excluded_passages_txt.insert(tk.END, '\n---\n')
        self.excluded_passages_txt.insert(tk.END, text)
        self.update_exclusions_from_ui()
        self.schedule_preview_update()
        dialog.destroy()

    def on_mousewheel(self, event):
        """Handle mouse wheel scrolling"""
        # Check if Ctrl is held - if so, let the zoom handler deal with it
        if event.state & 0x0004:  # Control key
            return

        # Horizontal scrolling when Shift is held or tilt wheel
        if event.state & 0x0001 or getattr(event, 'num', None) in (6, 7):
            if event.delta:
                self.canvas.xview_scroll(int(-1 * (event.delta / 120)), 'units')
            else:
                if event.num in (6,):
                    self.canvas.xview_scroll(-1, 'units')
                elif event.num in (7,):
                    self.canvas.xview_scroll(1, 'units')
            return

        # Vertical scrolling
        if event.delta:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        else:
            if event.num == 4:
                self.canvas.yview_scroll(-1, 'units')
            elif event.num == 5:
                self.canvas.yview_scroll(1, 'units')

    # --------------------- Navigation & Undo -------------------
    def prev_page(self, *args):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()

    def next_page(self, *args):
        if self.doc and self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self.display_page()

    def zoom_in(self, *args):
        self.canvas.scale = min(self.canvas.scale * 1.1, 10.0)
        self.display_page()
        self.save_prefs()

    def zoom_out(self, *args):
        self.canvas.scale = max(self.canvas.scale / 1.1, 0.2)
        self.display_page()
        self.save_prefs()

    def zoom_reset(self, *args):
        self.canvas.scale = 1.0
        self.display_page()
        self.save_prefs()

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
        msg = '''PDF Redactor Help

TOOLS:
• Pan Mode (Space): Click and drag to move around the PDF
• Text Select (T): Click and drag to select text
• Draw Mode (R/P): Draw rectangles to redact or protect areas

SHORTCUTS:
• Ctrl+O: Open PDF
• Ctrl+S: Save redacted PDF
• Ctrl+Z/Y: Undo/Redo
• Ctrl+I/E: Import/Export config
• Ctrl+Mouse Wheel or Ctrl+ +/-: Zoom in/out (Ctrl+0 resets)
• Left/Right arrows: Navigate pages

FEATURES:
• Draw red rectangles to mark areas for redaction
• Draw green rectangles to protect areas from text redaction
• Select text and add to patterns, exclusions, or excluded passages
• Preview mode shows what will be redacted
• Configs are auto-saved with timestamps
• Exclusion keywords and passages override matching redaction patterns
• Regions tab lists all drawn boxes for manual editing or deletion (Del key)
• OCR support for scanned PDFs (enable with "Use OCR" checkbox)
• Preset workflows for common redaction tasks (see Presets menu)
• Regex pattern support for advanced text matching'''

        messagebox.showinfo('Help', msg, parent=self.root)

    # --------------------- PDF Handling ------------------------
    def open_pdf(self, path=None):
        filename = path or filedialog.askopenfilename(filetypes=[('PDF files', '*.pdf')])
        if not filename:
            return
        self.doc = fitz.open(filename)
        self.current_page = 0
        stem = Path(filename).stem
        self.region_store = RegionStore.load(stem)
        self.page_label.config(text=f"1 / {len(self.doc)}")
        self.last_pdf = filename

        # Check if PDF appears to be scanned
        if self.canvas.ocr_processor.ocr_available:
            self.is_scanned = self.canvas.ocr_processor.is_scanned_pdf(self.doc)
            if self.is_scanned:
                self.use_ocr.set(True)
                self.status_bar.config(text="Detected scanned PDF - OCR enabled")

        self.display_page()

    def display_page(self):
        if not self.doc:
            return
        p = self.doc[self.current_page]
        regs = self.region_store.regions.get(str(self.current_page), []) if self.region_store else []
        prot = self.region_store.protect.get(str(self.current_page), []) if self.region_store else []

        self.canvas.display(
            p, regs, prot,
            scale=self.canvas.scale,
            patterns=self.patterns,
            exclusions=self.exclusions,
            excluded_passages=self.excluded_passages,
            preview=self.preview_var.get(),
            use_ocr=self.use_ocr.get(),
            regex_patterns=self.regex_patterns
        )

        self.page_label.config(text=f"{self.current_page + 1} / {len(self.doc)}")
        self.refresh_region_tree()

    # Drawing
    def start_draw(self, event):
        self.start_x = self.canvas.canvasx(event.x) / self.canvas.scale
        self.start_y = self.canvas.canvasy(event.y) / self.canvas.scale
        color = 'red' if self.drawing_mode == 'redact' else 'green'
        self.temp_rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline=color, width=2)

    def update_draw(self, event):
        if hasattr(self, 'temp_rect'):
            self.canvas.coords(self.temp_rect,
                               self.start_x * self.canvas.scale,
                               self.start_y * self.canvas.scale,
                               self.canvas.canvasx(event.x),
                               self.canvas.canvasy(event.y))

    def end_draw(self, event):
        if hasattr(self, 'temp_rect'):
            x2 = self.canvas.canvasx(event.x) / self.canvas.scale
            y2 = self.canvas.canvasy(event.y) / self.canvas.scale
            rect = [min(self.start_x, x2), min(self.start_y, y2), max(self.start_x, x2), max(self.start_y, y2)]
            if self.region_store and (rect[2] - rect[0] > 5) and (rect[3] - rect[1] > 5):
                self.region_store.add(self.current_page, rect, kind=self.drawing_mode)
            self.canvas.delete(self.temp_rect)
            del self.temp_rect
            self.display_page()

    # Region interaction helpers
    def find_region_at(self, x: float, y: float):
        """Return (kind, index) of region containing point or None."""
        page_key = str(self.current_page)
        regs = self.region_store.regions.get(page_key, []) if self.region_store else []
        for i, (x1, y1, x2, y2) in enumerate(regs):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return 'redact', i
        prot = self.region_store.protect.get(page_key, []) if self.region_store else []
        for i, (x1, y1, x2, y2) in enumerate(prot):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return 'protect', i
        return None

    def delete_region(self, kind: str, index: int):
        if self.region_store and self.region_store.remove(self.current_page, index, kind=kind):
            self.display_page()

    def toggle_region_kind(self, kind: str, index: int):
        if not self.region_store:
            return
        page_key = str(self.current_page)
        if kind == 'redact':
            rect = self.region_store.regions[page_key][index]
            self.region_store.remove(self.current_page, index, 'redact')
            self.region_store.add(self.current_page, rect, kind='protect')
        else:
            rect = self.region_store.protect[page_key][index]
            self.region_store.remove(self.current_page, index, 'protect')
            self.region_store.add(self.current_page, rect, kind='redact')
        self.display_page()

    def on_canvas_right_click(self, event):
        if not self.region_store:
            return
        x = self.canvas.canvasx(event.x) / self.canvas.scale
        y = self.canvas.canvasy(event.y) / self.canvas.scale
        hit = self.find_region_at(x, y)
        if not hit:
            return
        kind, idx = hit
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label='Delete Region', command=lambda: self.delete_region(kind, idx))
        menu.add_command(label='Toggle Redact/Protect', command=lambda: self.toggle_region_kind(kind, idx))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------- Save ----------------------------
    def save_patterns(self):
        kws = list(self.keywords_lb.get(0, tk.END))
        passages = [p.strip() for p in self.passages_txt.get(1.0, tk.END).split('\n---\n') if p.strip()]
        self.patterns = {'keywords': kws, 'passages': passages}
        self.save_app_configs()
        self.schedule_preview_update()

    def save_exclusions(self):
        self.exclusions = list(self.excl_lb.get(0, tk.END))
        passages = [p.strip() for p in self.excluded_passages_txt.get(1.0, tk.END).split('\n---\n') if p.strip()]
        self.excluded_passages = passages
        self.save_app_configs()
        self.schedule_preview_update()

    def save_excluded_passages(self):
        """Backwards compatibility wrapper"""
        self.save_exclusions()

    def save_redacted(self):
        if not self.doc:
            return
        self.region_store.save()
        output = filedialog.asksaveasfilename(defaultextension='.pdf', filetypes=[('PDF', '*.pdf')])
        if not output:
            return

        # Show progress dialog for OCR processing
        if self.use_ocr.get() and OCR_AVAILABLE:
            progress = tk.Toplevel(self.root)
            progress.title("Processing...")
            progress.geometry("300x100")
            ttk.Label(progress, text="Applying redactions with OCR...").pack(pady=20)
            progress_bar = ttk.Progressbar(progress, mode='indeterminate')
            progress_bar.pack(padx=20, fill=tk.X)
            progress_bar.start()
            self.root.update()

        # Combine exclusions and excluded passages
        all_exclusions = self.exclusions + self.excluded_passages

        try:
            apply_redactions(
                self.doc.name, output,
                self.region_store.regions,
                self.region_store.protect,
                self.patterns,
                all_exclusions,
                self.regex_patterns,
                self.use_ocr.get()
            )
            messagebox.showinfo('Done', f'Saved to {output}', parent=self.root)
        finally:
            if self.use_ocr.get() and OCR_AVAILABLE:
                progress.destroy()


# ---------------------------------------------------------------------------
# Core redaction logic (enhanced with OCR and regex)
# ---------------------------------------------------------------------------
def apply_redactions(input_pdf: str, output_pdf: str, regions: dict[str, list],
                     protect_regions: dict[str, list], patterns: dict,
                     exclusions: list, regex_patterns: list = None,
                     use_ocr: bool = False):
    doc = fitz.open(input_pdf)
    ocr_processor = OCRProcessor() if use_ocr else None

    # region redactions
    for page_num, regs in regions.items():
        page = doc[int(page_num)]
        for x1, y1, x2, y2 in regs:
            page.add_redact_annot(fitz.Rect(x1, y1, x2, y2), fill=(0, 0, 0))

    # text patterns
    all_patterns = patterns.get('keywords', []).copy()
    all_patterns += patterns.get('passages', [])

    for page_num, page in enumerate(doc):
        # Get protected regions for this page
        protected = protect_regions.get(str(page_num), [])

        # Regular text pattern search
        for pattern in all_patterns:
            if any(excl.lower() in pattern.lower() for excl in exclusions):
                continue

            for area in page.search_for(pattern, quads=False):
                # Check if area is in a protected region
                is_protected = False
                for px1, py1, px2, py2 in protected:
                    prot_rect = fitz.Rect(px1, py1, px2, py2)
                    if prot_rect.contains(area):
                        is_protected = True
                        break

                if not is_protected:
                    # Check context for exclusions
                    should_redact = True
                    expanded = fitz.Rect(area)
                    expanded.x0 -= 20
                    expanded.x1 += 20
                    try:
                        context = page.get_textbox(expanded)
                        if any(excl.lower() in context.lower() for excl in exclusions):
                            should_redact = False
                    except:
                        pass

                    if should_redact:
                        page.add_redact_annot(area, fill=(0, 0, 0))

        # OCR-based search if enabled
        if use_ocr and ocr_processor and ocr_processor.ocr_available:
            ocr_results = ocr_processor.extract_text_with_positions(page)
            for text, rect in ocr_results:
                for pattern in all_patterns:
                    if pattern.lower() in text.lower():
                        # Check protections and exclusions
                        is_protected = any(
                            rect.x0 >= px1 and rect.y0 >= py1 and
                            rect.x1 <= px2 and rect.y1 <= py2
                            for px1, py1, px2, py2 in protected
                        )

                        if not is_protected:
                            # Check context
                            should_redact = True
                            if any(excl.lower() in text.lower() for excl in exclusions):
                                should_redact = False

                            if should_redact:
                                page.add_redact_annot(rect, fill=(0, 0, 0))

        # Regex pattern search
        if regex_patterns:
            page_text = page.get_text()
            for pattern in regex_patterns:
                try:
                    for match in re.finditer(pattern, page_text, re.IGNORECASE):
                        matched_text = match.group(0)
                        # Find location on page
                        for area in page.search_for(matched_text, quads=False):
                            # Check protections
                            is_protected = any(
                                area.x0 >= px1 and area.y0 >= py1 and
                                area.x1 <= px2 and area.y1 <= py2
                                for px1, py1, px2, py2 in protected
                            )

                            if not is_protected:
                                # Check exclusions
                                should_redact = True
                                expanded = fitz.Rect(area)
                                expanded.x0 -= 20
                                expanded.x1 += 20
                                try:
                                    context = page.get_textbox(expanded)
                                    if any(excl.lower() in context.lower() for excl in exclusions):
                                        should_redact = False
                                except:
                                    pass

                                if should_redact:
                                    page.add_redact_annot(area, fill=(0, 0, 0))
                except re.error:
                    continue

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
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Enhanced PDF redactor with OCR support')
    parser.add_argument('--gui', action='store_true', help='Launch GUI')
    parser.add_argument('input', nargs='?', help='Input PDF for CLI apply mode')
    parser.add_argument('output', nargs='?', help='Output PDF for CLI apply mode')
    parser.add_argument('--patterns', help='Path to JSON patterns file')
    parser.add_argument('--exclusions', help='Path to JSON exclusions file')
    parser.add_argument('--regions', help='Path to JSON region file')
    parser.add_argument('--preset', help='Apply a named preset')
    parser.add_argument('--ocr', action='store_true', help='Use OCR for scanned PDFs')
    parser.add_argument('--apply', action='store_true', help='Apply redactions')

    args = parser.parse_args()

    if args.gui or (not args.input and not args.apply):
        run_gui()
        return

    if args.input and not args.output:
        parser.error('output PDF required in CLI mode')

    # CLI mode - apply redactions
    if args.apply or (args.input and args.output):
        # Load preset if specified
        regex_patterns = []
        if args.preset:
            presets = JSONStore.load_presets()
            preset = presets.get(args.preset)
            if preset:
                patterns = preset.get('patterns', {'keywords': [], 'passages': []})
                regex_patterns = preset.get('regex_patterns', [])
                print(f"Applied preset: {args.preset}")
            else:
                print(f"Warning: Preset '{args.preset}' not found")
                patterns = {'keywords': [], 'passages': []}
        else:
            # Load patterns
            patterns = {'keywords': [], 'passages': []}
            if args.patterns:
                with open(args.patterns) as f:
                    patterns = json.load(f)
            else:
                pat = JSONStore.find_latest_file('app_wide', 'patterns')
                if pat:
                    patterns = json.loads(pat.read_text())

        # Load exclusions
        exclusions = []
        excluded_passages = []
        if args.exclusions:
            with open(args.exclusions) as f:
                data = json.load(f)
                if isinstance(data, list):
                    exclusions = data
                elif isinstance(data, dict):
                    exclusions = data.get('keywords', [])
                    excluded_passages = data.get('passages', [])
        else:
            exc = JSONStore.find_latest_file('app_wide', 'exclusions')
            if exc:
                data = json.loads(exc.read_text())
                if isinstance(data, list):
                    exclusions = data
                elif isinstance(data, dict):
                    exclusions = data.get('keywords', [])
                    excluded_passages = data.get('passages', [])

        # Combine all exclusions
        all_exclusions = exclusions + excluded_passages

        # Load regions
        regions = {}
        protect_regions = {}
        if args.regions:
            with open(args.regions) as f:
                data = json.load(f)
                regions = data.get('regions', {})
                protect_regions = data.get('protect', {})
        else:
            store = RegionStore.load(Path(args.input).stem)
            regions = store.regions
            protect_regions = store.protect

        apply_redactions(args.input, args.output, regions, protect_regions,
                         patterns, all_exclusions, regex_patterns, args.ocr)
        print(f'Saved to {args.output}')


if __name__ == '__main__':
    main()
