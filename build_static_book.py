#!/usr/bin/env python3
"""Genera una copia estática local de Biological Psychology (Pressbooks)."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SOURCE_URL = "https://rotel.pressbooks.pub/biologicalpsychology/"
API_BASE = urljoin(SOURCE_URL, "wp-json/pressbooks/v2/")
JINA_PREFIX = "https://r.jina.ai/"
OUTPUT_DIR = Path(__file__).resolve().parent / "site"
MEDIA_DIR = OUTPUT_DIR / "assets" / "media"
TIMEOUT = 60


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/140 Safari/537.36 StaticPressbooksMirror/1.0"
            )
        }
    )
    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


SESSION = make_session()


def get_api_json(endpoint: str) -> Any:
    """Obtiene JSON directamente y usa el lector de Jina como respaldo."""
    url = urljoin(API_BASE, endpoint)
    response = SESSION.get(url, timeout=TIMEOUT)
    if response.ok and "json" in response.headers.get("content-type", ""):
        return response.json()

    proxy = SESSION.get(f"{JINA_PREFIX}{url}", timeout=TIMEOUT)
    proxy.raise_for_status()
    text = proxy.text
    marker = "Markdown Content:"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"No se pudo interpretar la respuesta de {url}") from exc


def rendered(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("rendered") or field.get("raw") or "")
    return str(field or "")


def safe_slug(value: str, fallback: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return value or fallback


def srcset_best(value: str) -> str:
    candidates = [part.strip().split()[0] for part in value.split(",") if part.strip()]
    return candidates[-1] if candidates else ""


def media_urls(content: str, page_url: str) -> set[str]:
    soup = BeautifulSoup(content, "html.parser")
    found: set[str] = set()
    for tag in soup.find_all("img"):
        candidate = srcset_best(tag.get("srcset", "")) or tag.get("data-src") or tag.get("src")
        if candidate:
            absolute = urljoin(page_url, candidate)
            if urlparse(absolute).scheme in {"http", "https"}:
                found.add(absolute)
    for tag in soup.find_all(["video", "audio", "source"]):
        candidate = tag.get("src")
        if candidate:
            absolute = urljoin(page_url, candidate)
            if urlparse(absolute).scheme in {"http", "https"}:
                found.add(absolute)
        poster = tag.get("poster")
        if poster:
            absolute = urljoin(page_url, poster)
            if urlparse(absolute).scheme in {"http", "https"}:
                found.add(absolute)
    return found


def extension_for(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,6}", suffix):
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
    return guessed or ".bin"


def download_media(url: str) -> tuple[str, str | None, str | None]:
    """Devuelve URL original, ruta relativa descargada y posible error."""
    try:
        response = SESSION.get(url, timeout=TIMEOUT)
        content_type = response.headers.get("content-type", "")
        if not response.ok or "text/html" in content_type:
            proxy_url = "https://images.weserv.nl/?url=" + quote(url, safe="")
            response = SESSION.get(proxy_url, timeout=TIMEOUT)
            content_type = response.headers.get("content-type", "")
        response.raise_for_status()
        if "text/html" in content_type:
            raise RuntimeError(f"contenido inesperado: {content_type}")

        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        original_name = safe_slug(Path(urlparse(url).path).stem, "recurso")[:60]
        filename = f"{digest}-{original_name}{extension_for(url, content_type)}"
        target = MEDIA_DIR / filename
        target.write_bytes(response.content)
        return url, f"assets/media/{filename}", None
    except Exception as exc:  # conserva el recurso remoto si no puede descargarse
        return url, None, str(exc)


def normalize_path(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path or "/"


def rewrite_content(
    content: str,
    page_url: str,
    media_map: dict[str, str],
    page_map: dict[str, str],
) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for unwanted in soup.find_all("script"):
        unwanted.decompose()

    for tag in soup.find_all("img"):
        candidate = srcset_best(tag.get("srcset", "")) or tag.get("data-src") or tag.get("src")
        if candidate:
            absolute = urljoin(page_url, candidate)
            if absolute in media_map:
                tag["src"] = "../" + media_map[absolute]
        tag.attrs.pop("srcset", None)
        tag.attrs.pop("data-src", None)
        tag["loading"] = "lazy"

    for tag in soup.find_all(["video", "audio", "source"]):
        for attribute in ("src", "poster"):
            if tag.get(attribute):
                absolute = urljoin(page_url, tag[attribute])
                if absolute in media_map:
                    tag[attribute] = "../" + media_map[absolute]

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        destination = page_map.get(normalize_path(absolute))
        if destination:
            link["href"] = destination + (f"#{parsed.fragment}" if parsed.fragment else "")
        elif absolute in media_map:
            link["href"] = "../" + media_map[absolute]
        elif parsed.scheme in {"http", "https"}:
            link["rel"] = "noopener"

    return str(soup)


def extract_cover(metadata: dict[str, Any]) -> str | None:
    image = metadata.get("image")
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        return image.get("url") or image.get("@id")
    if isinstance(image, list) and image:
        first = image[0]
        return first if isinstance(first, str) else first.get("url")
    return None


def page_title(item: dict[str, Any]) -> str:
    return BeautifulSoup(rendered(item.get("title")), "html.parser").get_text(" ", strip=True)


def content_text(content: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(content, "html.parser").get_text(" ", strip=True))


def nav_html(
    toc: dict[str, Any],
    filenames: dict[int, str],
    current_id: int | None = None,
) -> str:
    chunks = ['<nav class="book-nav" aria-label="Índice del libro">']
    chunks.append('<a class="home-link" href="../index.html">⌂ Portada e índice</a>')
    if toc.get("front-matter"):
        chunks.append('<p class="nav-part">Preliminares</p><ol>')
        for item in toc["front-matter"]:
            if item["id"] in filenames:
                active = ' aria-current="page" class="active"' if item["id"] == current_id else ""
                chunks.append(
                    f'<li><a{active} href="{html.escape(filenames[item["id"]])}">'
                    f"{html.escape(page_title(item))}</a></li>"
                )
        chunks.append("</ol>")
    for part in toc.get("parts", []):
        part_name = html.escape(page_title(part))
        if part["id"] in filenames:
            active = ' aria-current="page" class="active"' if part["id"] == current_id else ""
            heading = f'<a{active} href="{html.escape(filenames[part["id"]])}">{part_name}</a>'
        else:
            heading = part_name
        chunks.append(f'<p class="nav-part">{heading}</p><ol>')
        for item in part.get("chapters", []):
            if item["id"] in filenames:
                active = ' aria-current="page" class="active"' if item["id"] == current_id else ""
                chunks.append(
                    f'<li><a{active} href="{html.escape(filenames[item["id"]])}">'
                    f"{html.escape(page_title(item))}</a></li>"
                )
        chunks.append("</ol>")
    if toc.get("back-matter"):
        chunks.append('<p class="nav-part">Material final</p><ol>')
        for item in toc["back-matter"]:
            if item["id"] in filenames:
                active = ' aria-current="page" class="active"' if item["id"] == current_id else ""
                chunks.append(
                    f'<li><a{active} href="{html.escape(filenames[item["id"]])}">'
                    f"{html.escape(page_title(item))}</a></li>"
                )
        chunks.append("</ol>")
    chunks.append("</nav>")
    return "".join(chunks)


def license_notice() -> str:
    return (
        '<p><strong>Fuente:</strong> '
        '<a href="https://rotel.pressbooks.pub/biologicalpsychology/">'
        "Biological Psychology [Revised Edition]</a>, de Michael J. Hove y "
        "Steven A. Martinez, ROTEL (2024).</p>"
        '<p>Contenido bajo <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">'
        "CC BY-NC-SA 4.0</a>, excepto donde se indique otra licencia. "
        "Esta copia local conserva las atribuciones incluidas en el original.</p>"
    )


def document(title: str, body: str, *, prefix: str = "", description: str = "") -> str:
    escaped_title = html.escape(title)
    escaped_description = html.escape(description or title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{escaped_description}">
  <title>{escaped_title}</title>
  <link rel="stylesheet" href="{prefix}assets/style.css">
</head>
<body>
{body}
<script src="{prefix}assets/site.js"></script>
</body>
</html>
"""


