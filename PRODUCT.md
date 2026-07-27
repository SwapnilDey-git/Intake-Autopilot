# Product

## Register

product

## Platform

web

## Users

Reviewers at a small Austrian tax-advisory practice (Personenbetreuer/carer intake), using the dashboard as a recurring part of their workflow rather than a one-off tool. The exact team shape isn't fixed yet — it may be one person (the practice owner) or a small back-office group — so the design targets a competent office worker, not a developer: comfortable with forms and spreadsheets, not assumed to be technical. No secondary audience; this is a single-surface internal tool, not something shown to the carer or the tax client.

## Product Purpose

A human-in-the-loop review layer over a local vision-LLM extraction of handwritten Austrian tax intake forms. The AI reads a photographed/uploaded form into structured fields; the dashboard is where a reviewer verifies or corrects those fields, sees flags for missing data, low-confidence reads, and duplicate submissions, and approves the result into the client's Excel tax-calc records. It exists to eliminate manual re-typing of handwritten forms while keeping a mandatory, informed human checkpoint before anything is written or sent — nothing here runs unattended. Success is reviewers moving through forms quickly without anything wrong (a misread field, a duplicate, a low-confidence guess) slipping through unnoticed.

## Positioning

The trust layer over a local AI extraction: every element on screen exists to make a reviewer confident enough to approve what a local vision model read off a handwritten form, not just to display data.

## Brand Personality

Precise, calm, trustworthy. The voice carries the same directness as the practice's Metaborong design system — unembellished, engineering-grade, no marketing inflation — but the typographic DNA (Switzer, JetBrains Mono) is what transfers, not the marketing-site costume. This is a functional tool opened dozens of times a day, not a pitch: labels, warnings, and statuses should read as deliberate and credible, never decorative.

## Anti-references

Two specific things to avoid: (1) the generic AI-SaaS dashboard cliché — purple/blue gradient cards, hero-metric tiles, glassmorphism, rounded-everything, the look every AI-wrapper startup ships right now; (2) the Metaborong marketing site itself — no hero sections, no big display type, no scroll-driven reveals. This is a working tool, not a landing page, even though it borrows the same font stack and tone of voice.

## Design Principles

- **Trust is the product.** Confidence scores, warning banners, and disabled states exist to make an approval decision defensible, not to decorate the screen.
- **Nothing slips through by accident.** Error-proofing and clear negative states (low-confidence field, missing field, duplicate submission, failed extraction) take priority over visual polish whenever the two are in tension.
- **Built for repetition, not first impressions.** The same person(s) open this dozens of times a day — optimize for scan speed and low friction, not a "wow" first-run moment.
- **Borrow the voice, not the costume.** Carry the practice's design system's precise, unembellished typographic DNA without importing its marketing-site visual weight.
- **Local-first is a promise, not just infrastructure.** Data residency and sensitivity are the reason this whole system exists — the UI should never feel like a slick SaaS wrapper hiding what's actually a self-hosted, airgapped tool.

## Accessibility & Inclusion

WCAG 2.2 AA target, treated as a real priority rather than a checkbox — the review step is a mandatory gate on sensitive tax data, so reviewers must not be able to miss or misapprove something by accident. Strong contrast, explicit confirmation states, clear low-confidence/missing-field warnings, full keyboard operability, and a visible focus ring on every interactive element are all load-bearing, not optional polish.
