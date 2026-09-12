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
