#!/usr/bin/env python3
"""
nova_bulk_redact.py

Redacts every occurrence of each line in your sensitive passages,
plus keywords/names, from a PDF. Visual (black box) redaction.

Now includes EXCLUSIONS list to prevent certain terms from being redacted.

Usage: python nova_bulk_redact.py input.pdf output.pdf
"""

import sys
import fitz  # pip install pymupdf

# MANUAL REDACTION REGIONS
# Format: (page_number, x1, y1, x2, y2) - page numbers start at 0
# Or: (page_number, x, y, width, height, "xywh") for x,y,width,height format
REDACT_REGIONS = [
    # Example: Redact Discord profile image on page 2 (page index 1)
    (1, 470, 570, 615, 850),  # (page, left, top, right, bottom)

    # You can also use x,y,width,height format:
    # (1, 470, 570, 145, 280, "xywh"),  # (page, x, y, width, height, "xywh")

    # Add more regions as needed:
    # (0, 100, 200, 300, 400),  # Redact area on page 1
    # (2, 50, 50, 200, 200),    # Redact area on page 3
]


# Helper function to get page dimensions and show preview
def preview_pages(pdf_path):
    """Show page dimensions to help identify coordinates"""
    doc = fitz.open(pdf_path)
    print("\n📄 PDF Page Information:")
    print("-" * 50)
    for i, page in enumerate(doc):
        rect = page.rect
        print(f"Page {i + 1} (index {i}):")
        print(f"  Width: {rect.width:.1f} pixels")
        print(f"  Height: {rect.height:.1f} pixels")
        print(f"  Coordinates: (0, 0) to ({rect.width:.1f}, {rect.height:.1f})")
    print("-" * 50)
    print("\n💡 Tip: Use image editing software to find exact coordinates:")
    print("   1. Export PDF pages as images (many PDF readers can do this)")
    print("   2. Open in any image editor to see pixel coordinates")
    print("   3. Add regions to REDACT_REGIONS list\n")
    doc.close()


# Function to apply manual region redactions
def apply_region_redactions(doc, regions):
    """Apply redactions to manually specified regions"""
    region_count = 0

    for region in regions:
        if len(region) == 5:
            # Format: (page, x1, y1, x2, y2)
            page_num, x1, y1, x2, y2 = region
            rect = fitz.Rect(x1, y1, x2, y2)
        elif len(region) == 6 and region[5] == "xywh":
            # Format: (page, x, y, width, height, "xywh")
            page_num, x, y, w, h, _ = region
            rect = fitz.Rect(x, y, x + w, y + h)
        else:
            print(f"⚠️  Invalid region format: {region}")
            continue

        # Check if page exists
        if 0 <= page_num < len(doc):
            page = doc[page_num]
            page.add_redact_annot(rect, fill=(0, 0, 0))
            region_count += 1
        else:
            print(f"⚠️  Page {page_num} doesn't exist (PDF has {len(doc)} pages)")

    # Apply all redactions
    for page in doc:
        page.apply_redactions()

    return region_count


