---
name: heura-brand-deck
description: >-
  Apply the Heura 2026 brand guidelines (colors, typography, layout, do's &
  don'ts) to ANY presentation or slide deck. Use this skill whenever the user
  asks to create, build, design, or restyle a deck, slides, presentation,
  pitch, .pptx, or PowerPoint — regardless of topic. Always pair with the pptx
  skill: this skill defines HOW the deck must look (brand), pptx defines HOW to
  build the file. Trigger on "deck", "slides", "presentation", "pitch deck",
  "PowerPoint", ".pptx", or any request that results in slides.
compatibility: requires pptx skill
---

# Heura Brand Deck

This skill makes every deck **on-brand for Heura** (purpose-made plant-based food company; brand archetype: **The Outlaw** — bold, rule-breaking, authentic, confident).

## How to use this skill

1. **Read the brand spec first.** Open `references/brand_spec.md` for the exact color hex codes, typography rules, weights, and the do's & don'ts. These are non-negotiable brand constants.
2. **Then build the .pptx using the `pptx` skill** for the file mechanics. `references/pptx_theme.md` shows exactly how to translate the brand spec into `python-pptx` code (palette, master slides, fonts, title/body styling).
3. **Apply the brand to whatever content the user gives you.** This skill is purely visual/aesthetic — never change the user's actual message, just dress it in the brand.

## Non-negotiable rules (quick reference)

### Color palette
- **Primary**: Heura Yellow `#FDE01D` — always present in graphics, great for backgrounds
- **Secondaries**: Black `#000000` and White `#FFFFFF` (backgrounds, text, graphic elements)
- **Tertiaries** (for graphic details ONLY, never as backgrounds):
  - Orange: `#FF7700`
  - Green: `#00AE44`
  - Light Green: `#85C300`

### Background universes
**Two approved options only:**
- Yellow background with black/white text and accents
- Black background with white/yellow text and accents
- White is also acceptable (use with black text and yellow/color accents)

**Never do this:**
- Mix tertiary colors as backgrounds
- Combine light green on yellow
- Use dark green on black

### Typography

| Usage | Font | Weight | Notes |
|-------|------|--------|-------|
| Brand headings (digital) | **Heura** | Regular | Custom font from heurafoods.com. Used for all h1–h3 on the website. Primary heading font for digital-first decks. |
| Display/Large titles | Veneer | — | UPPERCASE ONLY. Impact moments. |
| Punchy headlines | Druk / Druk Wide | — | Short, bold statements |
| Headlines & body | Poppins | Medium, Semibold, Bold, Black | Workhorse font (Google Fonts, free) |
| Editorial alternative | Reckless Condensed | — | Sparingly, not for body copy |
| Decorative / special | Pixel Grafiti | — | Custom pixel font from heurafoods.com. Decorative use only. |

**Constraints:**
- Max 3 typefaces per slide
- **Heura** is the primary digital heading font — prefer it for presentations shared digitally to match the website
- Fallback hierarchy: Heura → Veneer/Druk → Poppins
- If brand fonts aren't installed, default to **Poppins** everywhere
- Licensed font status: Check `references/pptx_theme.md` for fallback rules

### Tone & aesthetics
- **Big bold type**, high contrast, confident
- Bold yellow/black blocks with generous negative space
- **No clutter**, no shadows/effects on logos
- The Outlaw archetype: rule-breaking, authentic, visually loud

### Avoid at all costs
- Light green on yellow
- Dark green on black
- Overusing yellow (balance with black/white)
- Shadows or effects on the Heura logo
- More than 3 fonts on one slide
- Busy, noisy slides with cramped text

## Workflow when building a deck

1. **User gives you content** (slides, talking points, data)
2. **You pair with the `pptx` skill** to build the file
3. **Apply the brand constraints** above to every design decision:
   - Pick one approved background (yellow, black, or white)
   - Choose fonts from the table
   - Use the color palette correctly
   - Ensure high contrast and readability
4. **Verify against the do's & don'ts** before finalizing

## Reference files

- `references/brand_spec.md` — Complete brand spec with examples and use cases
- `references/pptx_theme.md` — How to code these rules in `python-pptx`

## What "transversal" means here

Because the skill description above triggers on any deck request, this skill loads automatically whenever the user asks for slides on ANY topic. You do not need the user to mention "Heura" or "brand" — applying these guidelines is the default for every presentation.
