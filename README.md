# zip-ignore

`zip-ignore` creates compact ZIP snapshots of a project for code review, AI-assisted work, and hand-offs.
It combines repository `.zipignore` rules with Git-aware file discovery, purpose-specific profiles, a hard guard against common secret files, an embedded snapshot manifest, and a size report.

By default, the archive is named after the project folder and creation time, for example:

```text
my-project_20260918_093620.zip
```

## The important idea: profiles do not replace `.zipignore`

Every profile still respects repository policy and safety rules.

In particular, **`full` does not mean “put every file from the directory into the ZIP”**. It means:

> use the normal candidate set and normal repository/safety filters, but do not add any built-in profile exclusions.

So with `--profile full`:

- Git-ignored files are still absent in a Git repository;
- `.zipignore` still applies;
- the hard secret guard still applies;
- symlinks are still skipped;
- `--exclude` still applies;
- the output ZIP cannot include itself;
- only the built-in profile exclusions are disabled.

For example, if `.zipignore` contains:

```gitignore
htmlcov/
```

then this command still excludes `htmlcov/`:

```powershell
zip-ignore . --profile full
```

If `htmlcov/` is **not** in `.zipignore`, `full` may include it because `full` does not apply the normal built-in generated-report exclusions.

`.zipignore` is required for every profile, including `full`. If you intentionally want no repository-specific `.zipignore` exclusions, point `-i` at an empty ignore file; Git and safety filtering still remain active.

## Profiles

A single “archive everything except caches” policy is a poor fit for review work. Architecture discussions rarely need the whole test suite, while implementation and security review often depend on tests.

| Profile | Candidate set | Built-in generated-artifact exclusions | Tests | `.zipignore` | Typical use |
|---|---|---:|---:|---:|---|
| `context` | Git tracked + non-ignored untracked files | Yes | Excluded by built-in profile | Yes | Architecture, orientation, design discussion |
| `review` | Git tracked + non-ignored untracked files | Yes | Included | Yes | Code review, debugging, implementation planning |
| `changed` | Staged + unstaged + non-ignored untracked changes only | Yes | Included when changed | Yes | Follow-up review after the baseline is already known |
| `full` | Git tracked + non-ignored untracked files | **No** | Included | **Yes** | Broad investigation where built-in filtering might hide useful files |

`review` is the default profile.

Outside a Git work tree, `context`, `review`, and `full` fall back to filesystem traversal. `changed` requires Git and fails rather than pretending it can determine changes without Git history/index state.

## Installation

Install from GitHub with `pipx`:

```bash
pipx install git+https://github.com/mzilberman40/zip-ignore.git
```

Or install locally for development:

```bash
python -m pip install .
```

### Updating

If installed from GitHub with `pipx`:

```bash
pipx upgrade zip-ignore
```

If installed from a local checkout:

```bash
pipx reinstall .
```

## Command line

```text
zip-ignore [ROOT]
           [-o OUTPUT]
           [-i IGNORE_FILE]
           [-p {context,review,changed,full}]
           [--include PATTERN]
           [--exclude PATTERN]
           [-v]
           [--version]
```

### Options

| Option | Default | Repeatable | Meaning |
|---|---|---:|---|
| `ROOT` | `.` | No | Project root to snapshot. |
| `-o OUTPUT`, `--output OUTPUT` | `<root>_YYYYMMDD_HHMMSS.zip` | No | Output ZIP path. Parent directories are created when necessary. |
| `-i IGNORE_FILE`, `--ignore-file IGNORE_FILE` | `.zipignore` | No | Gitignore-style repository exclusion file. A relative path is resolved relative to `ROOT`. The file must exist. Applies to **all profiles**, including `full`. |
| `-p PROFILE`, `--profile PROFILE` | `review` | No | Selects `context`, `review`, `changed`, or `full`. See the profile table above. |
| `--include PATTERN` | none | Yes | Re-includes a path excluded **only by the selected profile**. It cannot override Git ignore, `.zipignore`, `--exclude`, secret protection, or symlink protection. |
| `--exclude PATTERN` | none | Yes | Adds an extra gitignore-style exclusion for this invocation without editing `.zipignore`. Wins over `--include`. |
| `-v`, `--verbose` | off | No | Prints each file added to the archive. |
| `--version` | — | No | Prints the installed `zip-ignore` version and exits. |
| `-h`, `--help` | — | No | Prints CLI help and exits. |

