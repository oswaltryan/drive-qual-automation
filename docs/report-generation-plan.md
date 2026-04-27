# Report Generation Plan

This plan captures the report-generation rules that are starting to emerge from
the technician workflow. It is intentionally separate from implementation code
until the report shape, pass/warn/fail thresholds, and product coverage rules
are settled.

## Goals

- Generate a readable qualification report from the existing report JSON and
  artifact folders.
- Generate the report as a Word document (`.docx`), matching the desired final
  deliverable instead of producing intermediate HTML or Markdown reports.
- Preserve the existing report JSON as the workflow contract.
- Add deterministic status evaluation so important results are highlighted
  consistently.
- Keep report rendering separate from hardware automation, GUI automation, and
  data collection steps.
- Make partially complete reports obvious without hiding missing data.

## Current Data Sources

- Report JSON:
  `Z:\<part_number>\drive_qualification_report_atomic_tests.json`
- Scope CSV artifacts:
  `Z:\<part_number>\<OS>\In Rush Current\*.csv`
  `Z:\<part_number>\<OS>\Max IO\*.csv`
- Scope screenshots or backups:
  `Z:\<part_number>\<OS>\In Rush Current\*.png`
  `Z:\<part_number>\<OS>\Max IO\*.png`
- Performance artifacts:
  `Z:\<part_number>\<OS>\<tool>\...`

The first report-generation pass should read from the report JSON and link to
existing artifacts. Re-parsing artifacts during rendering should be optional and
reserved for validation or recovery commands.

