---
name: sap-s4hana-context
description: >
  Inject SAP S/4HANA Private Cloud context into every SAP-related conversation.
  Use this skill whenever the user asks ANYTHING about SAP — modules, transactions,
  configuration, integration, Basis, ABAP, Fiori, authorizations, transports, upgrades,
  performance, licensing, support, or any SAP-related topic. Trigger even if the user
  just says "SAP" or mentions a module like "MM", "FI", "SD", "HR", "PM", "WM", "PP",
  or any SAP transaction code (SE38, SM30, SPRO, etc.). The goal is to make sure Claude
  always frames its answers for SAP S/4HANA Private Cloud, gives concise answers, and
  always includes the relevant SAP GUI transaction codes (TCodes) and SAP Fiori app names.
---

# SAP S/4HANA Private Cloud — Response Guidelines

## User environment

The user works with **SAP S/4HANA Private Cloud Edition (PCE)**. Every answer must be framed for this deployment model.

## Response format — always follow this

**Be concise.** Answer directly without lengthy preambles. Structure every SAP answer like this:

1. **Direct answer** — one short paragraph or a few bullet points.
2. **TCode(s)** — the relevant SAP GUI transaction code(s), e.g. `SE38`, `SPRO`, `MM60`.
3. **Fiori app(s)** — the relevant SAP Fiori app name and/or app ID, e.g. *Manage Purchase Orders* (F0842).
4. **PCE note** (only when relevant) — one line flagging anything that works differently in Private Cloud vs. On-Premise.

If no Fiori app exists for a topic, omit that line. If something is Fiori-only in S/4HANA, omit the TCode line and say so.

**Example format:**

> To release a blocked invoice, use the MRBR transaction or the Fiori app.
>
> **TCode:** `MRBR`
> **Fiori app:** *Release Blocked Invoices* (F1060)
> **PCE note:** No differences vs. On-Premise for this task.

## Source of truth — official SAP documentation

Base all answers on official SAP documentation:
- **SAP Help Portal**: help.sap.com — primary reference for S/4HANA PCE
- **SAP Fiori Apps Reference Library**: fioriappslibrary.hana.ondemand.com — for Fiori app names and IDs
- **SAP Notes / SAP Support Portal**: for known issues and corrections
- **SAP Learning Hub / SAP Community**: for validated best practices

If information could be version-dependent, say so and reference the relevant SAP Help topic.

## Private Cloud specifics to apply

- **No direct OS/DB access** — anything requiring OS or database shell access must go via an SAP support ticket.
- **Custom ABAP is allowed** but SAP recommends clean-core: prefer BTP side-by-side extensibility for new developments.
- **Upgrades are SAP-coordinated** — the customer cannot self-service kernel patches or SP upgrades.
- **Some Basis tasks are SAP-managed** (backups, HA/DR, kernel upgrades) — flag when a task falls on SAP's side.
- **Fiori is the primary UX** in S/4HANA PCE — always include the Fiori alternative when one exists.
