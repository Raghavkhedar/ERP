# Senken ERP

Django + HTMX + Alpine + Tailwind v4 (standalone CLI). No React or Node build.

## Commands

- Tests: `uv run pytest`
- Build CSS: `./bin/tailwindcss -i static/css/input.css -o static/css/app.css` (add `--watch` while working; `app.css` is gitignored and built on deploy)

## Design system: neo-brutalism (applies to everything we build)

Every new page, component and change follows this look. It lives in one place, `static/css/input.css` (the `@theme` block plus the neo-brutalism rules at the bottom), so use the existing Tailwind colour names and utilities rather than new hard-coded styles.

- **Palette** (from the logo, `static/img/logo.png`): pale sky page `canvas` #DDF0FA with a faint dot texture, white `surface` panels, `ink` #14112B for outlines, text and shadows, sky blue `blue-600` #0090D8 as the primary colour, indigo `blue-900` #281068 for dark blocks, and one yellow accent `pop` #FFD43B. Red and green stay for errors and success.
- **Outlines**: boxes (cards, fields, selects, buttons) are `border border-ink`, which renders 2px. Row dividers inside a card stay a pale `border-gray-100`.
- **Shadows**: hard offsets of the ink, never blurred: `shadow-md` (3px), `shadow-lg` (4px), `shadow-xl` (6px). Use `shadow-xl` on big cards, `shadow-md` on small ones and stickers.
- **Corners**: softly rounded, themed in `@theme`: `rounded-md` 6px, `rounded-lg` 10px, `rounded-xl` 14px, `rounded-2xl` 20px. Pills and avatars stay `rounded-full`.
- **Type**: Geist. Headings use the `title` utility (weight 800, tight). Body stays regular. Do not use all-caps labels.
- **Buttons**: primary buttons are `bg-blue-600` and automatically get ink text, an ink outline, a hard shadow, a lift on hover and a press-down on click. Do not restyle them per page.
- **Fields**: white with an ink outline; focus gives a hard sky-blue shadow. The keyboard focus ring on buttons is yellow.
- **Accents**: use `pop` yellow sparingly for stickers and highlights (`sticker` class tilts and straightens on hover). Use ink blocks (`bg-ink`) with `text-pop` for strips and emphasis. `marquee` scrolls a strip of words.
- **Motion**: snappy and mechanical (short linear or stepped transitions, press-downs, tilts, marquees, rolling numbers). No soft glows, blurs or long eases. Heavier motion belongs on showpiece pages (login, home); data pages stay calm and fast. Every animation must stop under `prefers-reduced-motion`.
- **Reference**: the look and components are ported from https://www.cult-ui.com/ and https://ui.watermelon.sh/ (React libraries) into plain CSS and Alpine. Cult UI ideas that fit: cutout/folded/texture cards, texture buttons, pixel headings, rolling numbers, direction-aware tabs, marquee. Recreate them in the templates; do not add React.
- **Checking**: screenshot with headless Chromium at 1280x800 and 390x844 before calling UI work done (`uv run --with playwright python`).