`--include` and `--exclude` use gitignore-style matching and may be supplied multiple times.

## File-selection pipeline

The effective selection is intentionally layered. In simplified form:

```text
candidate discovery
    ↓
symlink guard
    ↓
hard secret guard
    ↓
.zipignore
    ↓
--exclude
    ↓
profile exclusions
    ↓
--include may undo profile exclusions only
    ↓
ZIP + SNAPSHOT_MANIFEST.txt
```

More precisely:

1. **Candidate discovery**
   - normal profile inside Git: tracked files + untracked files that are not Git-ignored;
   - `changed`: staged + unstaged + untracked/non-Git-ignored changed files;
   - outside Git: filesystem traversal.
2. **Output self-exclusion** — the ZIP being created cannot add itself.
3. **Symlink guard** — symlinks are skipped rather than dereferenced.
4. **Reserved manifest name** — a source file named `SNAPSHOT_MANIFEST.txt` is not copied over the generated manifest.
5. **Hard secret guard** — always wins.
6. **`.zipignore`** — always applies, including with `full`.
7. **`--exclude`** — always applies and wins over `--include`.
8. **Built-in profile exclusions** — applied by `context`, `review`, and `changed`; `full` has none.
9. **`--include` override** — may undo step 8 only.

This makes `--include` deliberately different from a dangerous “force include” switch.

## Git-aware behaviour

For `context`, `review`, and `full` inside a Git work tree, candidate discovery is equivalent in intent to:

```bash
git ls-files --cached --others --exclude-standard
```

This normally prevents Git-ignored virtual environments, dependency trees, caches, local reports, local archives, and other generated material from even becoming candidates, while still including new uncommitted source files.

Consequently, `--profile full` still does **not** restore a Git-ignored file. `--include` cannot restore it either, because the file never entered the candidate set.

The `changed` profile collects current staged, unstaged, and untracked/non-ignored paths. It is intended for a follow-up review when the reviewer already has the baseline. It does not automatically add unchanged surrounding source files.

## `.zipignore`

The ignore file uses gitignore-style patterns through `pathspec`.

Default location:

```text
ROOT/.zipignore
```

Example:

```gitignore
# VCS metadata when using filesystem fallback
.git/

# Python
__pycache__/
.venv/
*.pyc

# Generated reports
htmlcov/
coverage/

# Build output
build/
dist/
```

Useful repository metadata such as these should normally remain available unless there is a repository-specific reason to hide them:

```text
.gitignore
.zipignore
.dockerignore
pyproject.toml
package.json / lock files
Dockerfile / compose files
.github/workflows/
```

### `.gitignore` versus `.zipignore`

They serve different layers:

- `.gitignore` controls what untracked files Git considers ignored. Inside a Git repository, ignored untracked files are normally absent from the candidate set.
- `.zipignore` is a snapshot-specific policy applied after candidate discovery. It can exclude tracked files as well as otherwise eligible untracked files.

Therefore `.zipignore` is useful even when `.gitignore` is already well maintained.

## Built-in profile exclusions

`review` and `changed` automatically remove common low-value/generated content even if a repository forgot to put it in `.zipignore`, including categories such as:

```text
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
coverage/
.coverage*
coverage.xml
node_modules/
build/
dist/
*.egg-info/
.next/
.vite/
```

`context` adds common test-file/test-directory patterns on top of those exclusions.

`full` adds **none** of these built-in exclusions. Repository and safety exclusions still apply.

