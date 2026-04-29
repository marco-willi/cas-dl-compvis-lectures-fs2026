# Computer Vision with Deep Learning

Lecture notes, slides, and materials for **Computer Vision mit Deep Learning** — part of the [CAS Deep Learning](https://www.fhnw.ch/de/weiterbildung/informatik/cas-deep-learning) at FHNW. Built with [Quarto](https://quarto.org/) and deployed to GitHub Pages.

[Module description](https://www.fhnw.ch/de/weiterbildung/informatik/fachvertiefungsmodule-data-science/computer-vision-mit-deep-learning)

## Setup

```bash
poetry install
```

## Build

```bash
make render        # build site
quarto preview     # live preview with auto-reload
```

See [docs/](docs/) for troubleshooting (e.g., slow renders on WSL2).

## Project Layout

- `pages/lectures/` — lecture notes (`.qmd`)
- `pages/slides/` — Reveal.js presentation versions
- `pages/background/` — prerequisite material
- `assets/images/{topic}/` — figures organized by topic
- `assets/references.bib` — bibliography
- `demos/` — asset-generating notebooks