def render_page(
    item: dict[str, Any],
    content: str,
    toc: dict[str, Any],
    filenames: dict[int, str],
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
) -> str:
    title = page_title(item)
    previous_link = (
        f'<a rel="prev" href="{filenames[previous_item["id"]]}">← {html.escape(page_title(previous_item))}</a>'
        if previous_item
        else "<span></span>"
    )
    next_link = (
        f'<a rel="next" href="{filenames[next_item["id"]]}">{html.escape(page_title(next_item))} →</a>'
        if next_item
        else "<span></span>"
    )
    body = f"""
<a class="skip-link" href="#contenido">Saltar al contenido</a>
<header class="topbar">
  <button class="menu-button" type="button" aria-expanded="false" aria-controls="sidebar">☰ Índice</button>
  <a href="../index.html">Biological Psychology — copia local</a>
  <form class="mini-search" action="../index.html"><label class="sr-only" for="q">Buscar</label><input id="q" name="q" type="search" placeholder="Buscar"></form>
</header>
<div class="layout">
  <aside id="sidebar">{nav_html(toc, filenames, item["id"])}</aside>
  <main id="contenido" class="content">
    <article>
      <h1>{html.escape(title)}</h1>
      <div class="pressbooks-content">{content}</div>
    </article>
    <nav class="page-turner" aria-label="Páginas anterior y siguiente">{previous_link}{next_link}</nav>
    <footer>{license_notice()}</footer>
  </main>
</div>
"""
    return document(f"{title} — Biological Psychology", body, prefix="../")


