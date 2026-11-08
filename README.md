# Phoebe's Style Vault

A library of visual styles, grouped by audience (board, bold, creative) and by category.
Each style page has a plain-language description, the topics it fits, an art-style breakdown,
and a JSON recipe to reuse it.

**[Open the Style Vault](https://phoebefu6.github.io/phoebe-style-vault/)**

Finished pieces live in the [Worth a Thousand Words gallery](https://phoebefu6.github.io/sketch-ideas-with-phoebe/).

## How it is built

The site is generated. Do not edit the HTML by hand.

- Source of truth: the style cards in Phoebe's private style store, read through the shared `styles.py` reader.
- `works.json` maps a style to Phoebe's own finished gallery works (the only images published here).
- `python3 build.py` rebuilds every page; `python3 build.py --check` checks the text rules.
