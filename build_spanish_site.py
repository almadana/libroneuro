#!/usr/bin/env python3
"""Construye la edición progresiva en español a partir de traducciones revisables."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
SOURCE_SITE = ROOT / "site"
OUTPUT_SITE = ROOT / "site-es"
TRANSLATIONS = ROOT / "translations" / "es-rioplatense"
MANIFEST_PATH = TRANSLATIONS / "manifest.json"


def replace_contents(target, fragment_html: str) -> None:
    target.clear()
    fragment = BeautifulSoup(fragment_html, "html.parser")
    for child in list(fragment.contents):
        target.append(child.extract())


def translated_link_text(text: str, title: str) -> str:
    prefix = "← " if text.lstrip().startswith("←") else ""
    suffix = " →" if text.rstrip().endswith("→") else ""
    return f"{prefix}{title}{suffix}"


def main() -> int:
    if not SOURCE_SITE.exists():
        raise SystemExit("Falta site/. Ejecutá primero: python build_static_book.py")
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Falta el manifiesto de traducción: {MANIFEST_PATH}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pages: dict[str, dict[str, str]] = manifest["pages"]

    if OUTPUT_SITE.exists():
        shutil.rmtree(OUTPUT_SITE)
    shutil.copytree(SOURCE_SITE, OUTPUT_SITE)

    translated_text: dict[str, str] = {}
    for filename, info in pages.items():
        source_fragment = TRANSLATIONS / "pages" / filename
        output_page = OUTPUT_SITE / "pages" / filename
        if not source_fragment.exists():
            raise SystemExit(f"Falta la traducción: {source_fragment}")
        if not output_page.exists():
            raise SystemExit(f"La página original ya no existe: {output_page}")

        soup = BeautifulSoup(output_page.read_text(encoding="utf-8"), "html.parser")
        content = soup.select_one(".pressbooks-content")
        heading = soup.select_one("article > h1")
        if content is None or heading is None:
            raise SystemExit(f"Estructura inesperada en {output_page}")

        fragment_html = source_fragment.read_text(encoding="utf-8")
        replace_contents(content, fragment_html)
        heading.string = info["title"]
        soup.html["lang"] = "es-AR"
        if soup.title:
            soup.title.string = f'{info["title"]} — Psicología biológica'

        topbar = soup.select_one(".topbar > a")
        if topbar:
            topbar.string = "Psicología biológica — traducción local"

        footer = soup.select_one("footer")
        if footer:
            note = BeautifulSoup(
                "<p><strong>Traducción:</strong> adaptación al español rioplatense; "
                "no constituye una edición oficial ni implica el aval de los autores "
                "o de ROTEL.</p>",
                "html.parser",
            )
            footer.insert(0, note.p)

        output_page.write_text(str(soup), encoding="utf-8")
        translated_text[filename] = content.get_text(" ", strip=True)

    title_map = {filename: info["title"] for filename, info in pages.items()}
    for page in OUTPUT_SITE.rglob("*.html"):
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        changed = False
        for link in soup.find_all("a", href=True):
            basename = Path(urlparse(link["href"]).path).name
            if basename in title_map:
                link.string = translated_link_text(link.get_text(" ", strip=True), title_map[basename])
                changed = True
        if changed:
            page.write_text(str(soup), encoding="utf-8")

    index_path = OUTPUT_SITE / "index.html"
    index = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    index.html["lang"] = "es-AR"
    if index.title:
        index.title.string = manifest["book_title"]
    hero_title = index.select_one(".hero h1")
    hero_description = index.select_one(".hero h1 + p")
    if hero_title:
        hero_title.string = manifest["book_title"]
    if hero_description:
        hero_description.string = manifest["book_description"]
    hero_label = index.select_one(".hero p")
    if hero_label:
        hero_label.string = "Traducción progresiva al español rioplatense"
    hero_inner = index.select_one(".hero-inner > div")
    if hero_inner:
        status = index.new_tag("p")
        status["class"] = "translation-status"
        status.string = manifest["status"]
        hero_inner.append(status)
    index_footer = index.select_one("footer")
    if index_footer:
        translation_note = BeautifulSoup(
            "<p><strong>Traducción:</strong> adaptación progresiva al español "
            "rioplatense; no constituye una edición oficial ni implica el aval "
            "de los autores o de ROTEL.</p>",
            "html.parser",
        )
        index_footer.insert(0, translation_note.p)
    index_path.write_text(str(index), encoding="utf-8")

    search_path = OUTPUT_SITE / "search-index.json"
    search_index = json.loads(search_path.read_text(encoding="utf-8"))
    for entry in search_index:
        filename = entry["file"]
        if filename in title_map:
            entry["title"] = title_map[filename]
            entry["text"] = translated_text[filename]
    search_path.write_text(
        json.dumps(search_index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    build_info_path = OUTPUT_SITE / "build-info.json"
    build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    build_info["translation"] = {
        "locale": "es-AR",
        "translated_pages": len(pages),
        "status": manifest["status"],
        "guide": "GUIA_DE_TRADUCCION.md",
    }
    build_info_path.write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_SITE / ".nojekyll").touch()

    print(
        f"Edición progresiva generada en {OUTPUT_SITE}: "
        f"{len(pages)} páginas traducidas."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
