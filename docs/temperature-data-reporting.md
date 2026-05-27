# Temperature Data Reporting

Temperature reporting is modeled as a post-processing step between performance
collection and final DOCX generation.

Current scaffold:

- `drive_qual.core.temperature` owns artifact paths, CSV parsing, chart
  generation, and updates to the report JSON
  `temperature -> <DUT> -> performance` contract.
- `drive_qual.workflows.temperature` owns the operator-facing workflow step.
- `drive-qual-temperature` is the standalone post-process CLI.
- `drive_qual.integrations.instruments.watlow_f4t` contains reusable Watlow F4T
  SCPI polling helpers.

Expected CSV rows use a long format with one operation per row:

```csv
TempRoundedC,Operation,SpeedMiB
-40,read,107.59
-40,write,109.31
```

Supported temperature columns include `TempRoundedC`, `TempRounded`,
`TemperatureC`, and `Temp1`. Supported speed columns include `SpeedMiB`,
`SpeedMeanMiB`, and `SpeedMedianMiB`.

Example:

```powershell
uv run drive-qual temperature --part-number 69-420 --dut "Padlock DT" --csv .\matched.csv
```

If `--chart` is omitted, the command generates a chart from `--csv`. If
`--chart` is provided, that custom PNG is copied instead.

The generated or copied chart is saved to:

```text
Z:\<part_number>\Temperature\<DUT> Temperature Data.png
```

The DOCX generator already embeds matching temperature PNG artifacts and renders
the updated JSON rows in the `Temperature Data` section.
