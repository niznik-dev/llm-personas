#!/usr/bin/env python3
"""Soft-link the built personas and roles into your AI tools' user directories.

By default this looks in your home directory for the config directories of
common AI tools (~/.claude, ~/.codex, ...) and, in each one it finds, links
every generated persona file and every role file there:

    <tool dir>/personas/<name>.md  ->  <this repo>/personas/<name>/<name>.md
    <tool dir>/personas/<role>.md  ->  <this repo>/roles/<role>.md

Persona and role names never overlap (bram.md vs slate.md), so both tiers
share one flat folder. Use --no-roles for personas only, or --roles-only for
the plain roles without the backstory.

Because these are symlinks, a `git pull` plus `python build.py` updates every
install at once. Tool directories that don't exist are never created.

Pass --dir to skip the search and link straight into a directory of your
choosing (created if needed): <DIR>/<name>.md. It can be repeated.

Existing files are never overwritten unless you pass --force. Run
`python build.py` first if a persona's generated .md is missing.
"""

import argparse
import errno
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PERSONAS = ROOT / "personas"
ROLES = ROOT / "roles"

# AI tool user directories, relative to $HOME. Only ones that already exist
# are used; personas go in a "personas" subdirectory of each.
TOOL_DIRS = (
    ".claude",
    ".codex",
    ".gemini",
    ".cursor",
    ".copilot",
    ".continue",
    ".codeium/windsurf",
    ".config/opencode",
    ".config/goose",
)


def find_persona_files() -> tuple[list[Path], list[str]]:
    """Return (generated persona files, names whose .md hasn't been built)."""
    found, unbuilt = [], []
    for char in sorted(PERSONAS.glob("*/character.md")):
        name = char.parent.name
        built = char.parent / f"{name}.md"
        if built.exists():
            found.append(built)
        else:
            unbuilt.append(name)
    return found, unbuilt


def find_role_files() -> list[Path]:
    """Return the role files; each is a complete prompt with no build step."""
    return sorted(ROLES.glob("*.md"))


def detect_tool_dirs(home: Path) -> list[Path]:
    """Return the "personas" install dir for each AI tool dir present in home."""
    return [home / d / "personas" for d in TOOL_DIRS if (home / d).is_dir()]


def check_dest_dir(dest_dir: Path) -> None:
    """Raise OSError if dest_dir can't be created or used as a directory.

    Walks up to the nearest existing ancestor without creating anything, so a
    dry run reports the same blockers (a regular file in the way) as a real run.
    """
    for path in (dest_dir, *dest_dir.parents):
        if path.is_dir():
            return
        if path.exists() or path.is_symlink():  # a file or a broken link
            raise NotADirectoryError(errno.ENOTDIR, "Not a directory", str(path))


def replace_with_link(link: Path, source: Path) -> None:
    """Replace link with a symlink to source without a window for data loss.

    The new symlink is built under a temporary name beside the old file and
    renamed over it, so if creating it fails the original is left untouched.
    """
    tmp = link.with_name(f".{link.name}.tmp-{os.getpid()}")
    tmp.unlink(missing_ok=True)
    try:
        tmp.symlink_to(source)
        os.replace(tmp, link)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def link_file(source: Path, dest_dir: Path, *, force: bool, dry_run: bool) -> str:
    """Link dest_dir/<source name> to source. Return a status for reporting.

    Statuses: "linked", "relinked", "ok" (already correct), or "skipped"
    (something else is in the way and --force wasn't given).
    """
    link = dest_dir / source.name
    status = "linked"
    if link.is_symlink() or link.exists():
        if link.resolve() == source.resolve():
            return "ok"
        # Never delete a real directory, even with --force.
        if not force or (link.is_dir() and not link.is_symlink()):
            return "skipped"
        status = "relinked"
    if dry_run:
        check_dest_dir(dest_dir)
    elif status == "relinked":
        replace_with_link(link, source)
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        link.symlink_to(source)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Soft-link built personas into your AI tools' user directories."
    )
    parser.add_argument(
        "--dir",
        "-d",
        action="append",
        type=Path,
        metavar="DIR",
        help="link personas directly into DIR instead of searching for AI tool "
        "directories (created if missing; repeatable)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="replace existing files or links that are in the way",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="show what would happen without changing anything",
    )
    tiers = parser.add_mutually_exclusive_group()
    tiers.add_argument(
        "--no-roles",
        action="store_true",
        help="link only the personas, not the plain roles",
    )
    tiers.add_argument(
        "--roles-only",
        action="store_true",
        help="link only the plain roles, not the personas",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, home: Path | None = None) -> int:
    args = parse_args(argv)
    home = home or Path.home()

    sources: list[Path] = []
    if not args.roles_only:
        personas, unbuilt = find_persona_files()
        for name in unbuilt:
            print(
                f"warning: personas/{name}/{name}.md not built; run `python build.py`"
            )
        sources += personas
    if not args.no_roles:
        sources += find_role_files()
    if not sources:
        print("No persona or role files found; run `python build.py` first.")
        return 1

    if args.dir:
        targets = [d.expanduser().absolute() for d in args.dir]
    else:
        targets = detect_tool_dirs(home)
        if not targets:
            print(f"No AI tool directories found in {home}. Use --dir to pick one.")
            return 1

    skipped = 0
    prefix = "[dry run] " if args.dry_run else ""
    for target in targets:
        print(f"{prefix}{target}")
        for source in sources:
            try:
                status = link_file(
                    source, target, force=args.force, dry_run=args.dry_run
                )
            except OSError as exc:
                skipped += 1
                print(f"  failed    {source.name}: {exc}")
                continue
            if status == "skipped":
                skipped += 1
                print(f"  skipped   {source.name} (already exists; use --force)")
            else:
                print(f"  {status:<9} {source.name}")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
