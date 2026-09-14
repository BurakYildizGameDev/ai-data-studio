"""Rewrite README.md for the PyPI project page, in place.

PyPI renders the README without the repository around it, so relative image paths,
links to other files and in-page anchors break there. The release workflow runs this
on its own checkout just before building; the README in the repository keeps its
relative links, which GitHub renders correctly.

Usage: python .github/scripts/pypi_readme.py <git-ref>   (e.g. v2.0.0)
"""
import re
import sys
from pathlib import Path

REPO = "BurakYildizGameDev/ai-data-studio"
IMAGE_SUFFIXES = (".png", ".gif", ".jpg", ".jpeg", ".svg", ".mp4")


def absolute(target: str, ref: str) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("//"):
        return target
    if target.startswith("#"):
        return "https://github.com/%s/blob/%s/README.md%s" % (REPO, ref, target)
    path = target.lstrip("./")
    if path.split("#")[0].lower().endswith(IMAGE_SUFFIXES):
        return "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, ref, path)
    return "https://github.com/%s/blob/%s/%s" % (REPO, ref, path)


def rewrite_prose(text: str, ref: str) -> str:
    # Markdown links and images: [text](target) / ![alt](target)
    text = re.sub(r"(\]\()([^)\s]+)(\))",
                  lambda m: m.group(1) + absolute(m.group(2), ref) + m.group(3), text)
    # HTML attributes: src="..." / href="..."
    text = re.sub(r'((?:src|href)=")([^"]+)(")',
                  lambda m: m.group(1) + absolute(m.group(2), ref) + m.group(3), text)
    return text


def rewrite(text: str, ref: str) -> str:
    """Rewrites links outside fenced code blocks only; code stays byte-for-byte."""
    parts = re.split(r"(^```.*?^```[^\n]*$)", text, flags=re.MULTILINE | re.DOTALL)
    return "".join(part if part.startswith("```") else rewrite_prose(part, ref)
                   for part in parts)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    readme = Path(__file__).resolve().parents[2] / "README.md"
    original = readme.read_text(encoding="utf-8")
    updated = rewrite(original, sys.argv[1])
    readme.write_text(updated, encoding="utf-8")
    changed = sum(1 for a, b in zip(original.splitlines(), updated.splitlines()) if a != b)
    print("README.md: %d lines rewritten for PyPI (ref %s)" % (changed, sys.argv[1]))


if __name__ == "__main__":
    main()
