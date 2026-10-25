# Changelog

flo2-calc's changes, newest first. Versions before 0.12.0 are described in the README, where each feature names the
version that added it, and in the commit history.

## 0.12.0 (2026-10-24)

A reply shows a readable decimal beside each exact array result; the kept record stays exact.
(`dec:a-reply-shows-a-readable-decimal-beside-an-exact-array-result`, design `0bee0c00b35845f6`, Anthony's ruling
of 2026-10-24.)

- An exact array writes an element whose decimal does not end as its fraction. The Shop sample trial's monthly net
  energy came back as twelve of them, the first `-4869729231506843861/1575262621733750` kWh.
- Beside each exact array result with such an element, every reply (all four tools) now shows `readable`: the
  elements the reply shows, each fraction rounded half-even to 6 significant digits and each decimal as written. A
  `rendering` label says it is a rendering. That first month now also reads `-3091.38`.
- It mirrors what is shown of the array: every value with a grid's rows kept; or its first, least and greatest; or,
  cut to fit, its first and last.
- It fits the host's answer budget. When the outcome alone is over the budget, a rendering goes before any exact
  value is cut, and `withheld.results` names it. It comes back beside the ends of a result cut to them.
- The record is unchanged. It holds the exact values only, in record schema version 10. The four tools, their
  classes and their arguments are unchanged.
- No new value carries a rendering where its text is already a decimal: a single exact value (already written
  rounded with its `exact` fraction), a rounded value, a float64 array, or an exact array whose elements all end.