# Your passages, as multiline strings (just copy-paste more below if needed)
PASSAGES = [
    """
    (2025-05-12-1626)
    Yooo, another HSV-2 study (with pay)
    https://northernbeachesclinicalresearch.com/studies/#!/study/122
    HSV-2 Vaccine/Treatment Phase I trials
    - ABI-5366 https://clinicaltrials.gov/study/NCT06385327 (In Sydney)
    - ABI-1179 https://clinicaltrials.gov/study/NCT06698575 (In Sydney Not Recruiting)
    - https://clinicaltrials.gov/study/NCT05298254 (Also in Sydney (Last update 2024-11-07)
    """,
    """
    about gender roles, the perception of danger, changes in humanity for the next century
    """,
    """
    the potential polymetallic nodule birthday present [Options 1 & 2].
    """,
    """
    paper quilling postcards
    """,
    """
    I think our next
    """,
    """
    long rambling section
    """,
    """
    my mother who
    """,
    """
    of Stepping Stones
    """,
    """
    and instead walk far away from Tom's party to weep in silence.
    """,
    """
    Btw, I should confess I watched the film with you on a significant psychedelic dose
    """,
    """
    Laying on the couch for 30 minutes afterwards letting the message seep in
    """,
    """
    I mention this as one of my favourite artists is
    """,
    """
    the poor Englishman whose madness slippage spilt across his late work
    """,
    """
    My brain has claimed its glory over me
    """,
    """
    I've a good heart albeit anxiety
    """,
    """
    Condemn him to the Infirmary
    """,
    """
    Living for the present
    """,
    """
    I invite you to compliment the string of gifts I'm scheming for others
    """,
    """
    introduce you to sweet white Moscato wines, Mead liqueur, Cloudberry Lakka or perhaps even Lychee liqueur
    """,
    """
    I'd like to get Chelsea swell seashells from our seashores
    """,
    """
    unfortunately missing her birthday to chase lightning up the Wide Bay
    """,
    """
    To finally visit the Richmond lapidary club, For Prj. Lazuli
    """,
    """
    To finally visit the Richmond lapidary club, For Prj. Lazuli
    """,
    """
    To finally visit the Richmond lapidary club, For Prj. Lazuli
    """,
    """
    All titles are available on Polymath's Jellyfin
    """,
    """
    These three Muong Nong tektites won't facet themselves!
    """
]

# Any extra keywords or names:
KEYWORDS = [
    "Noodle Messiter_2025-05-22-1525_FINAL- v4-font",
    "noodl",
    "noodle",
    "Havana Johansson",
    "Havana",
    "National Art School",
    "Metaphysical Department, ",
    "School of Science",
    "I, for one,",
    "(2025-06-15)",
    "(2025-04-09)",
    "Tom",
    "Tom's ",
    "Western Sydney University",
    "Their Caves",
    "mother who",
    "Cleo Eshun-Wilson",
    "Cleo",
    "Stepping Stones",
    "mum",
    "mother",
    "quilling",
    "Quilling",
    "Eshun-Wilson",
    "fate ",
    " fate",
    "fatema ",
    " fatema",
    "brooke ",
    " brooke",
    "messiter",
    "clancy",
    "sasindra",
    "Sasindra",
    "havana johansson",
    "ren ",
    " ren",
    "Nicholas Eshun-Wilson",
    "Nicholas",
    "Nic",
    "psychedelic",
    "psychedelic dose",
    "madness",
    "anxiety",
    "Infirmary",
    "Chelsea",
    "Richmond lapidary club",
    "Prj. Lazuli",
    "Project Lazuli",
    "Muong Nong tektites",
    "tektites",
    "Wide Bay",
    "Urangan",
    "Urangan Aquarium",
    "Tonna Perdix",
    "Tonna Galea",
    "Strawberry Top",
    "Moscato",
    "Mead liqueur",
    "Cloudberry Lakka",
    "Lychee liqueur",
    "gifts I'm scheming",
    "string of gifts",
    "birthday",
    "lightning",
    "Advanced Child Care, TAFE",
    "TAFE",
    "Letter 005",
    "Elusive Lustre",
    "Polymath's Jellyfin",
    "Jellyfin",
    "Note:",
    "Note: ",
    "From:",
    "To:",
    "hallucineko",
    "Hallucineko",
    "hallucineko + ha/him",
    "Daydreaming...",
    "Edit Profile",
    "discord",
    "My discord",
    "Fig ",
    "Figure ",
    "Fig 1a:",
    "Fig 1b:",
    "2a-b: ",
    "Fig 1c:",
    "Fig 1d-e:",
    "Fig 2a-b:",
    "Fig 2c-f:",
    "Fig 2g:",
    "Fig 2h-k:",
    "faceting boss",
    "alcoholic gift candidates",
    "Gift candidates",
    # Names and partial names still visible
    "Nic",
    "Nicole Arriaga",
    "titanic",
    "titan",

    "shell exhibit",
    "Aquarium",
    "aquarium",
    "Polymath",
    "Polymath's",
    "shell exhibit",

    # Gift-related terms
    "Tonna Perdix",
    "Tonna",
    "Perdix",
    "Galea",
    "liqueur",
    "liqueurs",
    "Lychee",
    "sweet white",
    "white",
    "sweet",
    "fermentation"
]

