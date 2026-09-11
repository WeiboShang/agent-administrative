# Third-party notices

The project code, its synthetic datasets, and the third-party materials listed below have
separate copyright and licence terms.

## WorkBench

The external-method evaluation adapts tool-loop semantics from
[WorkBench](https://github.com/olly-styles/WorkBench), pinned at commit
`49c7dfd00c03d384ec59ea57374f50b766aa5613`.

- Licence: MIT
- Copyright: Copyright (c) 2024 MindsDB
- Local notice: [`docs/licenses/WORKBENCH-MIT.txt`](docs/licenses/WORKBENCH-MIT.txt)

Only the loop semantics are adapted. The WorkBench databases and benchmark tasks are not
included.

## CORD

The optional WF3 external-validity script streams the CORD v2 receipt dataset at run time.
Receipt images are excluded from Git. The repository contains cached model predictions and
aggregate measurements produced from the evaluation.

- Dataset: [CORD: A Consolidated Receipt Dataset for Post-OCR Parsing](https://github.com/clovaai/cord)
- Authors: Seunghyun Park, Seung Shin, Bado Lee, Junyeop Lee, Jaeheung Surh, Minjoon Seo,
  and Hwalsuk Lee
- Licence: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
- Paper: *CORD: A Consolidated Receipt Dataset for Post-OCR Parsing* (2019)

## QMSum and AMI

The optional WF1 external-validity script streams the
[`pszemraj/qmsum-cleaned`](https://huggingface.co/datasets/pszemraj/qmsum-cleaned)
dataset at run time. Raw transcripts are excluded from Git. The repository retains derived
model outputs and aggregate abstention measurements.

- The cleaned Hugging Face dataset is marked Apache-2.0.
- The original [QMSum repository](https://github.com/Yale-LILY/QMSum) is MIT-licensed.
- The underlying [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/) is licensed
  under Creative Commons Attribution 4.0 International.
- QMSum citation: Ming Zhong et al., *QMSum: A New Benchmark for Query-based Multi-domain
  Meeting Summarization*, NAACL 2021.

QMSum contains several meeting domains, including AMI product meetings and public committee
meetings. Results from this script should therefore be described as QMSum/AMI diagnostics,
not as an AMI-only benchmark.
