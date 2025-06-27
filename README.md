# Redact-X Unified PDF Redactor

This repository provides a single script `redact_unified.py` that combines a simple GUI and command line interface for redacting PDF files. Settings and region data are stored in a folder sharing the script name.

## Installation

```
pip install -r requirements.txt
```

## Usage

Launch the GUI:

```
python redact_unified.py --gui
```

Process a PDF via CLI:

```
python redact_unified.py input.pdf output.pdf
```

The GUI supports drawing redaction and protect regions, undo/redo, and saving patterns or exclusions. CLI mode automatically loads any saved configurations.