Report generation must also support offline review from a copied folder. A test
machine may not be connected to the LAN or mounted `Z:\` share, so the generator
should accept a source-root argument that points at a local folder containing the
same per-part-number report/artifact layout.

Example source layouts:

- Fileshare layout:
  `Z:\69-420\drive_qualification_report_atomic_tests.json`
- Copied local layout:
  `C:\Users\<user>\Desktop\reports\69-420\drive_qualification_report_atomic_tests.json`

## Report Sections

The generated Word report should follow the established qualification document
shape from the current reference report:

- `Drive Qualification Report.`
- Revision table
- Drive Info
- Qualification Equipment
- Test Procedure
- Test Results
- Power Data
- Compatibility Data
- Temperature Data
- Disk Performance
- Compliance/Reliability Test
- Datasheet
- Disk Performance Raw Data & Screenshots
- Drive Qualification Result
- Notes and Considerations
- Appendix with per-DUT raw data and measurement tables

## Result Status Model

Report rendering needs a small shared status vocabulary:

- `pass`: result satisfies the threshold.
- `warn`: result is close to a limit or needs review.
- `fail`: result violates a hard limit or indicates an operational failure.
- `missing`: expected data is absent.
- `not_applicable`: result is intentionally not required for this product,
  platform, or material group.

Visual treatment:

- `fail` should render red.
- `warn` should render yellow or amber.
- `missing` should be distinct from `fail` unless the missing value blocks
  qualification.
- If speed drops to `0` or the source indicates an error, temperature testing
  should render red.

## Power Measurement Rules

All power values are stored in milliamps today.

### Max I/O

Current rules:

- `Accum Mean` / RMS current must be less than `1000 mA`.
- Values from `900 mA` through `1000 mA` should be flagged for review.
- Values at or above `1000 mA` should fail.
- Minimum voltage must be greater than `4.7 V`.
- Values at or below `4.7 V` should fail.

Implementation notes:

- The current parser stores Max I/O current from `Meas1 Accum-Max` and
  `Meas3 Accum-Mean`.
- The report currently has fields for current, but not a dedicated minimum
  voltage field.
- Before enforcing the voltage rule, add or confirm a report field for Max I/O
  minimum voltage and define which scope measurement row supplies it.

### In-Rush

Current rules:

- Flag any in-rush current over `900 mA`.

Open decision:

- Confirm whether over `900 mA` is a warning only or a failure.
- If it is a warning, define the hard fail threshold, if any.

## Temperature Testing Rules

Temperature testing is currently scaffolded under:

`temperature -> <DUT> -> performance -> <temperature> -> read_mb_s/write_mb_s`

Current rules:

- If read or write speed drops to `0`, render the result red.
- If the source records an error instead of a numeric speed, render the result
  red.
- Enova products do not need temperature data for every like product.
- For now, cover case-material groups instead of every SKU.

Material coverage:

- Aluminum:
  `Fortress L3`, `Padlock DT`, `Padlock SSD`, `ASK3`, `ASK3-NX`
- Plastic:
  everything else

Implementation notes:

- Add a product-to-case-material classification helper.
- Add a temperature coverage rule that marks untested like products as
  `not_applicable` when a material representative exists.
- Store enough metadata to explain which tested product represents the material
  group.

Open decisions:

- Confirm whether `Fortress` without `L3` should be aluminum or plastic.
- Confirm whether `Padlock DT FIPS` should inherit the `Padlock DT` aluminum
  classification.
- Confirm whether temperature thresholds compare against an initial baseline,
  a minimum absolute speed, or only the zero/error rule for now.

## Data Model Gaps

The current report JSON is enough for first-pass rendering, but these additions
would make status evaluation cleaner:

- Power status fields derived during report generation, not necessarily stored
  in the source JSON.
- Max I/O minimum voltage field per DUT and OS.
- Temperature case-material metadata per DUT.
- Temperature representative metadata, for example:
  `represented_by`, `case_material`, and `coverage_reason`.
- Error fields for temperature measurements, instead of overloading missing or
  zero speeds.

Recommendation: keep derived statuses out of the source report JSON initially.
Generate them in a report evaluation layer so threshold changes do not require
rewriting historical JSON.

## Proposed Implementation Phases

1. Create a report evaluation layer.
   - Input: report JSON.
   - Output: normalized section models with `value`, `status`, and `reason`.
   - No rendering dependency in this layer.

2. Implement power evaluation.
   - Apply Max I/O RMS thresholds.
   - Apply In-Rush threshold once warn/fail behavior is confirmed.
   - Add tests for boundary values: `899`, `900`, `999.9`, `1000`, and missing.

3. Extend power extraction for Max I/O minimum voltage.
   - Identify the scope measurement row and field.
   - Add JSON fields without breaking existing reports.
   - Backfill from saved CSVs where possible.

4. Implement temperature evaluation.
   - Treat `0` speed and explicit errors as `fail`.
   - Add case-material classification.
   - Mark non-representative products as `not_applicable` when covered by a
     representative for the same material group.

5. Build the Word report renderer.
   - Generate `.docx` directly from evaluated report data.
   - Include clear pass/warn/fail/missing summary tables.
   - Use Word table shading or text styling for status colors.
   - Link local artifacts where appropriate, and embed selected screenshots
     only when they add review value.

6. Add a CLI entrypoint.
   - Suggested command: `drive-qual-report-generate`.
   - Inputs: `--part-number`, optional `--source-root`, optional `--output`.
   - `--source-root` should override the default report/artifact root for
     read-only report generation.
   - Keep it import-safe on non-Windows hosts.

7. Add regression tests.
   - Evaluation unit tests for each threshold and material rule.
   - Snapshot or structural tests for generated report sections.
   - Import-boundary tests so report generation does not import Windows-only
     modules.

## Initial Acceptance Criteria

- A user can generate a report for an existing part number without running lab
  automation.
- A user can generate a report from a local copied folder by passing
  `--source-root`.
- Power rows show pass/warn/fail/missing status with reasons.
- Temperature rows show red failures for zero speeds and errors.
- Enova temperature coverage can be represented by case material.
- Missing values are visible and do not silently pass.
- The command works on non-Windows hosts when only report JSON and artifacts are
  being read.
