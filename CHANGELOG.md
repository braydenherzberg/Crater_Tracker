# Changelog

## 0.3.0

- Replaced shape-only run selection with event-aware post-event ranking.
- Added seven-frame temporal median review for dust and transient glare.
- Added continuity-constrained surface tracing and reflective-spike rejection.
- Prevented container boundaries from serving as inferred crater rims.
- Capped geometry confidence by measured surface visibility.
- Disabled automatic measurement acceptance when evidence is weak.
- Rebuilt the desktop experience around a large review canvas and restrained
  inspector instead of a dense control dashboard.
- Added optional low-contrast enhancement for review without altering analysis pixels.
- Added regression coverage for hazy reflective footage and flat no-crater surfaces.

## 0.2.0

- Added automatic surface tracking, crater geometry, calibrated metrics,
  candidate search, batch fields, packaging automation, and analysis documentation.