def write_assets() -> None:
    style = """
:root{--ink:#17212b;--muted:#596773;--paper:#fff;--wash:#f2f5f4;--brand:#176b61;--line:#d9e1df;--width:76rem}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--paper);font:17px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:#075f91}a:hover{text-decoration-thickness:2px}img,video{max-width:100%;height:auto}iframe{max-width:100%}
.skip-link{position:absolute;left:-9999px}.skip-link:focus{left:1rem;top:1rem;z-index:10;background:#fff;padding:.7rem}
.topbar{position:sticky;top:0;z-index:4;display:flex;align-items:center;gap:1rem;min-height:3.5rem;padding:.5rem 1rem;background:#123d39;color:#fff;box-shadow:0 1px 5px #0004}.topbar>a{color:#fff;text-decoration:none;font-weight:700}.menu-button{display:none}.mini-search{margin-left:auto}.mini-search input{width:13rem;padding:.45rem .65rem;border:0;border-radius:.25rem}
.layout{display:grid;grid-template-columns:minmax(15rem,20rem) minmax(0,1fr);max-width:var(--width);margin:auto}
#sidebar{position:sticky;top:3.5rem;height:calc(100vh - 3.5rem);overflow:auto;padding:1.3rem 1rem;border-right:1px solid var(--line);background:var(--wash)}
.book-nav ol{padding-left:1.35rem}.book-nav li{margin:.35rem 0}.book-nav a{text-decoration:none}.book-nav .active{font-weight:700;color:var(--brand)}.home-link{font-weight:700}.nav-part{margin:1.25rem 0 .25rem;font-weight:750}
.content{min-width:0;padding:clamp(1.2rem,4vw,4rem)}article{max-width:49rem;margin:auto}h1,h2,h3,h4{line-height:1.2;color:#173b37}h1{font-size:clamp(2rem,5vw,3.25rem);margin-top:0}h2{margin-top:2.5rem}blockquote{margin:1.5rem 0;padding:.5rem 1.2rem;border-left:.3rem solid var(--brand);background:var(--wash)}
figure{margin:2rem 0}figcaption{color:var(--muted);font-size:.92rem}.wp-caption{max-width:100%}.pressbooks-content table{display:block;max-width:100%;overflow-x:auto;border-collapse:collapse}.pressbooks-content th,.pressbooks-content td{padding:.55rem;border:1px solid var(--line)}
.page-turner{display:flex;justify-content:space-between;gap:2rem;max-width:49rem;margin:4rem auto 2rem;padding-top:1.5rem;border-top:1px solid var(--line)}.page-turner a:last-child{text-align:right}
footer{max-width:49rem;margin:auto;padding-top:1.5rem;border-top:1px solid var(--line);color:var(--muted);font-size:.88rem}
.hero{padding:clamp(2rem,7vw,6rem) 1.2rem;background:linear-gradient(130deg,#123d39,#1a7569);color:#fff}.hero-inner{display:grid;grid-template-columns:minmax(0,2fr) minmax(12rem,1fr);gap:3rem;align-items:center;max-width:64rem;margin:auto}.hero h1{color:#fff}.hero img{max-height:28rem;box-shadow:0 10px 30px #0006}.index-main{max-width:64rem;margin:0 auto;padding:2rem 1.2rem 5rem}.search-box{display:flex;gap:.5rem;margin:2rem 0}.search-box input{flex:1;padding:.8rem;font-size:1rem}.search-results{padding:0;list-style:none}.search-results li{padding:1rem 0;border-bottom:1px solid var(--line)}.toc-grid{columns:2 20rem}.toc-grid li{break-inside:avoid;margin:.4rem 0}.part-title{margin-top:1.8rem;font-weight:750;break-after:avoid}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:760px){.menu-button{display:block}.mini-search{display:none}.layout{display:block}#sidebar{display:none;position:fixed;inset:3.5rem 0 0 0;z-index:3;height:auto;border:0}#sidebar.open{display:block}.content{padding:1.3rem}.hero-inner{grid-template-columns:1fr}.hero img{max-height:20rem}.toc-grid{columns:1}.topbar>a{font-size:.9rem}}
@media print{.topbar,#sidebar,.page-turner,.search-box{display:none!important}.layout{display:block}.content{padding:0}a{color:inherit}.pressbooks-content a[href^="http"]::after{content:" (" attr(href) ")";font-size:.75em}}
"""
    script = """
document.querySelectorAll('.menu-button').forEach((button)=>button.addEventListener('click',()=>{
  const sidebar=document.getElementById('sidebar');const open=sidebar.classList.toggle('open');
  button.setAttribute('aria-expanded',String(open));
}));
const search=document.getElementById('book-search');
if(search){
  const results=document.getElementById('search-results');let index=[];
  fetch('search-index.json').then(r=>r.json()).then(data=>{index=data;run()});
  const run=()=>{const q=search.value.trim().toLocaleLowerCase();results.innerHTML='';
    if(q.length<2)return;
    index.filter(x=>(x.title+' '+x.text).toLocaleLowerCase().includes(q)).slice(0,50).forEach(x=>{
      const li=document.createElement('li'),a=document.createElement('a'),p=document.createElement('p');
      a.href='pages/'+x.file;a.textContent=x.title;
      const at=x.text.toLocaleLowerCase().indexOf(q),start=Math.max(0,at-80);
      p.textContent=(start?'…':'')+x.text.slice(start,start+240)+(x.text.length>start+240?'…':'');
      li.append(a,p);results.append(li);
    });
    if(!results.children.length)results.innerHTML='<li>No se encontraron resultados.</li>';
  };
  search.addEventListener('input',run);
  const initial=new URLSearchParams(location.search).get('q');if(initial){search.value=initial}
}
"""
    (OUTPUT_DIR / "assets" / "style.css").write_text(style.strip() + "\n", encoding="utf-8")
    (OUTPUT_DIR / "assets" / "site.js").write_text(script.strip() + "\n", encoding="utf-8")


