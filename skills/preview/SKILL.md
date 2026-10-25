---
name: preview
description: Render Markdown or LaTeX research artifacts to HTML or PDF with pandoc. Use when the user wants to review a written artifact, export a report, or view a rendered document. Escopo: apenas artefatos de pesquisa sob `<slug>/`.
---

# Preview

Render Markdown or LaTeX artifacts with pandoc through the shell. `feynman setup preview` checks for pandoc, and `feynman doctor` reports whether it is available.

```bash
pandoc <slug>/outputs/<slug>.md -s -o <slug>/outputs/<slug>.html   # HTML
pandoc <slug>/outputs/<slug>.md -o <slug>/outputs/<slug>.pdf       # PDF (needs a LaTeX engine)
open <slug>/outputs/<slug>.html                             # macOS; xdg-open on Linux
```

Rendered HTML and PDF files are previews; the Markdown artifact stays canonical. If pandoc or a LaTeX engine is missing, say so and leave the Markdown artifact as the deliverable.
