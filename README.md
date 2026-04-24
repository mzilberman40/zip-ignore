# zip-ignore

`zip-ignore` creates a ZIP archive from a project directory while honoring gitignore-style exclusion rules from a `.zipignore` file.

It is useful when you want to share a project snapshot without bundling virtual environments, caches, local editor files, build outputs, or other artifacts.

## Features

- Uses `pathspec` with gitignore-style matching.
- Supports negation patterns such as `!build/keep.txt`.
- Automatically avoids adding the output archive into itself.
- Works with relative or absolute paths on Windows, macOS, and Linux.
- Prunes ignored folders during traversal when it is safe to do so without breaking negation patterns.
- Handles files with pre-1980 timestamps without crashing.

## Installation

Install from the repository with `pipx`:

```bash
pipx install git+https://github.com/mzilberman40/zip-ignore.git
```

Or install locally for development:

```bash
python -m pip install .
```

## Updating

If you installed `zip-ignore` from GitHub with `pipx`, update it with:

```bash
pipx upgrade zip-ignore
```

`pipx upgrade` only sees a new release when the package version changes. If the installed version and the source version are both `0.1.0`, `pipx` will report that you are already on the latest version even if the code changed.

If you installed from the local project directory instead, reinstall from that directory after making changes:

```bash
pipx reinstall .
```

If you installed with `pip --user`, update from the project directory with:

```bash
py -m pip install --user --upgrade .
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
zip-ignore [ROOT] [-o OUTPUT] [-i IGNORE_FILE] [-v]
```

Examples:

```bash
zip-ignore
zip-ignore . -o release.zip
zip-ignore ./my-project -o ../artifacts/my-project.zip
zip-ignore . -i .gitignore -o source-only.zip
zip-ignore . -v  # verbose mode: prints added files to stdout
```

## `.zipignore` format

The ignore file uses gitignore-style patterns.

The ignore file must exist. By default, `zip-ignore` expects a `.zipignore` file in the project root; use `-i` to point at a different existing ignore file such as `.gitignore`.

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

Empty lines are ignored. Lines that start with `#` are treated as comments unless the `#` is escaped, matching normal `.gitignore` behavior.

## Development

Run the test suite with:

```bash
python -m unittest discover -s tests
```

## License

MIT. See [LICENSE](LICENSE).