## `--include`

`--include` exists mainly for cases such as an architecture snapshot that needs one relevant test family:

```powershell
zip-ignore . --profile context --include "tests/test_browser_session.py"
```

It can override only a **profile** exclusion. For example:

- test excluded by `context` → `--include` can restore it;
- file excluded by `.zipignore` → cannot restore it;
- file excluded by `--exclude` → cannot restore it;
- Git-ignored untracked file → cannot restore it;
- secret → cannot restore it;
- symlink → cannot restore it.

Multiple patterns are allowed:

```powershell
zip-ignore . --profile context `
  --include "tests/test_auth.py" `
  --include "tests/test_permissions.py"
```

## `--exclude`

Use `--exclude` for one-off filtering without changing repository policy:

```powershell
zip-ignore . --profile review --exclude "tests/fixtures/**"
```

Multiple exclusions are allowed:

```powershell
zip-ignore . `
  --exclude "tests/fixtures/**" `
  --exclude "docs/generated/**"
```

`--exclude` wins over `--include`.

## Secret guard

The built-in guard is a safety net, not a secret scanner. It blocks common high-risk filenames/extensions but cannot prove that arbitrary source or configuration files contain no credentials.

Typical blocked paths include:

```text
.env
.env.local
.npmrc
.pypirc
.netrc
id_rsa
id_ed25519
*.pem
*.key
*.p12
*.pfx
.aws/credentials
.kube/config
.docker/config.json
credentials.json
*.tfvars
```

Template/sample variants ending in `.example`, `.sample`, `.template`, or `.dist` are allowed.

Neither `full` nor `--include` bypasses the secret guard.

## Symlinks

Symlinks are skipped for every profile. They are not dereferenced into the archive.

This prevents a harmless-looking repository path from silently copying content from elsewhere on the machine or from bypassing filename-based secret protection through indirection.

## Examples

### Default review snapshot

Tests remain included; common generated artefacts are omitted:

```powershell
zip-ignore .
```

Equivalent profile selection:

```powershell
zip-ignore . --profile review
```

### Architecture/design snapshot

```powershell
zip-ignore . --profile context
```

### Architecture snapshot with one relevant test

```powershell
zip-ignore . --profile context --include "tests/test_browser_session.py"
```

### Follow-up snapshot with only current Git changes

```powershell
zip-ignore . --profile changed
```

### Review snapshot with a temporary extra exclusion

```powershell
zip-ignore . --profile review --exclude "tests/fixtures/**"
```

### Broad snapshot without built-in profile filtering

```powershell
zip-ignore . --profile full
```

Remember: this still respects Git ignore, `.zipignore`, safety guards, and `--exclude`.

### Use another ignore file

```powershell
zip-ignore . --ignore-file .zipignore-ai
```

### Choose the output path

```powershell
zip-ignore . --profile context --output ..\snapshots\bas-context.zip
```

### Show every included file

```powershell
zip-ignore . --verbose
```

## Snapshot manifest

Every archive contains `SNAPSHOT_MANIFEST.txt` with snapshot provenance and selection information, for example:

```text
zip-ignore snapshot manifest
tool_version: 0.2.1
created_utc: 2026-09-18T06:36:20Z
repository: biocompass-auth
profile: review
selection_mode: git-tracked+untracked
included_files: 184
included_source_bytes: 1864200
git:
  branch: main
  head: <commit SHA>
  worktree: modified
  status_short:
    M app/views.py
files:
  .gitignore
  README.md
  ...
```

The manifest deliberately contains no absolute local project path.

## Size report

After creating an archive, `zip-ignore` prints a summary containing:

- profile and selection mode;
- source file count and uncompressed source size;
- archive size and compression ratio;
- skipped-file counts by reason where available;
- largest top-level groups;
- largest files.

This helps identify why a repository snapshot is unexpectedly large without opening the ZIP manually.

## Development

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
