"""Inject Paply Chinese localization into LiteLLM's compiled admin UI."""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile

UI_ROOT = Path(
    "/app/.venv/lib/python3.13/site-packages/litellm/proxy/_experimental/out"
)
SCRIPT_SOURCE = Path("/tmp/paply-zh.js")
STYLE_SOURCE = Path("/tmp/paply-theme.css")
LOGO_SOURCE = Path("/tmp/paplyai-logo.png")
SCRIPT_TAG = '<script src="/ui/paply-zh.js"></script>'
STYLE_TAG = '<link rel="stylesheet" href="/ui/paply-theme.css">'


def main() -> None:
    if not UI_ROOT.is_dir():
        raise RuntimeError(f"LiteLLM UI directory is missing: {UI_ROOT}")
    if not all(
        source.is_file() for source in (SCRIPT_SOURCE, STYLE_SOURCE, LOGO_SOURCE)
    ):
        raise RuntimeError("Paply UI localization assets are missing")

    html_files = sorted(UI_ROOT.rglob("*.html"))
    if not html_files:
        raise RuntimeError("No LiteLLM UI HTML files were found")

    copyfile(SCRIPT_SOURCE, UI_ROOT / "paply-zh.js")
    copyfile(STYLE_SOURCE, UI_ROOT / "paply-theme.css")
    copyfile(LOGO_SOURCE, UI_ROOT / "paplyai-logo.png")

    for html_file in html_files:
        source = html_file.read_text(encoding="utf-8")
        if "</head>" not in source or "</body>" not in source:
            raise RuntimeError(f"Unexpected LiteLLM HTML structure: {html_file}")

        localized = source.replace('<html lang="en">', '<html lang="zh-CN">')
        localized = localized.replace(
            "<title>LiteLLM Dashboard</title>",
            "<title>PaplyAI 模型网关管理台</title>",
        )
        localized = localized.replace(
            '<meta name="description" content="LiteLLM Proxy Admin UI"/>',
            '<meta name="description" content="PaplyAI 模型网关管理台"/>',
        )
        localized = localized.replace("</head>", f"{STYLE_TAG}</head>", 1)
        localized = localized.replace("</body>", f"{SCRIPT_TAG}</body>", 1)
        html_file.write_text(localized, encoding="utf-8")

    print(f"Localized {len(html_files)} LiteLLM UI pages for PaplyAI")


if __name__ == "__main__":
    main()
