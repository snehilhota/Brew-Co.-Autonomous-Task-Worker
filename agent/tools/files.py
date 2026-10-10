"""Read-only file tools confined to the environment's document root."""

from pathlib import Path


class FileTools:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escapes the configured file root.") from exc
        if not candidate.is_file() and not candidate.is_dir():
            raise FileNotFoundError(f"No file or directory at {relative!r}.")
        return candidate

    def list_files(self, dir: str = ".") -> str:
        folder = self._safe_path(dir)
        if not folder.is_dir():
            raise ValueError("dir must refer to a directory.")
        rows = []
        for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
            if path.is_symlink():
                continue
            size = path.stat().st_size if path.is_file() else 0
            name = path.relative_to(self.root).as_posix()
            if path.is_dir():
                name += "/"
            rows.append(f"{name} ({size} bytes)")
        return "\n".join(rows) or "(empty directory)"

    def read_file(self, path: str, offset: int = 0) -> str:
        target = self._safe_path(path)
        if not target.is_file():
            raise ValueError("path must refer to a file.")
        if offset < 0:
            raise ValueError("offset must be zero or greater.")
        text = target.read_text(encoding="utf-8")
        chunk = text[offset:offset + 6000]
        ending = f"\n[more at offset {offset + len(chunk)}]" if offset + len(chunk) < len(text) else ""
        return chunk + ending

    def search_files(self, query: str, dir: str = ".") -> str:
        folder = self._safe_path(dir)
        files = [folder] if folder.is_file() else folder.rglob("*")
        hits = []
        for path in files:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(lines, start=1):
                if query.casefold() in line.casefold():
                    hits.append(f"{path.relative_to(self.root).as_posix()}:{number}: {line[:500]}")
                    if len(hits) >= 100:
                        return "\n".join(hits) + "\n[results capped at 100]"
        return "\n".join(hits) or "No matching lines."

