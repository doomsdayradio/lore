# lore

This repository is part of the Doomsday Radio multi-repo migration.

## Purpose
Canonical lore, world model, generated lore site, and MCP integration.

## Source relationship
This repo is intentionally separated from the monorepo so it can be built, tested, and deployed independently.

## Notes
- Keep product logic, tests, and deployment config in this repo.
- Prefer stable public URLs or versioned contracts over relative cross-repo links.
- Only radio-specific assets belong in Bunny Storage; non-radio assets may remain in the repo.

## Build and Deployment

The repository builds the static Lore website directly from `content/story` into HTML, generates the sitemap and deploys to Bunny CDN under the `/lore/` path.

### Local Build

```bash
pip install markdown
python build_lore_html.py --output dist
python generate_sitemap.py --docs-root dist --base-url https://doomsday.radio/lore
```

The generated HTML can be checked for the shared, privacy-aware analytics
loader without changing files:

```bash
python inject_umami_loader.py --docs-root dist --check
```

Run the unit tests with:

```bash
python -m unittest -v
```

### EPUB migration status

`build_epub.py` contains the legacy EPUB generator for selected stories. Its
input and output paths still assume the former monorepo layout, so it is not
part of the supported local build above. Migrate those paths before using it as
an independent repository tool.

### Bunny Deployment

The `main` branch deploys automatically to Bunny S3 (`s3://${BUNNY_STORAGE_ZONE}/lore/`) via GitHub Actions.

Required GitHub Variables and Secrets (same as `site`):
- Variable: `BUNNY_STORAGE_ENDPOINT` (e.g. `https://de-s3.storage.bunnycdn.com`)
- Variable: `BUNNY_STORAGE_ZONE`
- Secret: `BUNNY_STORAGE_PASSWORD`
