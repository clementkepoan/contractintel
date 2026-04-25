---
name: Technical Operations Framework
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#44474c'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#75777d'
  outline-variant: '#c5c6cd'
  surface-tint: '#515f74'
  primary: '#1d2b3e'
  on-primary: '#ffffff'
  primary-container: '#334155'
  on-primary-container: '#9eadc5'
  inverse-primary: '#b9c7e0'
  secondary: '#505f76'
  on-secondary: '#ffffff'
  secondary-container: '#d0e1fb'
  on-secondary-container: '#54647a'
  tertiary: '#1c2b3c'
  on-tertiary: '#ffffff'
  tertiary-container: '#334153'
  on-tertiary-container: '#9eadc2'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d5e3fd'
  primary-fixed-dim: '#b9c7e0'
  on-primary-fixed: '#0d1c2f'
  on-primary-fixed-variant: '#3a485c'
  secondary-fixed: '#d3e4fe'
  secondary-fixed-dim: '#b7c8e1'
  on-secondary-fixed: '#0b1c30'
  on-secondary-fixed-variant: '#38485d'
  tertiary-fixed: '#d4e4fa'
  tertiary-fixed-dim: '#b9c8de'
  on-tertiary-fixed: '#0d1c2d'
  on-tertiary-fixed-variant: '#39485a'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  h1:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  data-table:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  code-snippet:
    fontFamily: monospace
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  container-margin: 24px
  gutter: 16px
  table-row-height: 36px
  sidebar-width: 240px
  drawer-width: 400px
---

## Brand & Style

The design system is engineered for high-stakes contract management and technical auditing. It prioritizes information density and cognitive clarity over aesthetic flair, evoking the dependable feeling of a professional workstation. The brand personality is rooted in precision, transparency, and technical rigor.

The design style follows a **Corporate / Modern** approach with a heavy lean toward **Minimalism**. Every pixel serves a functional purpose; there are no decorative flourishes or distracting gradients. The interface is designed to disappear, allowing complex engineering data and contract clauses to remain the primary focus. It communicates reliability through structural alignment and a restrained, utilitarian aesthetic.

## Colors

The palette is intentionally desaturated to reduce eye strain during prolonged auditing sessions. It relies on a sophisticated range of slates and grays to establish hierarchy.

- **Primary & Neutrals:** Uses Slate-700 (#334155) for core interface elements and Slate-50 (#f8fafc) for primary work surfaces.
- **Functional Status:** Status colors are high-contrast for legibility but low-vibrancy. Emerald is used for approved contracts, Amber for warnings or pending audits, and Slate for neutral/draft states.
- **Offline Readiness:** A specific "Sync Blue" (#0ea5e9) is reserved exclusively for connectivity indicators, providing a calm but obvious signal of local-first data integrity.

## Typography

This design system utilizes **Inter** for its exceptional legibility at small scales and its neutral, systematic character. 

The typographic system is built for data density. Data tables utilize a specialized 13px size to maximize vertical information display without sacrificing the "scannability" required for legal and engineering reviews. Headings are compact, and a "label-caps" style is used for table headers and section metadata to provide a clear visual break from body content.

## Layout & Spacing

The layout uses a **Fluid Grid** for the main dashboard content, allowing the system to scale across ultra-wide engineering monitors. 

- **Structure:** A fixed 240px left-hand sidebar contains global navigation. A right-hand "Context Drawer" (400px) slides over content for metadata inspection, ensuring the user never loses their place in the primary list.
- **Density:** Spacing is based on a 4px baseline grid. Component padding is tight (8px to 12px) to minimize scrolling. Data tables use a fixed 36px row height to maintain a "compact-yet-clickable" target area.

## Elevation & Depth

This design system uses **Tonal Layers** and **Low-contrast Outlines** rather than heavy shadows to define hierarchy.

- **Surface Levels:** The background uses a slightly darker neutral (#f1f5f9), while primary work cards and tables sit on pure white (#ffffff). 
- **Borders:** Instead of shadows, use 1px borders in Slate-200 (#e2e8f0) to define element boundaries.
- **Interaction Depth:** A subtle 2px blur shadow is permitted only for floating elements like dropdown menus or active drawers to provide a clear physical cue of "overlay" without disrupting the flat, technical aesthetic.

## Shapes

The design system employs **Soft** (4px) roundedness. This minimal radius maintains the "grid-like" feel of technical drawings and blueprints while softening the UI enough to prevent visual fatigue. 

- **Buttons & Inputs:** Use the standard 4px radius.
- **Status Badges:** Use a fully pill-shaped radius (rounded-full) to differentiate them from interactive buttons and data cells.
- **Cards:** Kanban cards and dashboard containers use the 4px radius to reinforce the modular, structured nature of the data.

## Components

- **Compact Data Tables:** Rows use alternating "Zebra" striping (Slate-50). Cell borders are horizontal only to emphasize line-by-line reading. Text truncation occurs with ellipses, but full content is visible on hover.
- **Citation Icon Buttons:** Small, square 24px buttons with monochrome icons used to link specific contract clauses. They appear inline or at the end of data rows.
- **Status Badges:** Subtle background tints with high-contrast text (e.g., Emerald-100 background with Emerald-900 text). No icons are used in badges unless they indicate an error.
- **Right-Side Context Drawers:** These host metadata, audit trails, and version history. They feature a pinned header and footer with a scrollable middle section.
- **Kanban Cards:** Simplified cards with a top-accent bar colored by status. Primary text is bolded; secondary metadata is displayed in the "label-caps" style.
- **Markdown Areas:** Used for contract summaries. They must support monospaced code blocks for technical specifications and nested bullet points.
- **Connectivity Indicator:** A permanent, small status dot in the bottom-left of the sidebar. "Online" is a subtle outline; "Offline/Local Mode" is a solid Sync Blue (#0ea5e9) with a "Changes Pending" counter.