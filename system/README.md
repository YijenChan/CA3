# CA3 local UI

Run the bundled synthetic interface example from the repository root:

```bash
python -m system.ca3_system.serve
```

The browser only renders a validated run bundle. It does not perform scientific
inference. `static/data/case-study.json` is deliberately synthetic and must not
be cited as an experimental result.

For a local authorized run, `ca3_system.pipeline` converts saved round artifacts
into the same JSON contract. Keep its config, evidence paths, and generated data
outside version control, then pass the local config to the server with
`--config`.
