# Detection results

**Recall** (dependency problems a clean install revealed, flagged by zurix): 29 of 29 = 100.0% (95% Wilson [88.3, 100.0]; task bootstrap [100.0, 100.0])
Distinct mistakes caught every time they appeared: 16 of 16 (100.0%)

- missing_package: 0 of 0 (None%)
- missing_version: 29 of 29 (100.0%)

**Precision** (zurix flags that were real): 29 of 37 = 78.4% (95% Wilson [62.8, 88.6])

| Model | Runs | Broken-dependency runs | % (task bootstrap) | Flagged by zurix | Flagged without a real problem | Check failed without a real dependency problem |
|---|---|---|---|---|---|---|
| claude-haiku-4-5-20251001 | 150 | 29 | 19.3 [8.0, 32.0] | 29 | 6 | 11 {'phantom package': 6, 'suspicious package': 3, 'undeclared import': 2} |
| claude-sonnet-5-5 | 60 | 0 | 0.0 [0.0, 0.0] | 0 | 2 | 4 {'phantom package': 2, 'undeclared import': 2} |

Problems found only by zurix (no install signal, e.g. undeclared imports of missing packages): 0. Other install failures: 0.
