#!/usr/bin/env python3
"""
batch_redactor.py - Command-line batch processor using GUI configs

Uses the same JSON configuration files as the GUI for batch processing.

Usage:
    python batch_redactor.py input.pdf output.pdf
    python batch_redactor.py --batch folder/
    python batch_redactor.py --edit-patterns
"""

import sys
import os
import json
import fitz
from pathlib import Path
import argparse


class BatchRedactor:
    def __init__(self):
        self.patterns_file = "pdf_redactor_patterns.json"
        self.exclusions_file = "pdf_redactor_exclusions.json"
        self.load_configs()

    def load_configs(self):
        """Load configuration files"""
        # Load patterns
        if os.path.exists(self.patterns_file):
            with open(self.patterns_file, 'r') as f:
                self.patterns = json.load(f)
        else:
            self.patterns = {"keywords": [], "passages": []}
            print(f"⚠️  No patterns file found. Run GUI or use --edit-patterns")

        # Load exclusions
        if os.path.exists(self.exclusions_file):
            with open(self.exclusions_file, 'r') as f:
                self.exclusions = json.load(f)
        else:
            self.exclusions = []

    def redact_pdf(self, input_file, output_file):
        """Redact a single PDF"""
        print(f"\n📄 Processing: {input_file}")

        # Open document
        doc = fitz.open(input_file)

        # Load regions for this file
        regions_file = f"{Path(input_file).stem}_regions.json"
        file_regions = {}
        if os.path.exists(regions_file):
            with open(regions_file, 'r') as f:
                file_regions = json.load(f)
            print(f"   ✓ Found regions file")

        # Apply region redactions
        region_count = 0
        for page_num, regions in file_regions.items():
            page_idx = int(page_num)
            if 0 <= page_idx < len(doc):
                page = doc[page_idx]
                for region in regions:
                    x1, y1, x2, y2 = region
                    rect = fitz.Rect(x1, y1, x2, y2)
                    page.add_redact_annot(rect, fill=(0, 0, 0))
                    region_count += 1

        # Build text patterns list
        all_patterns = self.patterns.get("keywords", []).copy()
        for passage in self.patterns.get("passages", []):
            for line in passage.splitlines():
                if line.strip():
                    all_patterns.append(line.strip())

        # Apply text redactions
        text_count = 0
        for page in doc:
            for pattern in all_patterns:
                # Skip if in exclusions
                if any(excl.lower() in pattern.lower() for excl in self.exclusions):
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
                        if any(excl.lower() in context.lower() for excl in self.exclusions):
                            should_redact = False
                    except:
                        pass

                    if should_redact:
                        page.add_redact_annot(area, fill=(0, 0, 0))
                        text_count += 1

        # Apply all redactions
        for page in doc:
            page.apply_redactions()

        # Save
        doc.save(output_file, garbage=4)
        doc.close()

        print(f"   ✓ Redacted: {region_count} regions, {text_count} text items")
        print(f"   ✓ Saved to: {output_file}")

        return True

    def batch_process(self, folder):
        """Process all PDFs in a folder"""
        pdf_files = list(Path(folder).glob("*.pdf"))

        if not pdf_files:
            print("No PDF files found in folder")
            return

        print(f"\n📁 Batch processing {len(pdf_files)} PDFs...")

        output_folder = Path(folder) / "redacted"
        output_folder.mkdir(exist_ok=True)

        success_count = 0
        for pdf_file in pdf_files:
            # Skip already redacted files
            if "_redacted" in pdf_file.name:
                continue

            output_file = output_folder / f"{pdf_file.stem}_redacted.pdf"

            try:
                self.redact_pdf(str(pdf_file), str(output_file))
                success_count += 1
            except Exception as e:
                print(f"   ❌ Failed: {pdf_file.name} - {str(e)}")

        print(f"\n✅ Batch complete: {success_count}/{len(pdf_files)} processed")
        print(f"📁 Output folder: {output_folder}")

    def edit_patterns_cli(self):
        """Simple CLI editor for patterns"""
        print("\n📝 Pattern Editor")
        print("-" * 40)

        while True:
            print("\n1. View keywords")
            print("2. Add keyword")
            print("3. Remove keyword")
            print("4. View passages")
            print("5. Add passage")
            print("6. Save and exit")

            choice = input("\nChoice: ").strip()

            if choice == "1":
                print("\nKeywords:")
                for i, kw in enumerate(self.patterns.get("keywords", [])):
                    print(f"  {i + 1}. {kw}")

            elif choice == "2":
                keyword = input("New keyword: ").strip()
                if keyword:
                    if "keywords" not in self.patterns:
                        self.patterns["keywords"] = []
                    self.patterns["keywords"].append(keyword)
                    print("✓ Added")

            elif choice == "3":
                self.view_keywords()
                try:
                    idx = int(input("Number to remove: ")) - 1
                    if 0 <= idx < len(self.patterns.get("keywords", [])):
                        removed = self.patterns["keywords"].pop(idx)
                        print(f"✓ Removed: {removed}")
                except:
                    print("Invalid selection")

            elif choice == "4":
                print("\nPassages:")
                for i, passage in enumerate(self.patterns.get("passages", [])):
                    print(f"\n--- Passage {i + 1} ---")
                    print(passage)

            elif choice == "5":
                print("Enter passage (end with blank line):")
                lines = []
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
                if lines:
                    if "passages" not in self.patterns:
                        self.patterns["passages"] = []
                    self.patterns["passages"].append("\n".join(lines))
                    print("✓ Added passage")

            elif choice == "6":
                with open(self.patterns_file, 'w') as f:
                    json.dump(self.patterns, f, indent=2)
                print("✓ Saved")
                break

    def show_stats(self):
        """Show configuration statistics"""
        print("\n📊 Redaction Configuration:")
        print(f"   Keywords: {len(self.patterns.get('keywords', []))}")
        print(f"   Passages: {len(self.patterns.get('passages', []))}")
        print(f"   Exclusions: {len(self.exclusions)}")

        # Check for region files
        region_files = list(Path().glob("*_regions.json"))
        print(f"   Region files: {len(region_files)}")

        if region_files:
            print("\n   PDFs with regions:")
            for rf in region_files[:5]:  # Show first 5
                print(f"     - {rf.stem.replace('_regions', '')}")
            if len(region_files) > 5:
                print(f"     ... and {len(region_files) - 5} more")


