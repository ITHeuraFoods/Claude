# Heura Word Document — Format Spec

This is the exact format extracted from `assets/heura-doc-template.docx`. Reproduce
these values when building or editing a Heura Word document. **Always start from the
template file** — these values are what the template already contains; the spec is here
so you can verify and extend it, not so you rebuild from scratch.

## Page setup

| Property | Value |
|----------|-------|
| Page size | A4 portrait (210 × 297 mm) |
| Margins | 2.54 cm (1" / 1440 twips) top, bottom, left, right |
| Header distance | 1.27 cm (720 twips) |
| Footer distance | 1.27 cm (720 twips) |

## Typography

- **Body / default font: `Poppins`, 11 pt** (docDefaults). Poppins is the Heura
  workhorse font (Google Fonts, free). If unavailable, fall back to **Calibri** — never
  another brand font.
- Heading styles (all inherit Poppins from the default):

| Style | Size | Color | Notes |
|-------|------|-------|-------|
| Title | 26 pt | default (black) | Document title |
| Subtitle | 15 pt | `#666666` | Optional subtitle |
| Heading 1 | 20 pt | default | Main section labels, `spacing before 20pt / after 6pt`, keepNext |
| Heading 2 | 16 pt | default | Sub-topics |
| Heading 3 | 14 pt | `#434343` | |
| Heading 4 | 12 pt | `#666666` | |

## Header

The template header contains:
- The **Heura wordmark logo** (black, `word/media/image1.jpg`).
- The text **"Heura Foods Document"**.

Keep both. Do not delete the logo or rebuild the header from scratch.

## Brand colors (for sparing accents only)

- Heura Yellow `#FDE01D` — primary accent (table header shading, thin rules). Use sparingly.
- Black `#000000` — body text.
- White `#FFFFFF` — background.
- Tertiaries (graphic details only, rarely in a document): Orange `#FF7700`,
  Green `#00AE44`, Light Green `#85C300`.

Documents are **black text on white** by default. Yellow is an accent, not a background.

## Standard document structure

The template ships with this canonical layout — keep it and fill it in:

1. **Title** (Title style) — placeholder `"Title Of the Document"`.
2. **Metadata table** (2 rows):
   - Row 1: `Owner` | `Name Surname` | `Team` | *(value)*
   - Row 2: `Revised` | *(value)* | `Last Rv.` | *(date, e.g. "5 Mar 2023")*
3. **Objective:** (Heading 1) — short explanation + bullet objectives.
4. **Detailed Description:** (Heading 1) — sub-topics as Heading 2.
5. **Technical resources:** (Heading 1)
6. **Risk:** (Heading 1)
7. **Extra documentation:** (Heading 1)

Add, remove or rename sections to fit the user's content, but keep the visual style,
the header, and the metadata table.

## Building it with `python-docx`

### Preferred: copy the template and edit placeholders

```python
import shutil
from docx import Document

# 1. Copy the template so the header logo, fonts and styles are preserved
shutil.copy("assets/heura-doc-template.docx", "output.docx")
doc = Document("output.docx")

# 2. Replace placeholder text in paragraphs (simple find & replace)
REPLACEMENTS = {
    "Title Of the Document": "My Real Title",
    "Name Surname": "Enaitz Semperena",
    "5 Mar 2023": "7 Jul 2026",
}
for p in doc.paragraphs:
    for run in p.runs:
        for old, new in REPLACEMENTS.items():
            if old in run.text:
                run.text = run.text.replace(old, new)

# 3. Replace placeholders inside the metadata table too
for table in doc.tables:
    for row in table.rows:
        for cell in row.cells:
            for old, new in REPLACEMENTS.items():
                if old in cell.text:
                    cell.text = cell.text.replace(old, new)

# 4. Add content using the template's built-in styles
doc.add_heading("Objective:", level=1)      # uses Heading 1 (Poppins 20pt)
doc.add_paragraph("Explain the objective here.")
doc.add_paragraph("First objective", style="List Bullet")

doc.save("output.docx")
```

> Note: `run.text` replacement only works when the placeholder lives in a single run.
> If Word split it across runs, either use the `docx` skill's find-and-replace helper
> or set the paragraph text directly.

### Enforcing Poppins if you add fresh content

```python
from docx.shared import Pt

def set_poppins(run, size=11):
    run.font.name = "Poppins"
    run.font.size = Pt(size)
    # ensure East-Asian/complex fallback also maps to Poppins
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rFonts.set(qn := __import__("docx.oxml.ns", fromlist=["qn"]).qn(attr), "Poppins")
```

If Poppins is not installed on the machine rendering the file, Word substitutes the
nearest font; the document still opens. Do not embed alternate brand fonts.

## Checklist before delivering

- [ ] Built from `assets/heura-doc-template.docx` (header logo present).
- [ ] Title, owner, team and revision date filled in.
- [ ] Body in Poppins 11 pt; section labels use Heading 1/2 styles.
- [ ] A4 portrait, 2.54 cm margins (inherited from template — don't override).
- [ ] Black text on white; yellow used only as a light accent, if at all.
- [ ] User's content preserved verbatim — only the format is Heura.
