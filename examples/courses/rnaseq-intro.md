---
title: RNA-seq introduction
slug: rnaseq-introduction
description: A minimal live lesson with a Markdown page and a quiz.
---

# RNA-seq

RNA-seq measures RNA abundance across a transcriptome.

---

:::quiz
id: deseq2-input
type: single_choice
question: |
  Which input does DESeq2 model?
choices:
  - TPM
  - FPKM
  - Raw counts
  - Z-score
answer:
  - Raw counts
explanation: |
  DESeq2 models raw count data.
:::
