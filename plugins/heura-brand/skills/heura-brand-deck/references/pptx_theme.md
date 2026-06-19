# Heura Brand Theme Implementation in python-pptx

This reference shows how to code the Heura brand guidelines using `python-pptx`. Use this alongside `brand_spec.md` when building decks.

---

## Color Palette as Code

```python
from pptx.util import Pt, Inches
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.dml.color import RGBColor

# Primary Color
HEURA_YELLOW = RGBColor(253, 224, 29)  # #FDE01D

# Secondary Colors
BLACK = RGBColor(0, 0, 0)              # #000000
WHITE = RGBColor(255, 255, 255)        # #FFFFFF

# Tertiary Colors (accents only, never backgrounds)
ORANGE = RGBColor(255, 119, 0)         # #FF7700
GREEN = RGBColor(0, 174, 68)           # #00AE44
LIGHT_GREEN = RGBColor(133, 195, 0)    # #85C300

# Palette dictionary for easy reference
HEURA_PALETTE = {
    'yellow': HEURA_YELLOW,
    'black': BLACK,
    'white': WHITE,
    'orange': ORANGE,
    'green': GREEN,
    'light_green': LIGHT_GREEN,
}
```

---

## Font Setup

```python
from pptx.util import Pt

# Font stack with fallbacks
FONTS = {
    'veneer': {
        'primary': 'Veneer',
        'fallback': 'Poppins',
        'weight': 'normal',  # Veneer is typically one weight
        'style': 'UPPERCASE'  # Always uppercase
    },
    'druk': {
        'primary': 'Druk',
        'fallback': 'Poppins Bold',
        'weight': 'bold',
    },
    'poppins': {
        'primary': 'Poppins',
        'fallback': 'Arial',
        'weights': ['medium', 'semibold', 'bold', 'black']
    },
    'reckless': {
        'primary': 'Reckless Condensed',
        'fallback': 'Poppins',
        'weight': 'normal',
    }
}

# Typography hierarchy
TYPOGRAPHY = {
    'title': {
        'font': 'Poppins',
        'size': Pt(44),
        'weight': 'bold',
        'color': BLACK,
    },
    'headline': {
        'font': 'Druk',
        'size': Pt(32),
        'weight': 'bold',
        'color': BLACK,
    },
    'body': {
        'font': 'Poppins',
        'size': Pt(14),
        'weight': 'medium',
        'color': BLACK,
    },
    'small': {
        'font': 'Poppins',
        'size': Pt(12),
        'weight': 'medium',
        'color': BLACK,
    }
}
```

---

## Helper Functions

```python
def set_background(slide, color):
    """Set slide background to a specific color."""
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_title_shape(slide, text, font_name, size, color, left, top, width, height):
    """Add a text shape with Heura brand styling."""
    textbox = slide.shapes.add_textbox(left, top, width, height)
    text_frame = textbox.text_frame
    text_frame.word_wrap = True
    
    paragraph = text_frame.paragraphs[0]
    paragraph.text = text
    paragraph.font.name = font_name
    paragraph.font.size = size
    paragraph.font.color.rgb = color
    paragraph.font.bold = True
    
    if font_name == 'Veneer':
        paragraph.text = paragraph.text.upper()
    
    return textbox

def add_body_text(slide, text, color=BLACK, size=Pt(14), left=Inches(0.5), top=Inches(2), width=Inches(9), height=Inches(4.5)):
    """Add body copy with consistent Poppins styling."""
    textbox = slide.shapes.add_textbox(left, top, width, height)
    text_frame = textbox.text_frame
    text_frame.word_wrap = True
    
    for line in text.split('\n'):
        if text_frame.paragraphs[0].text == '':
            p = text_frame.paragraphs[0]
        else:
            p = text_frame.add_paragraph()
        
        p.text = line
        p.font.name = 'Poppins'
        p.font.size = size
        p.font.color.rgb = color
        p.level = 0
        p.line_spacing = 1.5
    
    return textbox

def add_accent_shape(slide, shape_type, color, left, top, width, height):
    """Add accent shapes (rectangles, lines, circles) in brand colors."""
    # shape_type: 'rectangle', 'circle', 'line'
    from pptx.enum.shapes import MSO_SHAPE
    
    if shape_type == 'rectangle':
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    elif shape_type == 'circle':
        shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, width, height)
    else:
        shape = slide.shapes.add_connector(1, left, top, left + width, top + height)
    
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.color.rgb = color
    shape.line.width = Pt(3)  # Bold lines
    
    return shape
```

---

## Slide Templates

### Title Slide

```python
def create_title_slide(prs, title_text, subtitle_text=''):
    """Create a Heura title slide (yellow background)."""
    blank_layout = prs.slide_layouts[6]  # Blank layout
    slide = prs.slides.add_slide(blank_layout)
    
    # Yellow background
    set_background(slide, HEURA_YELLOW)
    
    # Main title
    left = Inches(0.5)
    top = Inches(2.5)
    width = Inches(9)
    height = Inches(2)
    
    textbox = slide.shapes.add_textbox(left, top, width, height)
    tf = textbox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title_text.upper()
    p.font.name = 'Veneer'
    p.font.size = Pt(54)
    p.font.color.rgb = BLACK
    p.font.bold = True
    
    # Subtitle (if provided)
    if subtitle_text:
        left = Inches(0.5)
        top = Inches(4.5)
        width = Inches(9)
        height = Inches(1)
        add_body_text(slide, subtitle_text, BLACK, Pt(20), left, top, width, height)
    
    # Logo area (placeholder: add your logo path)
    # logo_pic = slide.shapes.add_picture('heura_logo.png', Inches(8.5), Inches(5.5), width=Inches(1))
    
    return slide

```