def main() -> int:
    print("Descargando estructura y contenidos de Pressbooks…")
    toc = get_api_json("toc")
    metadata = get_api_json("metadata")
    collections = {
        "front-matter": get_api_json("front-matter?per_page=100"),
        "parts": get_api_json("parts?per_page=100"),
        "chapters": get_api_json("chapters?per_page=100"),
        "back-matter": get_api_json("back-matter?per_page=100"),
    }
    by_id: dict[int, dict[str, Any]] = {}
    for collection in collections.values():
        by_id.update({item["id"]: item for item in collection})

    ordered: list[dict[str, Any]] = []
    for summary in toc.get("front-matter", []):
        if summary["id"] in by_id:
            ordered.append(by_id[summary["id"]])
    for part in toc.get("parts", []):
        full_part = by_id.get(part["id"])
        if full_part and content_text(rendered(full_part.get("content"))):
            ordered.append(full_part)
        for summary in part.get("chapters", []):
            if summary["id"] in by_id:
                ordered.append(by_id[summary["id"]])
    for summary in toc.get("back-matter", []):
        if summary["id"] in by_id:
            ordered.append(by_id[summary["id"]])

    if not ordered:
        raise RuntimeError("La API no devolvió páginas publicadas.")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    MEDIA_DIR.mkdir(parents=True)
    (OUTPUT_DIR / "pages").mkdir()

    filenames: dict[int, str] = {}
    used_names: set[str] = set()
    for item in ordered:
        base = safe_slug(item.get("slug", ""), f"pagina-{item['id']}")
        filename = f"{base}.html"
        if filename in used_names:
            filename = f"{base}-{item['id']}.html"
        filenames[item["id"]] = filename
        used_names.add(filename)

    page_map: dict[str, str] = {}
    for item in ordered:
        if item.get("link"):
            page_map[normalize_path(item["link"])] = filenames[item["id"]]

    all_media: set[str] = set()
    for item in ordered:
        all_media.update(media_urls(rendered(item.get("content")), item.get("link") or SOURCE_URL))
    cover_url = extract_cover(metadata)
    if cover_url:
        all_media.add(cover_url)

    print(f"Descargando {len(all_media)} recursos multimedia…")
    media_map: dict[str, str] = {}
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_media, url): url for url in sorted(all_media)}
        for count, future in enumerate(as_completed(futures), 1):
            original, local, error = future.result()
            if local:
                media_map[original] = local
            else:
                failures.append({"url": original, "error": error or "error desconocido"})
            if count % 25 == 0 or count == len(futures):
                print(f"  {count}/{len(futures)} recursos procesados")

    search_index: list[dict[str, str]] = []
    for index, item in enumerate(ordered):
        raw_content = rendered(item.get("content"))
        rewritten = rewrite_content(
            raw_content,
            item.get("link") or SOURCE_URL,
            media_map,
            page_map,
        )
        previous_item = ordered[index - 1] if index else None
        next_item = ordered[index + 1] if index + 1 < len(ordered) else None
        output = render_page(item, rewritten, toc, filenames, previous_item, next_item)
        (OUTPUT_DIR / "pages" / filenames[item["id"]]).write_text(output, encoding="utf-8")
        search_index.append(
            {
                "title": page_title(item),
                "file": filenames[item["id"]],
                "text": content_text(raw_content),
            }
        )

    write_assets()
    (OUTPUT_DIR / "search-index.json").write_text(
        json.dumps(search_index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    description = BeautifulSoup(str(metadata.get("description") or ""), "html.parser").get_text(" ", strip=True)
    title = str(metadata.get("name") or "Biological Psychology [Revised Edition]")
    first_file = filenames[ordered[0]["id"]]
    cover = (
        f'<img src="{html.escape(media_map[cover_url])}" alt="Portada de {html.escape(title)}">'
        if cover_url and cover_url in media_map
        else ""
    )
    toc_sections = nav_html(toc, filenames).replace("../index.html", "index.html")
    for filename in filenames.values():
        toc_sections = toc_sections.replace(
            f'href="{filename}"',
            f'href="pages/{filename}"',
        )
    index_body = f"""
<a class="skip-link" href="#contenido">Saltar al contenido</a>
<section class="hero">
  <div class="hero-inner">
    <div>
      <p>Edición local sin conexión</p>
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(description)}</p>
      <p><a href="pages/{html.escape(first_file)}" style="color:white;font-weight:700">Comenzar a leer →</a></p>
    </div>
    {cover}
  </div>
</section>
<main id="contenido" class="index-main">
  <section aria-labelledby="buscar-titulo">
    <h2 id="buscar-titulo">Buscar en el libro</h2>
    <div class="search-box"><label class="sr-only" for="book-search">Texto a buscar</label><input id="book-search" type="search" placeholder="Escribe al menos dos caracteres…"></div>
    <ol id="search-results" class="search-results"></ol>
  </section>
  <section aria-labelledby="indice-titulo">
    <h2 id="indice-titulo">Índice</h2>
    <div class="toc-grid">{toc_sections}</div>
  </section>
  <footer>{license_notice()}</footer>
</main>
"""
    (OUTPUT_DIR / "index.html").write_text(
        document(title, index_body, description=description),
        encoding="utf-8",
    )
    build_info = {
        "source": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pages": len(ordered),
        "media_downloaded": len(media_map),
        "media_failed": failures,
        "license": "CC BY-NC-SA 4.0, excepto donde se indique otra licencia",
    }
    (OUTPUT_DIR / "build-info.json").write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Sitio generado en {OUTPUT_DIR}: {len(ordered)} páginas, "
        f"{len(media_map)} recursos locales, {len(failures)} recursos remotos."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nGeneración cancelada.", file=sys.stderr)
        raise SystemExit(130)
