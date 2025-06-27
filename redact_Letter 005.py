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
    "Rentoul",
    "Lee Rentoul",
    "Nic",
    "Nicole Arriaga",
    "Chronicles",
    "Chronicle",
    "a schizophre",
    "schizophre",
    "schizophrenic",
    "titanic",
    "titan",

    "shell exhibit",
    "Aquarium",
    "aquarium",
    "Magnus Archives",
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
