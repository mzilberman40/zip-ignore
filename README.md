# zip-ignore

`zip-ignore` creates a ZIP archive from a project directory while honoring gitignore-style exclusion rules from a `.zipignore` file.

It is useful when you want to share a project snapshot without bundling virtual environments, caches, local editor files, build outputs, or other artifacts.

## Features

- Uses `pathspec` with gitignore-style matching.
- Supports negation patterns such as `!build/keep.txt`.
- Automatically avoids adding the output archive into itself.
- Works with relative or absolute paths on Windows, macOS, and Linux.

## Installation

Install from the repository with `pipx`:

```bash
pipx install git+https://github.com/mzilberman40/zip-ignore.git
```

Or install locally for development:

```bash
python -m pip install .
```

## Windows 11: Use From Anywhere

If you want to run `zip-ignore` from any PowerShell window, install it as a command-line tool.

Recommended with `pipx`:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Close and reopen PowerShell, then install `zip-ignore` from the project folder:

```powershell
pipx install .
```

After that, the command should work from anywhere:

```powershell
zip-ignore --help
zip-ignore C:\Projects\MyApp -o C:\Archives\MyApp.zip
```

Alternative with `pip --user`:

```powershell
py -m pip install --user .
```

If `zip-ignore` is still not recognized, add your user Python `Scripts` directory to `PATH`, then reopen PowerShell. A typical path looks like:

```text
C:\Users\<YourUser>\AppData\Roaming\Python\Python313\Scripts
```

## Usage

```bash
zip-ignore [ROOT] [-o OUTPUT] [-i IGNOREFILE]
```

Examples:

```bash
zip-ignore
zip-ignore . -o release.zip
zip-ignore ./my-project -o ../artifacts/my-project.zip
zip-ignore . -i .gitignore -o source-only.zip
```

## `.zipignore` format

The ignore file uses gitignore-style patterns.

Example:

```gitignore
# VCS
.git/

# Python
__pycache__/
.venv/
*.pyc

# Build output
build/
dist/

# Keep one generated file
!build/keep.txt
```

Empty lines and lines starting with `#` are ignored.

## Development

Run the test suite with:

```bash
python -m unittest discover -s tests
```

## License

MIT. See [LICENSE](LICENSE).
