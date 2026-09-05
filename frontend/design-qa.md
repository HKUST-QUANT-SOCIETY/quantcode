# QuantCode Lens UI — Design QA

## Evidence

- Source reference: `/Users/hendrixchen/.codex/generated_images/01a00c59-4fb1-70f2-9dc0-66354a18fe92/exec-699c5ba3-17c1-46f6-aace-f6ccf1fafd2e.png`
- User-reported static interaction issue: `/var/folders/7j/mqxltsb15p12qxs6shkjr3d80000gn/T/TemporaryItems/NSIRD_screencaptureui_jlzTtm/截屏2026-08-18 22.19.01.png`
- Final static implementation: `/private/tmp/quantcode-motion-static-final.png`
- Final in-motion implementation: `/private/tmp/quantcode-motion-dynamic-final.png`
- Compact desktop implementation: `/private/tmp/quantcode-motion-1024.png`
- Route: `http://localhost:4444/` (QuantCode channel root home)
- Comparison viewport: 1487 × 1058 CSS pixels
- Source and implementation captures: 1487 × 1058 physical pixels, 1× density
- State: QuantCode workspace open, task field empty, Auto Factor Evaluation selected, Server B connected. Static evidence has the pointer outside the stage; dynamic evidence captures a fast left-to-right pointer pass while the lens is still carrying momentum.
- Full-view comparison: the selected 1487 × 1058 source and static implementation were inspected together at original detail. A separate crop was not needed because the focus lens, particle field, composer labels, status metadata, and all three research rows are legible at 1:1. The dynamic frame was then inspected independently because the source does not specify a motion frame.

## Findings

- P0: none.
- P1: none.
- P2: none.
- P3: the OpenCode native desktop tab/title strip remains above the QuantCode surface; this is intentional shell integration rather than a mismatch inside the workspace.
- P3: development-only performance diagnostics and the help button remain visible in the local dev build; neither belongs to the QuantCode component and neither is present as QuantCode production UI.
- P3: rail glyphs use the closest icons already present in the OpenCode icon library, avoiding a new asset or SVG dependency.
- Typography: the original Inter/SF Pro and Arial Black hierarchy, weights, tracking, and readable task metadata are preserved. Motion never changes font metrics or layout bounds.
- Spacing and layout: the 60px rail, identity bar, lens, composer, and research rows retain the selected proportions; the 1024 × 800 check keeps the task controls visible and the lower list scrollable.
- Colors and tokens: the monochrome paper/ink palette and status green remain unchanged. Optical energy only modulates opacity, contrast, shadow, and sub-pixel displacement.
- Image and asset fidelity: the target contains no raster hero asset. The canvas particle field is an interactive rendering layer for the existing wordmark, not a replacement for a supplied image or icon.
- Copy and content: task, Skill, group, SSH, template, and research labels are unchanged.

## Iterations

### Iteration 1

- Evidence: `/private/tmp/quantcode-implementation-pass1.png`
- Found: lens content crossed the oversized letterforms and lost contrast; the composer read as a floating rounded card; the third research row was clipped.
- Fixed: moved and enlarged the lens; lowered its controls; rebuilt the composer as a sharp bordered rectangle; reduced row height and moved metadata into a one-line layout.

### Iteration 2

- Evidence: `/private/tmp/quantcode-implementation-pass2.png`
- Found: the oversized title lacked the source's dotted diffusion; identity labels and separators were too heavy; lower metadata was oversized.
- Fixed: added a halftone/diffusion treatment outside the lens; masked a sharp title layer inside it; reduced identity and lens metadata type; changed separators to vertical hairlines.

### Iteration 3 — Particle renderer

- Evidence: `/private/tmp/quantcode-motion-pass1-smear.png`
- Found (P1): focused canvas circles were joined into a single path, producing horizontal black smears across the wordmark and obscuring the lens content.
- Fixed: started every particle arc as an independent subpath before filling, restoring discrete particles without connection artifacts.

### Iteration 4 — Moving lens legibility

- Evidence: `/private/tmp/quantcode-motion-pass2-overlap.png`
- Found (P1): allowing the lens to follow the pointer vertically pulled the title and settings rows back over the heavy display letters, reducing readability.
- Fixed: retained full horizontal inertia while mapping vertical pointer travel to a constrained ±14px optical parallax around the designed anchor. The title remains below the wordmark during motion.

### Final motion pass

- Evidence: `/private/tmp/quantcode-motion-static-final.png` and `/private/tmp/quantcode-motion-dynamic-final.png`
- Result: the static frame preserves the selected composition. Pointer motion now creates a real sampled particle field, spring/damping inertia, radial refraction, edge flow, velocity deformation, and decaying wake marks while the research controls remain stable and readable.

## Interaction and implementation checks

- Task template populates the composer.
- Skill selection updates the active workflow.
- Start Research becomes enabled when a task exists.
- The root route mounts the QuantCode workspace directly; a first-time project selection creates and submits the draft only after the project is available.
- Command/Ctrl+Enter follows the same submission path.
- Submission delegates to the current OpenCode session through `quantcode_run_agent`; the live model call was intentionally not executed during visual QA to avoid an external-cost side effect.
- Memory and HumanGate rail panels open and show their expected states.
- Pointer movement updates a canvas particle system and inertial optical lens without triggering Solid component rerenders.
- Fast pointer passes were checked in-flight and after settling; the title and metadata remain readable.
- Animation stops advancing while the document is hidden, cleans up listeners/ticker/ResizeObserver on unmount, and lazy-loads GSAP only when the QuantCode surface mounts.
- `prefers-reduced-motion` disables continuous physics and leaves a static, fully usable lens; keyboard-focus styles remain present.
- Responsive check at 1024 × 800 kept primary controls visible and preserved scrolling for lower content.
- Browser console was checked after a clean reload and panel mount: no new application errors.
- `bun run typecheck`: passed.
- `bun run build`: passed; Vite emitted only existing chunking/duplicate-import warnings.
- `bunx oxlint packages/app/src/components/quantcode/panels.tsx packages/app/src/components/quantcode/lens-field.ts`: passed with zero warnings and zero errors.
- `git diff --check`: passed.

final result: passed
