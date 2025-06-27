#!/usr/bin/env python3
"""
redact-3_GUI.py - Visual PDF Redaction System

A complete GUI for managing PDF redactions with external JSON storage.
- Visual region selection
- Dynamic text pattern management
- Exclusion lists
- File-specific configurations

Requirements:
    pip install pymupdf pillow

Usage:
    python redact-3_GUI.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import fitz
from PIL import Image, ImageTk, ImageDraw
import json
import os
from datetime import datetime
from pathlib import Path


class PDFRedactorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(Path(__file__))
        self.root.geometry("1200x800")
        base = Path(__file__).stem

        # Initialize variables
        self.current_pdf = None
        self.current_page = 0
        self.doc = None
        self.regions = []  # Current file's regions
        self.temp_region = None  # For drawing
        self.scale_factor = 1.0

        # Config file names derived from that base
        self.patterns_file   = f"{base}_patterns.json"
        self.exclusions_file = f"{base}_exclusions.json"
        self.file_regions = {}  # Store regions per file
        self.protect_regions = {}     # Store protected_regions

        # Load or create configs
        self.load_configs()

        # Setup UI
        self.setup_ui()

    def load_configs(self):
        """Load patterns and exclusions from JSON files"""
        # Load patterns
        if os.path.exists(self.patterns_file):
            with open(self.patterns_file, 'r') as f:
                self.patterns = json.load(f)
        else:
            self.patterns = {
                "keywords": [],
                "passages": []
            }

        # Load exclusions
        if os.path.exists(self.exclusions_file):
            with open(self.exclusions_file, 'r') as f:
                self.exclusions = json.load(f)
        else:
            self.exclusions = []

    def save_configs(self):
        """Save patterns and exclusions to JSON files"""
        with open(self.patterns_file, 'w') as f:
            json.dump(self.patterns, f, indent=2)

        with open(self.exclusions_file, 'w') as f:
            json.dump(self.exclusions, f, indent=2)

    def setup_ui(self):
        """Create the GUI layout"""
        # Create menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open PDF", command=self.open_pdf)
        file_menu.add_command(label="Save Redacted PDF", command=self.save_redacted)
        file_menu.add_separator()
        file_menu.add_command(label="Export Config", command=self.export_config)
        file_menu.add_command(label="Import Config", command=self.import_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        # Create main layout
        self.create_main_layout()

    def create_main_layout(self):
        """Create the main UI layout"""
        # Top toolbar
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        ttk.Button(toolbar, text="Open PDF", command=self.open_pdf).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Previous Page", command=self.prev_page).pack(side=tk.LEFT, padx=5)
        self.page_label = ttk.Label(toolbar, text="No PDF loaded")
        self.page_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(toolbar, text="Next Page", command=self.next_page).pack(side=tk.LEFT, padx=5)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        ttk.Button(toolbar, text="Apply Redactions", command=self.save_redacted).pack(side=tk.LEFT, padx=5)

        # Main content area
        main_frame = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel - PDF viewer
        left_panel = ttk.Frame(main_frame)
        main_frame.add(left_panel, weight=3)

        # Canvas for PDF display
        canvas_frame = ttk.Frame(left_panel)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg="gray")
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        # Bind mouse events for region selection
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

        # Region controls
        region_controls = ttk.Frame(left_panel)
        region_controls.pack(fill=tk.X, pady=5)

        ttk.Label(region_controls, text="Click and drag to select regions to redact").pack(side=tk.LEFT, padx=5)
        ttk.Button(region_controls, text="Clear All Regions", command=self.clear_regions).pack(side=tk.RIGHT, padx=5)
        ttk.Button(region_controls, text="Undo Last Region", command=self.undo_region).pack(side=tk.RIGHT, padx=5)

        # Right panel - Controls
        right_panel = ttk.Notebook(main_frame)
        main_frame.add(right_panel, weight=1)

        # Text patterns tab
        patterns_tab = ttk.Frame(right_panel)
        right_panel.add(patterns_tab, text="Text Patterns")
        self.create_patterns_tab(patterns_tab)

        # Exclusions tab
        exclusions_tab = ttk.Frame(right_panel)
        right_panel.add(exclusions_tab, text="Exclusions")
        self.create_exclusions_tab(exclusions_tab)

        # Regions tab
        regions_tab = ttk.Frame(right_panel)
        right_panel.add(regions_tab, text="Regions")
        self.create_regions_tab(regions_tab)

        # Status bar
        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_patterns_tab(self, parent):
        """Create the text patterns management tab"""
        # Keywords section
        ttk.Label(parent, text="Keywords to Redact:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)

        keywords_frame = ttk.Frame(parent)
        keywords_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.keywords_listbox = tk.Listbox(keywords_frame, height=10)
        self.keywords_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        keywords_scrollbar = ttk.Scrollbar(keywords_frame, command=self.keywords_listbox.yview)
        keywords_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.keywords_listbox.config(yscrollcommand=keywords_scrollbar.set)

        # Load existing keywords
        for keyword in self.patterns.get("keywords", []):
            self.keywords_listbox.insert(tk.END, keyword)

        # Add keyword controls
        keyword_controls = ttk.Frame(parent)
        keyword_controls.pack(fill=tk.X, padx=5, pady=5)

        self.keyword_entry = ttk.Entry(keyword_controls)
        self.keyword_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(keyword_controls, text="Add", command=self.add_keyword).pack(side=tk.LEFT, padx=5)
        ttk.Button(keyword_controls, text="Remove", command=self.remove_keyword).pack(side=tk.LEFT)

        # Passages section
        ttk.Label(parent, text="Passages to Redact:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5, pady=(20, 5))

        self.passages_text = scrolledtext.ScrolledText(parent, height=10, width=40)
        self.passages_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Load existing passages
        self.passages_text.insert(tk.END, "\n---\n".join(self.patterns.get("passages", [])))

        passages_controls = ttk.Frame(parent)
        passages_controls.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(passages_controls, text="Save Patterns", command=self.save_patterns).pack(side=tk.RIGHT)
        ttk.Label(passages_controls, text="Separate passages with ---").pack(side=tk.LEFT)

    def create_exclusions_tab(self, parent):
        """Create the exclusions management tab"""
        ttk.Label(parent, text="Text to Preserve (won't be redacted):", font=("", 10, "bold")).pack(anchor=tk.W, padx=5,
                                                                                                    pady=5)

        exclusions_frame = ttk.Frame(parent)
        exclusions_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.exclusions_listbox = tk.Listbox(exclusions_frame)
        self.exclusions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        exclusions_scrollbar = ttk.Scrollbar(exclusions_frame, command=self.exclusions_listbox.yview)
        exclusions_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.exclusions_listbox.config(yscrollcommand=exclusions_scrollbar.set)

        # Load existing exclusions
        for exclusion in self.exclusions:
            self.exclusions_listbox.insert(tk.END, exclusion)

        # Add exclusion controls
        exclusion_controls = ttk.Frame(parent)
        exclusion_controls.pack(fill=tk.X, padx=5, pady=5)

        self.exclusion_entry = ttk.Entry(exclusion_controls)
        self.exclusion_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(exclusion_controls, text="Add", command=self.add_exclusion).pack(side=tk.LEFT, padx=5)
        ttk.Button(exclusion_controls, text="Remove", command=self.remove_exclusion).pack(side=tk.LEFT)

        ttk.Button(parent, text="Save Exclusions", command=self.save_exclusions).pack(side=tk.BOTTOM, pady=10)

    def create_regions_tab(self, parent):
        """Create the regions management tab"""
        ttk.Label(parent, text="Selected Regions for Current Page:", font=("", 10, "bold")).pack(anchor=tk.W, padx=5,
                                                                                                 pady=5)

        # Regions list
        self.regions_listbox = tk.Listbox(parent, height=15)
        self.regions_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Region controls
        region_controls = ttk.Frame(parent)
        region_controls.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(region_controls, text="Remove Selected", command=self.remove_selected_region).pack(side=tk.LEFT,
                                                                                                      padx=5)
        ttk.Button(region_controls, text="Clear All", command=self.clear_regions).pack(side=tk.LEFT)

        # Manual entry
        ttk.Label(parent, text="Manual Entry (x1,y1,x2,y2):", font=("", 9)).pack(anchor=tk.W, padx=5, pady=(20, 5))

        manual_frame = ttk.Frame(parent)
        manual_frame.pack(fill=tk.X, padx=5, pady=5)

        self.manual_entry = ttk.Entry(manual_frame)
        self.manual_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(manual_frame, text="Add Region", command=self.add_manual_region).pack(side=tk.LEFT, padx=5)

    def open_pdf(self):
        """Open a PDF file"""
        filename = filedialog.askopenfilename(
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )

        if filename:
            self.current_pdf = filename
            self.doc = fitz.open(filename)
            self.current_page = 0

            # ── redact-regions handling (already there) ─────────────
            pdf_regions_file = f"{Path(filename).stem}_regions.json"
            if os.path.exists(pdf_regions_file):
                with open(pdf_regions_file, 'r') as f:
                    self.file_regions = json.load(f)
            else:
                self.file_regions = {}

            # ── NEW: protect-regions handling ───────────────────────
            self.protect_regions_file = f"{Path(filename).stem}_protect_regions.json"
            if os.path.exists(self.protect_regions_file):
                with open(self.protect_regions_file, 'r') as f:
                    self.protect_regions = json.load(f)
            else:
                self.protect_regions = {}

            # finally, load regions for page 0
            self.load_regions_for_page(self.current_page)
            self.display_page()
    def display_page(self):
        """Display the current PDF page"""
        if not self.doc:
            return

        # Clear canvas
        self.canvas.delete("all")

        # Get page
        page = self.doc[self.current_page]

        # Render page
        mat = fitz.Matrix(2, 2)  # 2x zoom for better quality
        pix = page.get_pixmap(matrix=mat)

        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Store scale factor
        self.scale_factor = 2.0
        self.page_width = page.rect.width
        self.page_height = page.rect.height

        # Draw existing regions
        draw = ImageDraw.Draw(img, 'RGBA')
        for region in self.regions:
            x1, y1, x2, y2 = region
            # Scale coordinates
            x1_scaled = int(x1 * self.scale_factor)
            y1_scaled = int(y1 * self.scale_factor)
            x2_scaled = int(x2 * self.scale_factor)
            y2_scaled = int(y2 * self.scale_factor)

            # Draw semi-transparent red rectangle
            draw.rectangle([x1_scaled, y1_scaled, x2_scaled, y2_scaled],
                           fill=(255, 0, 0, 100), outline=(255, 0, 0), width=2)

        # Convert to PhotoImage
        self.photo = ImageTk.PhotoImage(img)

        # Display on canvas
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

        # Update page label
        self.page_label.config(text=f"Page {self.current_page + 1} of {len(self.doc)}")

        # Load regions for this page
        self.regions = self.file_regions.get(str(self.current_page), [])
        self.update_regions_list()

    def save_current_regions(self):
        # Always save current page’s regions
        if self.doc is not None:
            self.file_regions[str(self.current_page)] = list(self.regions)  # Copy to be safe

    def load_regions_for_page(self, page_num):
        # Always load fresh for the new page
        self.regions = list(self.file_regions.get(str(page_num), []))

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.save_current_regions()
            self.current_page -= 1
            self.load_regions_for_page(self.current_page)
            self.display_page()

    def next_page(self):
        if self.doc and self.current_page < len(self.doc) - 1:
            self.save_current_regions()
            self.current_page += 1
            self.load_regions_for_page(self.current_page)
            self.display_page()

    def on_canvas_click(self, event):
        """Start drawing a region"""
        # Get canvas coordinates
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)

        # Store start point
        self.start_x = canvas_x / self.scale_factor
        self.start_y = canvas_y / self.scale_factor

        # Create temporary rectangle
        self.temp_rect = self.canvas.create_rectangle(
            canvas_x, canvas_y, canvas_x, canvas_y,
            outline="red", width=2, fill=""
        )

    def on_canvas_drag(self, event):
        """Update the temporary region while dragging"""
        if hasattr(self, 'temp_rect'):
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)

            self.canvas.coords(self.temp_rect,
                               self.start_x * self.scale_factor,
                               self.start_y * self.scale_factor,
                               canvas_x, canvas_y)

    def on_canvas_release(self, event):
        """Finish drawing a region"""
        if hasattr(self, 'temp_rect'):
            canvas_x = self.canvas.canvasx(event.x)
            canvas_y = self.canvas.canvasy(event.y)

            # Calculate region in PDF coordinates
            x1 = min(self.start_x, canvas_x / self.scale_factor)
            y1 = min(self.start_y, canvas_y / self.scale_factor)
            x2 = max(self.start_x, canvas_x / self.scale_factor)
            y2 = max(self.start_y, canvas_y / self.scale_factor)

            # Only add if region has some size
            if abs(x2 - x1) > 5 and abs(y2 - y1) > 5:
                self.regions.append([x1, y1, x2, y2])
                self.file_regions[str(self.current_page)] = self.regions
                self.update_regions_list()
                self.display_page()  # Redraw to show the new region

            # Remove temporary rectangle
            self.canvas.delete(self.temp_rect)
            delattr(self, 'temp_rect')

    def update_regions_list(self):
        """Update the regions listbox"""
        self.regions_listbox.delete(0, tk.END)
        for i, region in enumerate(self.regions):
            x1, y1, x2, y2 = region
            self.regions_listbox.insert(tk.END,
                                        f"Region {i + 1}: ({int(x1)}, {int(y1)}) to ({int(x2)}, {int(y2)})")

    def clear_regions(self):
        """Clear all regions for current page"""
        self.regions = []
        self.file_regions[str(self.current_page)] = self.regions
        self.update_regions_list()
        self.display_page()

    def undo_region(self):
        """Remove the last added region"""
        if self.regions:
            self.regions.pop()
            self.file_regions[str(self.current_page)] = self.regions
            self.update_regions_list()
            self.display_page()

    def remove_selected_region(self):
        """Remove the selected region from the list"""
        selection = self.regions_listbox.curselection()
        if selection:
            index = selection[0]
            del self.regions[index]
            self.file_regions[str(self.current_page)] = self.regions
            self.update_regions_list()
            self.display_page()

    def add_manual_region(self):
        """Add a region from manual entry"""
        try:
            coords = self.manual_entry.get().split(',')
            if len(coords) == 4:
                region = [float(c.strip()) for c in coords]
                self.regions.append(region)
                self.file_regions[str(self.current_page)] = self.regions
                self.update_regions_list()
                self.display_page()
                self.manual_entry.delete(0, tk.END)
        except:
            messagebox.showerror("Error", "Invalid coordinates. Use format: x1,y1,x2,y2")

    def add_keyword(self):
        """Add a keyword to the patterns"""
        keyword = self.keyword_entry.get().strip()
        if keyword:
            self.keywords_listbox.insert(tk.END, keyword)
            self.keyword_entry.delete(0, tk.END)

    def remove_keyword(self):
        """Remove selected keyword"""
        selection = self.keywords_listbox.curselection()
        if selection:
            self.keywords_listbox.delete(selection[0])

    def add_exclusion(self):
        """Add an exclusion"""
        exclusion = self.exclusion_entry.get().strip()
        if exclusion:
            self.exclusions_listbox.insert(tk.END, exclusion)
            self.exclusion_entry.delete(0, tk.END)

    def remove_exclusion(self):
        """Remove selected exclusion"""
        selection = self.exclusions_listbox.curselection()
        if selection:
            self.exclusions_listbox.delete(selection[0])

    def save_patterns(self):
        """Save text patterns to JSON"""
        # Get keywords
        keywords = list(self.keywords_listbox.get(0, tk.END))

        # Get passages
        passages_text = self.passages_text.get(1.0, tk.END).strip()
        passages = [p.strip() for p in passages_text.split('---') if p.strip()]

        self.patterns = {
            "keywords": keywords,
            "passages": passages
        }

        self.save_configs()
        messagebox.showinfo("Success", "Patterns saved!")

    def save_exclusions(self):
        """Save exclusions to JSON"""
        self.exclusions = list(self.exclusions_listbox.get(0, tk.END))
        self.save_configs()
        messagebox.showinfo("Success", "Exclusions saved!")

    def save_redacted(self):
        """Apply all redactions and save the PDF"""
        if not self.doc:
            messagebox.showerror("Error", "No PDF loaded")
            return

        # Save current regions
        self.file_regions[str(self.current_page)] = self.regions

        # Save regions to file
        pdf_regions_file = f"{Path(self.current_pdf).stem}_regions.json"
        with open(self.protect_regions_file, 'w') as f:
            json.dump(self.protect_regions, f, indent=2)

        # Get output filename
        output_file = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialfile=f"{Path(self.current_pdf).stem}_redacted.pdf"
        )

        if not output_file:
            return

        # Apply redactions
        try:
            self.apply_all_redactions(output_file)
            messagebox.showinfo("Success", f"Redacted PDF saved to:\n{output_file}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save redacted PDF:\n{str(e)}")

    def apply_all_redactions(self, output_file):
        """Apply all redactions to the PDF"""
        # Create a new document for output
        output_doc = fitz.open(self.current_pdf)

        # Apply region redactions
        region_count = 0
        for page_num, regions in self.file_regions.items():
            page_idx = int(page_num)
            if 0 <= page_idx < len(output_doc):
                page = output_doc[page_idx]
                for region in regions:
                    x1, y1, x2, y2 = region
                    rect = fitz.Rect(x1, y1, x2, y2)
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    region_count += 1

        # Apply text redactions
        text_count = 0
        keywords = list(self.keywords_listbox.get(0, tk.END))
        passages_text = self.passages_text.get(1.0, tk.END).strip()
        passages = [p.strip() for p in passages_text.split('---') if p.strip()]
        exclusions = list(self.exclusions_listbox.get(0, tk.END))

        # Combine all text patterns
        all_patterns = keywords.copy()
        for passage in passages:
            passage_text = passage.strip()
            if passage_text:
                all_patterns.append(passage_text)

        # Apply text redactions
        for page in output_doc:
            for pattern in all_patterns:
                # Skip if in exclusions
                if any(excl.lower() in pattern.lower() for excl in exclusions):
                    continue

                areas = page.search_for(pattern, quads=False, hit_max=9999)
                for area in areas:
                    # Check context
                    should_redact = True
                    expanded = fitz.Rect(area)
                    expanded.x0 -= 50
                    expanded.x1 += 50
                    try:
                        context = page.get_textbox(expanded)
                        if any(excl.lower() in context.lower() for excl in exclusions):
                            should_redact = False
                    except:
                        pass

                    if should_redact:
                        page.add_redact_annot(area, fill=(0, 0, 0))
                        text_count += 1

        # Apply all redactions
        for page in output_doc:
            page.apply_redactions()

        # Save the output
        output_doc.save(output_file, garbage=4)
        output_doc.close()

        self.status_bar.config(text=f"Saved: {region_count} regions, {text_count} text redactions")

    def export_config(self):
        """Export complete configuration"""
        config = {
            "patterns": self.patterns,
            "exclusions": self.exclusions,
            "file_regions": self.file_regions,
            "created": datetime.now().isoformat()
        }

        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="redaction_config.json"
        )

        if filename:
            with open(filename, 'w') as f:
                json.dump(config, f, indent=2)
            messagebox.showinfo("Success", "Configuration exported!")

    def import_config(self):
        """Import configuration from file"""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if filename:
            try:
                with open(filename, 'r') as f:
                    config = json.load(f)

                # Load patterns
                if "patterns" in config:
                    self.patterns = config["patterns"]
                    # Update UI
                    self.keywords_listbox.delete(0, tk.END)
                    for keyword in self.patterns.get("keywords", []):
                        self.keywords_listbox.insert(tk.END, keyword)

                    self.passages_text.delete(1.0, tk.END)
                    self.passages_text.insert(tk.END, "\n---\n".join(self.patterns.get("passages", [])))

                # Load exclusions
                if "exclusions" in config:
                    self.exclusions = config["exclusions"]
                    self.exclusions_listbox.delete(0, tk.END)
                    for exclusion in self.exclusions:
                        self.exclusions_listbox.insert(tk.END, exclusion)

                # Load file regions if present
                if "file_regions" in config and self.current_pdf:
                    self.file_regions = config["file_regions"]
                    self.regions = self.file_regions.get(str(self.current_page), [])
                    self.update_regions_list()
                    self.display_page()

                self.save_configs()
                messagebox.showinfo("Success", "Configuration imported!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import configuration:\n{str(e)}")


def main():
    root = tk.Tk()
    app = PDFRedactorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()