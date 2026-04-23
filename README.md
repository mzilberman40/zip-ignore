# zip-ignore

A straightforward command-line tool to create a ZIP archive of your project directory while strictly respecting `.zipignore` (or `.gitignore` style) exclusion patterns.

## Features
- Uses standard `gitwildmatch` semantics for ignore patterns.
- Automatically prevents the output archive from including itself.
- Cross-platform path handling.

## Installation

The recommended way to install this tool globally without polluting your system Python environment is using [pipx](https://pypa.github.io/pipx/):

```bash
pipx install git+[https://github.com/YOUR_USERNAME/zip-ignore.git](https://github.com/YOUR_USERNAME/zip-ignore.git)