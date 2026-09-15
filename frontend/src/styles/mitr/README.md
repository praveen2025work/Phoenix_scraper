# MITR AI design assets

Standalone CSS, icon, and font kit extracted from `apps/web`.

Regenerate after visual changes:

```bash
npm run extract:design-assets
```

## What's in here

| Path | Contents |
| --- | --- |
| `css/tokens.css` | Light/dark design tokens (`--brand`, surfaces, type, radius, shadow) |
| `css/fonts.css` | Self-hosted `@font-face` for Inter, Sora, JetBrains Mono |
| `css/components.css` | Framework-free utilities: buttons, chips, surfaces, type, glass, scrollbars |
| `css/vendor-overrides.css` | Optional AG Grid / Wijmo / Recharts / print / Tailwind-class dark overrides |
| `css/mitr.css` | Entry file that imports fonts + tokens + components |
| `icons/svg/` | Lucide SVGs actually imported by the Next.js UI |
| `icons/sprite.svg` | SVG symbol sprite (`<use href="sprite.svg#message-square" />`) |
| `icons/icons.json` | Export name, file, and `apps/web` usage for every icon |
| `fonts/` | `woff2` files (SIL OFL) |
| `catalog.html` | Visual inventory — open in a browser |

Open `catalog.html` (via a local static server, or as a file) to browse colors, type, components, and the icon set.

## Use in another page

```html
<link rel="stylesheet" href="css/mitr.css" />

<button class="btn-primary">Ask MITR</button>
<span class="chip chip-brand">Indigo / lavender</span>
<img class="icon" src="icons/svg/message-square.svg" alt="" />
```

Toggle dark theme by adding `class="dark"` on `<html>`.

## Fonts

The web app loads these through `next/font/google` in `apps/web/src/app/layout.tsx`:

- **Inter** — UI / body (`--font-sans`)
- **Sora** — display headings (`--font-display`)
- **JetBrains Mono** — numerals and code (`--font-mono`)

This package vendors the latin `woff2` files so they can be self-hosted without Google at runtime.

## Icons

Icons come from `lucide-react` (ISC). Only icons imported by `apps/web` are extracted — not the full Lucide set. See `icons/LUCIDE-LICENSE`.

## Vendor CSS

`vendor-overrides.css` is **not** imported by `mitr.css`. Include it only when you also load AG Grid, Wijmo, or Recharts, or when leftover Tailwind `gray-*` / `blue-*` class names need dark-theme mapping.
