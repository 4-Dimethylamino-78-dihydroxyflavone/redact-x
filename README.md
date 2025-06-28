# Redactor X - 2025-06-28-1342

`redact_unified.py` provides both a graphical and command-line interface for redacting PDF files. This enhanced version includes OCR support for scanned PDFs, preset workflows, improved zoom controls, and comprehensive testing.

## Features

### Core Features
- Interactive GUI built with Tkinter to mark rectangular areas for redaction
- Support for lists of keyword and passage patterns to automatically search and redact text
- Exclusion list (keywords and passages) to prevent redaction of matching strings
- Autosaves region selections and configurations to timestamped JSON files
- Resizable panes with zoomable PDF viewer
- Pane sizes are remembered between sessions
- Preview updates live as you edit patterns or exclusions
- Command-line interface to apply saved settings without launching the GUI
- Right-click an existing region to delete it or toggle between redaction and protection
- Global keyboard shortcuts (Ctrl+Z/Ctrl+Y) work regardless of focus

### New Features
- **OCR Support**: Automatically detect and process scanned PDFs using Tesseract OCR
- **Preset Workflows**: Built-in presets for common redaction tasks:
  - Personal Information (SSN, phone numbers, emails)
  - Financial Data (credit cards, account numbers)
  - Medical Records (patient info, diagnoses)
  - Legal Documents (case numbers, privileged info)
- **Regex Pattern Support**: Advanced pattern matching using regular expressions
- **Enhanced Zoom Controls**: Fixed Ctrl+MouseWheel zoom with multiple key binding support
- **Improved Error Handling**: Graceful degradation when optional features unavailable
- **Standalone Executable**: Build script for creating distributable executables
- **Comprehensive Testing**: Extended unit test coverage for all components

### Needed Features
The latest version implements several of these requested features:
- **Flexible Polygon**: New polygon drawing mode lets you freehand-draw redaction or protection areas.
- **More Supported Filetypes**: The CLI and GUI now accept common image formats and DOC/DOCX files. Image conversion to PDF is optional via a new flag/checkbox.
- **Optional metadata scrubbing**: A new checkbox and CLI flag remove document metadata when exporting.
  
### Patterns vs Exclusions

Patterns define text you want to redact. Exclusions hold keywords or passages that should never be removed. When both match, the exclusion wins so the text is preserved. Use protected regions to completely block pattern matches within those areas.

## Installation

### Basic Installation

Install the required packages using pip:

```bash
pip install pymupdf Pillow
```

### Full Installation (with OCR)

For OCR support with scanned PDFs:

```bash
pip install pymupdf Pillow pytesseract opencv-python numpy
```

You'll also need to install Tesseract OCR:
- **Windows**: Download installer from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
- **macOS**: `brew install tesseract`
- **Linux**: `sudo apt-get install tesseract-ocr`

### Development Installation

For development with testing and building capabilities:

```bash
pip install -r requirements.txt
pip install pytest pytest-cov pytest-mock pyinstaller
```

## Usage

### Launch the GUI

Run the script without arguments or with the `--gui` flag:

```bash
python redact_unified.py --gui
```

Use the GUI to open a PDF, draw boxes over regions to redact, manage keywords and passage lists, then choose **Save Redacted** to export a new PDF.

### Controls

- **Space**: Pan mode - click and drag to move around the PDF
- **T**: Text selection tool - select text to add to patterns/exclusions
- **R**: Draw redaction rectangles (areas to black out)
- **P**: Draw protection rectangles (areas to preserve)
- **Ctrl+Mouse Wheel** or **Ctrl+/Ctrl-** or **Ctrl+Plus/Minus**: Zoom in and out
- **Ctrl+0**: Reset zoom to 100%
- **Ctrl+Z/Ctrl+Y**: Undo/redo region changes
- **Left/Right Arrow**: Navigate between pages
- **Delete**: Remove selected region in Regions tab
- **Preview** checkbox: See redactions applied live
- **Use OCR** checkbox: Enable OCR for scanned PDFs (when available)
- **Convert Images** checkbox: Convert opened images to PDF for processing

