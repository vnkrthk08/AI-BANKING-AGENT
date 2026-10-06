---
name: KURAL Operations Console
description: Role-based call operations, analytics, and compliance workspace for AVA.
colors:
  navy-950: "#101d31"
  navy-900: "#17263d"
  navy-800: "#263a55"
  neutral-0: "#ffffff"
  neutral-50: "#f5f7fa"
  neutral-100: "#edf1f5"
  neutral-500: "#758196"
  neutral-800: "#29364a"
  teal-600: "#087e83"
  teal-50: "#e6f4f3"
  green-700: "#23764b"
  amber-700: "#a76609"
  red-700: "#b23939"
typography:
  body:
    fontFamily: "Inter, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  data:
    fontFamily: "JetBrains Mono, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
rounded:
  sm: "6px"
  md: "10px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.teal-600}"
    textColor: "{colors.neutral-0}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
  sidebar:
    backgroundColor: "{colors.navy-950}"
    textColor: "{colors.neutral-0}"
    width: "248px"
---

## Overview

An operations-first, role-based banking workspace. The visual grammar is a deep navy navigation rail, a bright neutral work surface, and restrained teal actions. Keep the AVA Test Console as one route within the same shell.

## Colors

Navy carries persistent navigation and orientation. Neutral surfaces carry dense operational content. Teal marks the primary action and selected navigation. Green, amber, red and gray are reserved for semantic dispositions and health states; never use them as decoration.

## Typography

Use Inter or the system UI fallback for navigation, headings and prose. Use JetBrains Mono or the system monospace fallback for identifiers, timestamps and compact measurements. Enable tabular numerals for KPIs and tables.

## Layout

Desktop-first shell with a collapsible 248px navigation rail, a fixed-height top bar, contextual filters, and a responsive main workspace. Analytics may use a 12-column grid; agent work is a queue/case/resolution split and must remain action-oriented. Collapse to a single column on tablet widths without hiding critical status or actions.

## Elevation & Depth

Use one-pixel neutral borders as the default separation. Reserve subtle low-opacity shadows for popovers, drawers and floating controls. Avoid stacked nested cards.

## Shapes

Use 6px control radii and 10px panel radii. Status badges may be compact pills; tables and primary workflow surfaces remain squared enough to read as operational tools.

## Components

Use consistent buttons, search, filter, table, drawer and status vocabularies across roles. Label mock roles, synthetic records, unavailable recordings and simulated telephony/email actions in context. Permission checks must be centralized and drive routes, navigation and controls together.

## Do's and Don'ts

- Keep identifiers masked and use synthetic Indian examples with IST timestamps.
- Derive analytics, call log, workload and journey views from the same `CallRecord` collection.
- Log transcript and audio access and data exports through the audit service.
- Never imply browser role switching is security enforcement.
- Never claim a simulated phone call, audio recording, email or external LLM action occurred.
