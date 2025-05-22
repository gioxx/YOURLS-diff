# YOURLS Diff

[Readme file is also available in italian](README_IT.md).

**YOURLS Diff** is a Python script that simplifies updating a YOURLS installation via FTP by creating a ZIP package containing only the new or modified files between two release tags.

If you want to take advantage of the patches that are automatically created by this script and this repository (via [this GitHub Action](.github/workflows/patch.yml)), you can take a look at [Releases](https://github.com/gioxx/YOURLS-diff/releases). The most recent update package will always be available by pointing to the [Latest tag](https://github.com/gioxx/YOURLS-diff/releases/latest). The script runs every day at midnight.

## Features

- Automatically downloads the two ZIP archives (`old` and `new`) from the YOURLS GitHub repository.  
- Compares files and identifies **new** or **modified** ones.  
- Generates a ZIP package containing only the changed files.  
- Produces an external manifest file (`.txt`) listing the changed files.  
- Generates a bash script that allows you to update your YOURLS instance via rsync and SSH.  
- Supports SSL certificate verification with an option to disable it.

## Requirements

- Python **3.6+**  
- Python libraries listed in `requirements.txt`:
  ```txt
  requests>=2.20.0
  urllib3>=1.25.0
  ```

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/gioxx/YOURLS-diff.git
   cd YOURLS-diff
   ```

2. Create a virtual environment (optional but recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/MacOS
   .\.venv\Scripts\activate  # Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

The main script is called `YOURLS-diff_CreatePackage.py` and accepts the following options:

| Option         | Description                                                              | Example                              |
|----------------|--------------------------------------------------------------------------|--------------------------------------|
| `--old`        | **(required)** Tag of the starting release (e.g., `1.8.10`).             | `--old 1.8.10`                       |
| `--new`        | Tag of the target release. If omitted, `latest` is used.                 | `--new 1.9.0`                        |
| `--output`     | Output ZIP filename. Default: `YOURLS-update-OLD-to-NEW.zip`.            | `--output diff.zip`                  |
| `--no-verify`  | Disable SSL certificate verification (not recommended).                  | `--no-verify`                        |
| `--summary`    | Generate a summary text file with patch details.                         | `--summary`                          |

### Examples

- **Update from 1.8.10 to the latest release**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10
  ```
  Produces:
  - `YOURLS-update-1.8.10-to-<latest>.zip`  
  - `YOURLS-update-1.8.10-to-<latest>.txt` (manifest)

- **Update from 1.8.10 to 1.9.0 with a custom output name**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --new 1.9.0 --output update.zip
  ```

- **Disable SSL verification**:
  ```bash
  python YOURLS-diff_CreatePackage.py --old 1.8.10 --no-verify
  ```

## Repository Structure

```text
├── YOURLS-diff_CreatePackage.py   # Main Python script
├── requirements.txt               # Python dependencies
├── LICENSE                        # License used for this repository
├── README.md                      # This documentation
└── README_IT.md                   # Italian documentation
```

## Contributing

Pull requests and issue reports are welcome! Please open a new issue for bugs or feature requests.