### Using Presets

1. Open the **Presets** menu and select a preset (e.g., "Personal Information")
2. The preset's patterns and regex rules will be loaded automatically
3. Adjust as needed and apply to your PDF
4. Save your customized settings as a new preset via "Save Current as Preset..."

### Command Line Interface

Apply redactions using saved settings:

```bash
python redact_unified.py input.pdf output.pdf
```

With specific configuration files:

```bash
python redact_unified.py input.pdf output.pdf \
    --patterns custom_patterns.json \
    --exclusions custom_exclusions.json \
    --regions sample_regions.json
```

Apply a preset from command line:

```bash
python redact_unified.py input.pdf output.pdf --preset "Personal Information"
```

Enable OCR for scanned PDFs:

```bash
python redact_unified.py input.pdf output.pdf --ocr
```

Convert images to PDF before processing:

```bash
python redact_unified.py input.jpg output.pdf --convert-images
```

## Configuration Files

The application stores configurations in a data folder named after the script:

- **Patterns**: Keywords and passages to search for and redact
- **Exclusions**: Keywords and passages that should never be redacted
- **Regions**: Manually drawn rectangles for redaction or protection
- **Presets**: Saved combinations of patterns and settings

### Pattern File Format

```json
{
  "keywords": ["confidential", "secret", "private"],
  "passages": [
    "This entire paragraph should be redacted",
    "Another passage to remove"
  ]
}
```

### Exclusion File Format

```json
{
  "keywords": ["public", "released"],
  "passages": [
    "This text should never be redacted even if it contains keywords"
  ]
}
```

### Custom Preset Format

```json
{
  "name": "My Custom Preset",
  "description": "Redacts specific business information",
  "patterns": {
    "keywords": ["proprietary", "trade secret"],
    "passages": []
  },
  "regex_patterns": [
    "Project\\s+[A-Z]{2,4}-\\d{4}",
    "Serial\\s*#\\s*\\d{6,}"
  ]
}
```

## Building Standalone Executable

To create a distributable executable:

```bash
python build_standalone.py
```

This creates a `Redactor-X_Distribution` folder containing:
- Single executable file (no Python required)
- README documentation
- Launch script for easy execution

To clean build artifacts:

```bash
python build_standalone.py clean
```

## Testing

Run the test suite:

```bash
# Basic tests
python -m pytest tests/

# With coverage report
python -m pytest tests/ --cov=redact_unified --cov-report=html

# Specific test file
python -m unittest tests.test_redact_unified
```

## OCR Tips

- The application automatically detects scanned PDFs and enables OCR
- OCR processing may be slow for large documents
- For best results, ensure scanned pages are:
  - High resolution (300 DPI or higher)
  - Well-aligned and not skewed
  - Good contrast between text and background
- OCR accuracy varies with document quality

## Troubleshooting

### Zoom shortcuts not working
- Ensure the main window has focus
- Try different key combinations: Ctrl+Plus, Ctrl+Equal, Ctrl+MouseWheel
- On some systems, use Cmd instead of Ctrl

### OCR not available
- Install pytesseract: `pip install pytesseract opencv-python`
- Install Tesseract OCR system package
- Check that `tesseract` command works from terminal

### Large file performance
- Disable preview mode while editing
- Process one page at a time for very large PDFs
- Consider using command-line mode for batch processing

## Privacy and Security

- All processing happens locally on your machine
- No data is sent to external servers
- Configurations are stored in local JSON files
- Be careful when sharing configuration files as they may contain sensitive patterns

## Contributing

Contributions are welcome! Areas for improvement:

- Additional preset templates
- Enhanced OCR accuracy with preprocessing options
- Support for more file formats
- Batch processing improvements
- UI/UX enhancements

## License

This project is provided as-is for educational and personal use. Please ensure you have the right to redact any documents you process.
