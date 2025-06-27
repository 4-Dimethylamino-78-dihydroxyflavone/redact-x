#!/usr/bin/env python3
"""
pdf_region_finder.py - Interactive tool to find coordinates for redaction

This tool helps you visually identify regions in your PDF and generates
the coordinate list for the main redaction script.

Usage:
    python pdf_region_finder.py input.pdf

Requirements:
    pip install pymupdf pillow
"""

import sys
import fitz
from PIL import Image, ImageDraw, ImageFont
import os
import json


class RegionFinder:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.regions = []
        self.output_dir = "pdf_pages_preview"

    def export_pages_as_images(self, dpi=150):
        """Export all PDF pages as images for easier coordinate finding"""
        os.makedirs(self.output_dir, exist_ok=True)

        print(f"📄 Exporting {len(self.doc)} pages as images...")

        for i, page in enumerate(self.doc):
            # Render page to image
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            # Save as PNG
            img_path = os.path.join(self.output_dir, f"page_{i + 1}_index_{i}.png")
            pix.save(img_path)

            # Also create a grid overlay version
            self._create_grid_overlay(img_path, i, page.rect.width, page.rect.height)

            print(f"   ✓ Page {i + 1} exported")

        print(f"\n✅ Images saved to: {os.path.abspath(self.output_dir)}")
        print("\n📏 Finding coordinates:")
        print("   1. Open the images in any image editor")
        print("   2. Use the selection tool to find coordinates")
        print("   3. Grid images show 100px grid for reference")

    def _create_grid_overlay(self, img_path, page_index, pdf_width, pdf_height):
        """Create a version with coordinate grid overlay"""
        img = Image.open(img_path)
        draw = ImageDraw.Draw(img)

        # Draw grid every 100 pixels
        grid_spacing = 100

        # Vertical lines
        for x in range(0, img.width, grid_spacing):
            pdf_x = int(x * pdf_width / img.width)
            draw.line([(x, 0), (x, img.height)], fill=(255, 0, 0, 50), width=1)
            draw.text((x + 2, 2), str(pdf_x), fill=(255, 0, 0))

        # Horizontal lines
        for y in range(0, img.height, grid_spacing):
            pdf_y = int(y * pdf_height / img.height)
            draw.line([(0, y), (img.width, y)], fill=(255, 0, 0, 50), width=1)
            draw.text((2, y + 2), str(pdf_y), fill=(255, 0, 0))

        # Save grid version
        grid_path = img_path.replace('.png', '_grid.png')
        img.save(grid_path)

    def add_region_interactive(self):
        """Interactive mode to add regions"""
        print("\n🎯 Manual Region Entry")
        print("Enter regions in format: page x1 y1 x2 y2")
        print("Example: 2 100 200 300 400")
        print("Type 'done' when finished\n")

        while True:
            entry = input("Region (or 'done'): ").strip()
            if entry.lower() == 'done':
                break

            try:
                parts = entry.split()
                if len(parts) == 5:
                    page, x1, y1, x2, y2 = map(int, parts)
                    # Convert to 0-based page index
                    self.regions.append((page - 1, x1, y1, x2, y2))
                    print(f"   ✓ Added region on page {page}")
                else:
                    print("   ❌ Invalid format. Use: page x1 y1 x2 y2")
            except:
                print("   ❌ Invalid input")

    def save_regions(self):
        """Save regions to a file that can be copied to the main script"""
        output_file = "redact_regions.py"

        with open(output_file, 'w') as f:
            f.write("# Generated redaction regions\n")
            f.write("# Copy this to your main redaction script\n\n")
            f.write("REDACT_REGIONS = [\n")

            for region in self.regions:
                f.write(f"    {region},  # Page {region[0] + 1}\n")

            f.write("]\n")

        print(f"\n✅ Regions saved to: {output_file}")
        print("   Copy the REDACT_REGIONS list to your main script")

    def preview_redactions(self):
        """Create preview images showing where redactions will be applied"""
        if not self.regions:
            print("No regions defined yet!")
            return

        print("\n🖼️  Creating redaction preview...")

        for i, page in enumerate(self.doc):
            # Check if this page has any redactions
            page_regions = [r for r in self.regions if r[0] == i]
            if not page_regions:
                continue

            # Render page
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img)

            # Draw redaction rectangles
            scale_x = pix.width / page.rect.width
            scale_y = pix.height / page.rect.height

            for region in page_regions:
                _, x1, y1, x2, y2 = region
                # Scale coordinates
                x1_scaled = int(x1 * scale_x)
                y1_scaled = int(y1 * scale_y)
                x2_scaled = int(x2 * scale_x)
                y2_scaled = int(y2 * scale_y)

                # Draw semi-transparent black rectangle
                draw.rectangle([x1_scaled, y1_scaled, x2_scaled, y2_scaled],
                               fill=(0, 0, 0, 200))
                # Draw red border
                draw.rectangle([x1_scaled, y1_scaled, x2_scaled, y2_scaled],
                               outline=(255, 0, 0), width=2)

            # Save preview
            preview_path = os.path.join(self.output_dir, f"page_{i + 1}_PREVIEW.png")
            img.save(preview_path)
            print(f"   ✓ Preview for page {i + 1} created")

    def run(self):
        """Main workflow"""
        print(f"\n📚 PDF Region Finder")
        print(f"PDF: {self.pdf_path}")
        print(f"Pages: {len(self.doc)}")

        # Export pages
        self.export_pages_as_images()

        # Interactive region entry
        self.add_region_interactive()

        if self.regions:
            # Create preview
            self.preview_redactions()

            # Save regions
            self.save_regions()

        self.doc.close()


def main():
    if len(sys.argv) != 2:
        print("Usage: python pdf_region_finder.py input.pdf")
        sys.exit(1)

    finder = RegionFinder(sys.argv[1])
    finder.run()


if __name__ == "__main__":
    main()