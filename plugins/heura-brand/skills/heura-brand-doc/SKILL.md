---
name: heura-brand-doc
description: >-
  Apply the Heura document format to ANY Word document (.doc / .docx). Use this
  skill whenever the user asks to create, write, build, draft, or restyle a Word
  document, memo, report, spec, procedure, one-pager, or any deliverable as a
  .doc/.docx file — regardless of topic. The output MUST be based on the Heura
  Word template shipped with this skill. Always pair with the `docx` skill: this
  skill defines HOW the document must look (Heura format + template), `docx`
  defines HOW to build the file. Trigger on "Word", "documento", "doc", ".docx",
  "memo", "informe", "report", "plantilla", "template", or any request that
  results in a Word document.
compatibility: requires docx skill
---

# Heura Brand Doc

This skill makes every Word document **on-brand for Heura** by building it on top of the
official Heura Word template. The brand archetype is **The Outlaw** — bold, authentic,
confident — but documents stay clean, corporate and readable (this is not a deck).

## How to use this skill

1. **Always start from the template.** The base file is
   `assets/heura-doc-template.docx`. It already carries the correct page setup,
   fonts (Poppins), the **Heura logo header**, the heading styles, and the standard
   metadata table. **Copy it and edit the copy** — never rebuild the document from a
   blank file, or you lose the header logo, embedded fonts, and styles.
2. **Then edit it with the `docx` skill** for the file mechanics (opening, editing
   paragraphs/tables, find-and-replace, saving).
3. **Read `references/docx_theme.md`** for the exact format spec (fonts, sizes,
   colors, margins) and copy-paste `python-docx` snippets that match the template.
4. **Fill in the user's actual content.** This skill is about format, not message —
   never change what the user wants to say, just dress it in the Heura format.

## The canonical workflow

```
1. Copy assets/heura-doc-template.docx  →  <output>.docx
2. Open the copy with python-docx (docx skill)
3. Replace the placeholders with the user's content:
   - "Title Of the Document"  → real title
   - "Name Surname"           → owner
   - "Team"                   → team
   - "Last Rv." / "5 Mar 2023"→ revision + date (use today's date if none given)
4. Fill the standard sections (add/remove as the content needs):
   - Objective:            (Heading 1)
   - Detailed Description:  (Heading 1)  → sub-topics as Heading 2
   - Technical resources:   (Heading 1)
   - Risk:                  (Heading 1)
   - Extra documentation:   (Heading 1)
5. Save. Verify the header logo and Poppins font survived.
```

## Non-negotiable format rules (quick reference)

- **Base template**: `assets/heura-doc-template.docx` — always the starting point.
- **Page**: A4 portrait, 2.54 cm (1") margins on all sides.
- **Font**: **Poppins** everywhere (body 11 pt). Fallback to Calibri only if Poppins
  is unavailable, never substitute another brand font.
- **Header**: keep the Heura wordmark logo + "Heura Foods Document" — do not remove it.
- **Section labels** use the built-in heading styles from the template:
  - Heading 1 → 20 pt (main sections, e.g. "Objective:", "Risk:")
  - Heading 2 → 16 pt (sub-topics)
  - Heading 3 → 14 pt, `#434343`
  - Heading 4 → 12 pt, `#666666`
  - Title → 26 pt · Subtitle → 15 pt, `#666666`
- **Metadata table** at the top (Owner / Name Surname / Team · Revised / Last Rv. / date)
  is part of the standard layout — keep it and fill it in.
- **Accent color**: Heura Yellow `#FDE01D` may be used sparingly for emphasis
  (table shading, rules). Keep documents predominantly black text on white — this is
  a corporate document, not a poster. Do **not** flood pages with yellow.

## What this skill does NOT do

- It does not create presentations — use **`heura-brand-deck`** for `.pptx`/slides.
- It does not change the user's content or wording — format only.

## Reference files

- `assets/heura-doc-template.docx` — the official Heura Word template (start here).
- `references/docx_theme.md` — full format spec + `python-docx` code snippets.

## What "transversal" means here

Because the description triggers on any Word-document request, this skill loads
automatically whenever the user asks for a `.doc`/`.docx` on ANY topic. The user does
not need to mention "Heura", "brand", or "template" — building from the Heura template
is the default for every Word document.