### Content Slide (White Background)

```python
def create_content_slide(prs, title_text, body_text, accent_color=HEURA_YELLOW):
    """Create a content slide with white background."""
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)
    
    # White background
    set_background(slide, WHITE)
    
    # Accent bar (left edge, yellow or black)
    accent_shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0), Inches(0),
        Inches(0.1), Inches(7.5)
    )
    accent_shape.fill.solid()
    accent_shape.fill.fore_color.rgb = accent_color
    accent_shape.line.fill.background()
    
    # Title
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(1))
    title_frame = title_box.text_frame
    p = title_frame.paragraphs[0]
    p.text = title_text
    p.font.name = 'Poppins'
    p.font.size = Pt(40)
    p.font.color.rgb = BLACK
    p.font.bold = True
    
    # Body text
    add_body_text(slide, body_text, BLACK, Pt(14), Inches(0.5), Inches(2), Inches(9), Inches(4.5))
    
    return slide
```

### Dark Slide (Black Background)

```python
def create_dark_slide(prs, title_text, body_text=''):
    """Create a dramatic black background slide."""
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)
    
    # Black background
    set_background(slide, BLACK)
    
    # Yellow accent block (bottom-right)
    accent = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(7), Inches(6),
        Inches(2.5), Inches(1.5)
    )
    accent.fill.solid()
    accent.fill.fore_color.rgb = HEURA_YELLOW
    accent.line.fill.background()
    
    # Title (white text on black)
    title_box = slide.shapes.add_textbox(Inches(0.5), Inches(2.5), Inches(9), Inches(2))
    title_frame = title_box.text_frame
    title_frame.word_wrap = True
    p = title_frame.paragraphs[0]
    p.text = title_text
    p.font.name = 'Druk'
    p.font.size = Pt(48)
    p.font.color.rgb = HEURA_YELLOW
    p.font.bold = True
    
    # Body (if provided)
    if body_text:
        add_body_text(slide, body_text, WHITE, Pt(16), Inches(0.5), Inches(5), Inches(6.5), Inches(2))
    
    return slide
```

### Call-to-Action Slide

```python
def create_cta_slide(prs, cta_text, description=''):
    """Create a call-to-action closing slide."""
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)
    
    # Black background
    set_background(slide, BLACK)
    
    # Large yellow block (left side)
    block = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0), Inches(1),
        Inches(3.5), Inches(5.5)
    )
    block.fill.solid()
    block.fill.fore_color.rgb = HEURA_YELLOW
    block.line.fill.background()
    
    # CTA text (on yellow block)
    cta_box = slide.shapes.add_textbox(Inches(0.3), Inches(2.5), Inches(2.9), Inches(3))
    cta_frame = cta_box.text_frame
    cta_frame.word_wrap = True
    p = cta_frame.paragraphs[0]
    p.text = cta_text.upper()
    p.font.name = 'Veneer'
    p.font.size = Pt(48)
    p.font.color.rgb = BLACK
    p.font.bold = True
    
    # Description (optional, white text on black)
    if description:
        desc_box = slide.shapes.add_textbox(Inches(4.5), Inches(3), Inches(5), Inches(2.5))
        desc_frame = desc_box.text_frame
        desc_frame.word_wrap = True
        p = desc_frame.paragraphs[0]
        p.text = description
        p.font.name = 'Poppins'
        p.font.size = Pt(16)
        p.font.color.rgb = WHITE
    
    # Logo area (placeholder)
    # logo_pic = slide.shapes.add_picture('heura_logo_white.png', Inches(7.5), Inches(5.5), width=Inches(1.5))
    
    return slide
```

---

## Complete Example

```python
from pptx import Presentation
from pptx.util import Inches, Pt

# Create presentation
prs = Presentation()
prs.slide_width = Inches(10)
prs.slide_height = Inches(7.5)

# Add slides
create_title_slide(prs, "Transform Your Plate", "Plant-based. Fearless. Delicious.")
create_content_slide(prs, "The Problem", "Traditional protein sources aren't cutting it. We're building a better way.")
create_dark_slide(prs, "Bold. Authentic. On-Brand.", "That's the Heura way.")
create_cta_slide(prs, "Join the Outlaw", "heura.com")

# Save
prs.save('heura_deck.pptx')
```

---

## Validation Checklist

Before finalizing any deck, verify:

- ✅ **Colors**: Only use palette colors (yellow, black, white, tertiary accents)
- ✅ **Typography**: Max 3 fonts per slide, Poppins as workhorse
- ✅ **Contrast**: 4.5:1 ratio for body, 3:1 for headlines
- ✅ **Logo**: Unmodified, no shadows or effects
- ✅ **Spacing**: Generous margins (min 40px), breathing room
- ✅ **Backgrounds**: Yellow, black, or white only (no mixing tertiaries)
- ✅ **Tone**: Bold, confident, rule-breaking (Outlaw archetype)

---

## Notes

- **Font Installation**: Before running the script, ensure Veneer, Druk, and Reckless Condensed are installed. Otherwise, python-pptx will silently substitute system defaults.
- **Export**: When exporting to PDF, test colors on a projector if critical. Yellow can fade under projection.
- **Accessibility**: Always verify contrast ratios using a tool like WebAIM. Don't rely on visual inspection alone.