# EXCLUSIONS: Terms that should NOT be redacted
# These will be checked before redaction - if found within a larger phrase,
# that phrase won't be redacted
EXCLUSIONS = [
    # Common words that might appear in titles/content
    "the",
    "and",
    "for",
    "with",
    "from",
    "about",

    # Film/media titles you want to keep visible
    "KPop Demon Hunters",
    "K-Pop Demon Hunters",
    "Perfect Blue",
    "Memoirs of a Geisha",
    "Words on Bathroom Walls",
    "Robot & Frank",
    "Scott Pilgrim vs the World",
    "Sing",
    "Verónica",
    "Next to Normal",

    # Professional titles/credits
    "Animation Magazine",
    "Gayety",
    "Variety",
    "Wikipedia",

    # Technical terms
    "schizophrenic",  # when used in medical/film context
    "bipolar",
    "disorder",
    "bittersweet",
    "Magus Archive",
    "a schizophre",
    "schizophre",
    "schizophrenic"

    # Add more exclusions as needed
]


def should_exclude(target, area_text, exclusions):
    """
    Check if the target area should be excluded from redaction.
    Returns True if any exclusion term is found in the area text.
    """
    # Get the text in the area to be redacted
    for exclusion in exclusions:
        # Check if the exclusion appears in the same area
        if exclusion.lower() in area_text.lower():
            return True
    return False


def build_targets(passages, keywords):
    """Flatten passage lines and combine with keywords."""
    targets = []
    for passage in passages:
        for line in passage.strip().splitlines():
            s = line.strip()
            if s:  # ignore blank lines
                targets.append(s)
    targets += keywords
    return targets


def redact_pdf(input_pdf, output_pdf, targets, exclusions):
    doc = fitz.open(input_pdf)
    total = 0
    skipped = 0

    for page_num, page in enumerate(doc):
        # Get full page text for context
        page_text = page.get_text()

        for target in targets:
            # Skip if target is in exclusions
            if target in exclusions:
                continue

            # Case-insensitive search for each line/keyword
            areas = page.search_for(target, quads=False, hit_max=9999)

            for area in areas:
                # Extract text from the specific area
                area_text = page.get_textbox(area)

                # Check if we should exclude this redaction
                exclude = False

                # Method 1: Check if the target itself should be excluded
                for exclusion in exclusions:
                    if exclusion.lower() in target.lower():
                        exclude = True
                        break

                # Method 2: Check surrounding context (get a bit more text around the area)
                if not exclude:
                    # Expand the area slightly to get context
                    expanded = fitz.Rect(area)
                    expanded.x0 -= 50
                    expanded.x1 += 50
                    try:
                        context_text = page.get_textbox(expanded)
                        for exclusion in exclusions:
                            if exclusion.lower() in context_text.lower():
                                exclude = True
                                break
                    except:
                        pass

                if not exclude:
                    page.add_redact_annot(area, fill=(0, 0, 0))
                    total += 1
                else:
                    skipped += 1

        page.apply_redactions()

    doc.save(output_pdf, garbage=4)
    print(f"[✓] {total} redactions applied, {skipped} skipped due to exclusions. Output → {output_pdf}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python nova_bulk_redact.py input.pdf output.pdf")
        sys.exit(1)
    # Build target list from all passage lines and keywords
    targets = build_targets(PASSAGES, KEYWORDS)
    redact_pdf(sys.argv[1], sys.argv[2], targets, EXCLUSIONS)