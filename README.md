# Redact X

`redact_unified.py` provides both a graphical and command-line interface for redacting PDF files. It consolidates earlier scripts into a single executable while storing its configuration in a data folder named after the script.

## Features

- Interactive GUI built with Tkinter to mark rectangular areas for redaction
- Support for lists of keyword and passage patterns to automatically search and redact text
- Exclusion list to prevent redaction of matching strings
- Autosaves region selections and configurations to timestamped JSON files
- Command-line interface to apply saved settings without launching the GUI

## Installation

Install the required packages using pip:

```bash
pip install pymupdf Pillow
```

Alternatively install from the provided requirements file:

```bash
pip install -r requirements.txt
```

## Usage

### Launch the GUI

Run the script without arguments or with the `--gui` flag:

```bash
python redact_unified.py --gui
```

Use the GUI to open a PDF, draw boxes over regions to redact, manage keywords and passage lists, then choose **Save Redacted** to export a new PDF.

### Command line

Apply redactions using saved settings:

```bash
python redact_unified.py input.pdf output.pdf
```

The script loads the most recent patterns, exclusions and region selections from its data folder and writes the redacted PDF to the specified output location.

