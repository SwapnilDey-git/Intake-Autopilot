---
name: Intake Reviewer
description: The human trust layer over a local AI extraction of handwritten Austrian tax intake forms.
colors:
  canvas: "oklch(0.16 0.006 260)"
  surface: "oklch(0.205 0.006 260)"
  surface-hover: "oklch(0.245 0.007 260)"
  border: "oklch(0.32 0.01 260)"
  ink: "oklch(0.96 0.003 260)"
  ink-muted: "oklch(0.78 0.01 260)"
  ink-faint: "oklch(0.6 0.01 260)"
  accent: "oklch(0.64 0.14 250)"
  accent-hover: "oklch(0.7 0.14 250)"
  success: "oklch(0.64 0.13 155)"
  success-hover: "oklch(0.7 0.13 155)"
  danger: "oklch(0.62 0.16 20)"
  danger-hover: "oklch(0.68 0.16 20)"
  warning: "oklch(0.75 0.13 80)"
typography:
  body:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  heading:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  label:
    fontFamily: "var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.02em"
  data:
    fontFamily: "var(--font-geist-mono), ui-monospace, monospace"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
rounded:
  sm: "8px"
  md: "10px"
  lg: "14px"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.success}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.lg}"
    padding: "14px 24px"
  button-primary-hover:
    backgroundColor: "{colors.success-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
    rounded: "{rounded.lg}"
    padding: "14px 24px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-hover}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "24px"
  input:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
---

# Design System: Intake Reviewer

## 1. Overview

**Creative North Star: "The Verification Desk"**

A quiet, well-lit desk where someone checks another party's work before it's filed — not a dashboard performing intelligence, a workspace that gets out of the way of judgment. Every surface is flat and low-contrast until something needs attention; the only saturated color on screen at rest is Signal Blue, and it appears exactly where a decision is expected. This system exists to make a reviewer trust what they're looking at, not to impress them.

It explicitly rejects the register most AI-tooling dashboards default to: no gradient headlines, no glassmorphic panels, no glow shadows, no decorative motion. Those read as a product trying to look intelligent; this one is trying to look correct. Typography carries the same precise, unembellished character as the practice's broader design language (Metaborong) — a geometric-humanist sans for everything, a true monospace reserved for the one thing that actually needs it: the extracted data itself.

**Key Characteristics:**
- Flat dark neutral surfaces, stepped by lightness only (canvas → surface → surface-hover), never by blur or transparency layering.
- One accent color (Signal Blue), used only for primary actions, focus rings, and current-state — never decoration.
- A three-color semantic vocabulary (danger / warning / success) that is the *entire* color story beyond the accent — no near-duplicate hues doing the same job.
- Monospace exclusively for extracted form data, to visually mark it as "a machine's reading of a source," distinct from interface chrome.
- Motion limited to state feedback (hover, focus, loading spinners) — nothing plays on load, nothing loops, nothing simulates energy.

## 2. Colors

Restrained: tinted neutrals carry the surface, one accent does all the "act here" signaling, and three semantic colors exist solely to flag review states — never to decorate.

### Primary
- **Signal Blue** (`oklch(0.64 0.14 250)`): the Upload button, focus rings, the current-value emphasis in the queue counter. Nowhere else. If it shows up a third time on a screen, that's a bug, not an accent.

### Neutral
- **Canvas** (`oklch(0.16 0.006 260)`): page background and the innermost recess (data-field wells, the document-preview pane).
- **Surface** (`oklch(0.205 0.006 260)`): card backgrounds — the primary content plane sits one step lighter than canvas.
- **Surface Hover** (`oklch(0.245 0.007 260)`): hover state for surface-level interactive chrome (secondary buttons, the source-PDF header bar).
- **Border** (`oklch(0.32 0.01 260)`): the only line-work in the system. 1px, always — never a colored stripe, never a glow.
- **Ink** (`oklch(0.96 0.003 260)`): primary text and extracted data values.
- **Ink Muted** (`oklch(0.78 0.01 260)`): labels, secondary copy, placeholder text (still clears 4.5:1 — never drop to a truly faint gray for anything readable).
- **Ink Faint** (`oklch(0.6 0.01 260)`): "Not found" empty-value copy only. Never body text, never placeholder.

### Semantic (state only)
- **Danger** (`oklch(0.62 0.16 20)`): Extraction Failed, unsigned-form flag, the Reject button's text/border. Hard blockers — things that need a human decision before anything proceeds.
- **Warning** (`oklch(0.75 0.13 80)`): Missing Fields and Low-Confidence Fields banners. One color for both — they're the same category of "double-check this," and giving them near-identical amber/yellow tones (as the previous version did) was noise, not signal.
- **Success** (`oklch(0.64 0.13 155)`): the Approve button and the empty-queue checkmark. The one place color is allowed to feel good, because it's the one moment that's actually a reward.

### Named Rules
**The One Accent Rule.** Signal Blue is the only saturated, non-semantic color in the system. If a new element wants a color and it isn't flagging a review state, it gets a neutral, not a hue.

**The Flat Stack Rule.** Depth is communicated by *which* neutral a surface sits on (canvas → surface → surface-hover), never by blur, transparency, or shadow. If two panels need to read as "layered," lighten the top one — don't blur the one beneath it.

## 3. Typography