def main():
    parser = argparse.ArgumentParser(description="Batch PDF Redactor")
    parser.add_argument("input", nargs="?", help="Input PDF file")
    parser.add_argument("output", nargs="?", help="Output PDF file")
    parser.add_argument("--batch", help="Process all PDFs in folder")
    parser.add_argument("--edit-patterns", action="store_true", help="Edit patterns via CLI")
    parser.add_argument("--stats", action="store_true", help="Show configuration stats")
    parser.add_argument("--export-config", help="Export full config to file")
    parser.add_argument("--import-config", help="Import config from file")

    args = parser.parse_args()

    redactor = BatchRedactor()

    if args.stats:
        redactor.show_stats()

    elif args.edit_patterns:
        redactor.edit_patterns_cli()

    elif args.batch:
        redactor.batch_process(args.batch)

    elif args.export_config:
        config = {
            "patterns": redactor.patterns,
            "exclusions": redactor.exclusions
        }
        with open(args.export_config, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"✓ Config exported to: {args.export_config}")

    elif args.import_config:
        with open(args.import_config, 'r') as f:
            config = json.load(f)
        if "patterns" in config:
            redactor.patterns = config["patterns"]
            with open(redactor.patterns_file, 'w') as f:
                json.dump(redactor.patterns, f, indent=2)
        if "exclusions" in config:
            redactor.exclusions = config["exclusions"]
            with open(redactor.exclusions_file, 'w') as f:
                json.dump(redactor.exclusions, f, indent=2)
        print("✓ Config imported")

    elif args.input and args.output:
        redactor.redact_pdf(args.input, args.output)

    else:
        parser.print_help()
        print("\nExamples:")
        print("  python batch_redactor.py input.pdf output.pdf")
        print("  python batch_redactor.py --batch ./documents/")
        print("  python batch_redactor.py --edit-patterns")
        print("  python batch_redactor.py --stats")


if __name__ == "__main__":
    main()