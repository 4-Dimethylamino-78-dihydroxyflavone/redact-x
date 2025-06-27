#!/usr/bin/env python3
"""
nova_bulk_redact.py

Redacts every occurrence of each line in your sensitive passages,
plus keywords/names, from a PDF. Visual (black box) redaction.

Usage: python nova_bulk_redact.py input.pdf output.pdf
"""

import sys
import fitz  # pip install pymupdf

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
    "fate",
    "fatema",
    "brooke",
    "messiter",
    "clancy",
    "sasindra",
    "Sasindra",
    "havana johansson",
    "ren ",
    " ren"
]

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

def redact_pdf(input_pdf, output_pdf, targets):
    doc = fitz.open(input_pdf)
    total = 0
    for page in doc:
        for target in targets:
            # Case-insensitive search for each line/keyword
            areas = page.search_for(target, quads=False, hit_max=9999)
            for area in areas:
                page.add_redact_annot(area, fill=(0, 0, 0))
                total += 1
        page.apply_redactions()
    doc.save(output_pdf, garbage=4)
    print(f"[✓] {total} redactions applied. Output → {output_pdf}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python nova_bulk_redact.py input.pdf output.pdf")
        sys.exit(1)
    # Build target list from all passage lines and keywords
    targets = build_targets(PASSAGES, KEYWORDS)
    redact_pdf(sys.argv[1], sys.argv[2], targets)
