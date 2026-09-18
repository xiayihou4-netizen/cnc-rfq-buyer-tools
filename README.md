# CNC RFQ Buyer Tools

Free tools for industrial buyers preparing CNC machine requests for quotation and reviewing supplier responses.

## Included

- `free/CNC_RFQ_Checklist_Lite.md` — a practical pre-RFQ and quotation review checklist.
- `site/dist/index.html` — a browser-based CNC RFQ brief builder. Information stays in the browser.
- `bounty_scout.py` — a conservative GitHub bounty scanner used to find credible open-source opportunities.
- `tests/` — automated tests for the bounty screening rules.

## Use the RFQ brief builder

Download or clone the repository, then open `site/dist/index.html` in a modern browser. Complete the form and copy the generated English RFQ brief into an email. Review every field before sending and mark unknown technical data as `TBD` instead of guessing.

## Run the bounty scanner

Python 3.12 or later is recommended.

```powershell
python .\bounty_scout.py --limit 8
```

The report is written to `reports/latest.md` and `reports/latest.json`. Authenticated GitHub API requests have a higher rate limit. The included GitHub Actions workflow uses the repository-provided `GITHUB_TOKEN` and runs once a week.

Run the tests with:

```powershell
python -m unittest discover -s tests -v
```

## Safety and scope

The scanner rejects unverified rewards, crowded issues, engagement manipulation, advance-payment requests, and other suspicious patterns. A listed opportunity is still not a payment guarantee.

The RFQ resources are general sourcing aids. Verify all project-specific technical, commercial, legal, tax, customs, and contract information before making a decision.

The paid Excel workbook, email template document, customer delivery ZIP, generation scripts, and private income records are intentionally excluded from this public repository.