**Body & Display Font:** Geist Sans (self-hosted via `next/font/google`, zero external requests at runtime — consistent with this system's airgapped posture), falling back to system sans-serif.
**Data Font:** Geist Mono, reserved exclusively for extracted field values and anything numeric a reviewer needs to visually audit (E-Card number, tax year, monetary fields, distance/trip counts).

**Character:** One family carries labels, buttons, and body copy — product UI doesn't need a display/body pairing, and a second face would only compete with the data it's supposed to help verify. The monospace face is not a stylistic flourish; it exists so extracted data visually reads as "read off a source," not authored.

### Hierarchy
- **Heading** (600, 24px, 1.3 line-height, -0.01em): the single page title, "Intake Reviewer." Nothing else on the page competes with it in size.
- **Section label** (600, 16px): "AI Extraction," card headers.
- **Body** (400, 14px, 1.5): descriptive copy, banner text, button labels.
- **Field label** (500, 12px, 0.02em tracking, uppercase): the field-name row above every extracted value.
- **Data value** (400, 16px, monospace): the extracted value itself — the one place in the UI where size and font both signal "this is the thing being reviewed."

### Named Rules
**The One Mono Rule.** Monospace appears only on extracted data values and nowhere else — not on labels, not on buttons, not on the page title. Its rarity is what makes it legible as a signal ("this came from the form") rather than a stylistic tic.

## 4. Elevation

Flat by design — zero `box-shadow` anywhere in the system. Depth comes entirely from the neutral stepping described in Colors (canvas → surface → surface-hover) plus 1px borders. This is a deliberate rejection of the glow-shadow, glassmorphic-blur treatment the previous version used; a review tool opened dozens of times a day should feel calm and inert at rest, not like it's perpetually lit from within.

### Named Rules
**The No-Glow Rule.** Nothing in this system emits light. No `box-shadow` with color, no `blur()` filters, no drop-shadows on icons or headings. If an element needs to feel important, make it larger or give it the accent color — never a glow.

## 5. Components

### Buttons
- **Shape:** 14px radius (`rounded-lg`), consistent across primary and secondary.
- **Primary (Approve):** solid Success background, Canvas-colored text, no gradient. Disabled state drops to 40% opacity with `cursor-not-allowed` — this is the only button that can be disabled (a failed extraction can't be approved).
- **Secondary (Reject, Edit Data, Upload):** Surface background at rest, Surface Hover on hover; Reject's text/icon is Danger-colored to signal its consequence without needing a filled background — rejection is a valid, common action, not an alarm state.
- **Hover / Focus:** background-color transition only (150ms), no scale, no translate, no shine sweep. Every interactive element gets a 2px Signal Blue focus-visible ring with 2px offset — never `:focus`, always `:focus-visible`.

### Cards
- **Corner Style:** 14px radius (`rounded-lg`) for panels; 10px (`rounded-md`) for nested field wells and inputs.
- **Background:** Surface for primary panels; Canvas for nested wells (the document preview frame, individual data-field boxes) — the recess reads as "deeper," not "different."
- **Shadow Strategy:** none. See Elevation.
- **Border:** 1px Border color on every card; on data-field wells, the border shifts to Accent at 50% opacity on hover as the only "this is interactive" cue — no background color shift, no lift.
- **Internal Padding:** 24px for primary panels, 16px for nested field wells, matching the `spacing.lg` / `spacing.md` tokens.

### Inputs / Fields
- **Style:** Canvas background, 1px Border, 10px radius, Ink text in monospace (matching the data value it replaces in edit mode).
- **Focus:** 2px Signal Blue ring, no border-color change, no inner shadow.
- **Placeholder:** Ink Muted, never a faint gray below 4.5:1 contrast (the "Your name" field in the reviewer-identity row is a placeholder that's actually load-bearing — it must stay legible).

### Banners (state flags)
- **Style:** 10% tint of the semantic color as background, 40% tint as border, full-strength semantic color for the heading text, Ink Muted for the body copy. No shadow, no icon glow.
- **Danger banners:** Extraction Failed, unsigned-form flag.
- **Warning banners:** Missing Fields, Low-Confidence Fields — same color, distinguished only by heading text and icon, because they're the same severity of "double-check this."

### Navigation
Single-page tool; no persistent nav chrome exists yet. The header row (title + Upload button + queue counter) is the closest analog — flat, no border, no background treatment distinct from Canvas.

## 6. Do's and Don'ts

Every anti-reference from PRODUCT.md is enforced here directly.

### Do:
- **Do** keep the accent to Signal Blue and nothing else — one saturated color, used only for primary actions and focus.
- **Do** use monospace exclusively for extracted data values, to keep "what the AI read" visually distinct from interface chrome.
- **Do** flag Missing Fields and Low-Confidence Fields with the same Warning color — they're one severity tier, not two.
- **Do** give every interactive element a visible `:focus-visible` ring (2px Signal Blue, 2px offset) — this is a mandatory-review-gate tool; keyboard operability isn't optional polish.
- **Do** keep card radius at 14px and under — never larger.

### Don't:
- **Don't** use gradient text or gradient button fills. PRODUCT.md names "the generic AI-SaaS dashboard cliché" as an explicit anti-reference; gradient headlines are its most recognizable tell.
- **Don't** use glassmorphism (`backdrop-blur` + translucent white/black overlays) on any panel. Depth comes from the flat neutral stack, never from blur.
- **Don't** add glow shadows (`box-shadow` with color, colored `drop-shadow`) to any element. See the No-Glow Rule.
- **Don't** add decorative motion — no shine sweeps, no scale-on-hover icon flourishes, no orchestrated load-in sequences. Motion exists only to confirm a state changed.
- **Don't** let this dashboard look like the Metaborong marketing site (the second explicit PRODUCT.md anti-reference) — no hero sections, no display-scale type, no scroll-driven reveals. It borrows the font stack and the directness of voice, nothing else.
- **Don't** introduce a second accent hue "for variety." If a new element seems to need one, it's either a semantic state (use the existing trio) or it doesn't need color at all.
