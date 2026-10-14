# Biological Psychology — copia estática local

Copia local navegable de **Biological Psychology [Revised Edition]**, de
Michael J. Hove y Steven A. Martinez, publicada por ROTEL en Pressbooks.

El sitio generado está en [`site/`](site/) e incluye:

- 113 páginas HTML ordenadas según el índice original.
- Ilustraciones y recursos multimedia descargados localmente.
- Navegación anterior/siguiente e índice lateral adaptable a móviles.
- Búsqueda local en todo el contenido.
- Estilos de pantalla e impresión.
- Atribución y licencia en cada página.

La futura traducción se rige por la
[guía de traducción al español rioplatense](GUIA_DE_TRADUCCION.md), que incluye
criterios editoriales, flujo de revisión y un glosario técnico normativo.

## Abrir el libro

Para que la búsqueda funcione, hay que servir los archivos por HTTP:

```bash
python -m http.server 8000 --directory site
```

Después, abrir <http://localhost:8000>.

## Edición progresiva en español

El capítulo 1 está traducido al español rioplatense. Para generar `site-es/` a
partir de la copia inglesa y de los fragmentos revisables guardados en
`translations/es-rioplatense/`:

```bash
python build_spanish_site.py
python -m http.server 8001 --directory site-es
```

Después, abrir <http://localhost:8001>. Los capítulos todavía no traducidos se
mantienen en inglés y están identificados como tales en la portada.

### Publicación en GitHub Pages

El workflow `.github/workflows/deploy-pages.yml` se ejecuta con cada `push` a
`main` o `master` que modifique el contenido del libro. Genera `site-es/` y
publica únicamente esa edición; la copia inglesa no forma parte del artefacto
desplegado. También puede iniciarse manualmente desde la pestaña **Actions**.

En la configuración del repositorio de GitHub, seleccionar:

```text
Settings → Pages → Build and deployment → Source → GitHub Actions
```

El generador crea `site-es/.nojekyll` automáticamente.

## Actualizar la copia

Instalar las dependencias:

```bash
python -m pip install -r requirements.txt
```

Volver a descargar y generar el libro:

```bash
python build_static_book.py
```

El generador reemplaza completamente `site/` con la versión publicada en ese
momento. Los detalles de cada generación quedan registrados en
`site/build-info.json`.

## Licencia y fuente

Fuente: [Biological Psychology [Revised Edition]](https://rotel.pressbooks.pub/biologicalpsychology/),
ROTEL, 2024.

El libro está disponible bajo
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/),
excepto donde se indique otra licencia. Deben conservarse las atribuciones
específicas de los materiales incorporados en cada capítulo.
