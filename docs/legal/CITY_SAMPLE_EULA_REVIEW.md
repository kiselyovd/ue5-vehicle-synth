# City Sample EULA review

**Reviewed:** 2026-06-08
**Reviewer:** kiselyovd
**Sources:**
- Unreal Engine EULA (Content / For Publishing / For Creators), URL: https://www.unrealengine.com/eula/content
- Fab listing for City Sample (UE-Only Content tag).

## Findings

### Permitted use

Key operative clause (quoted verbatim from the Unreal Engine Content EULA):

> "you may freely Distribute non-interactive linear media products (e.g., broadcast or streamed video files, cartoons, movies, or images) rendered using the Engine Code, and asset files (other than UE-Only Content) developed or used with the Engine Code".

The exclusion "(other than UE-Only Content)" grammatically attaches only to the second coordinated object "asset files", NOT to the first object "images rendered using the Engine Code". Therefore rendered images produced with the engine are freely distributable even when rendered from UE-Only Content like City Sample.

City Sample is tagged "UE-Only Content - Licensed for Use Only with Unreal Engine-based Products", which restricts USE of the raw assets to UE-based products (e.g. no Unity import). This is satisfied because our capture plugin runs inside UE and only rendered PNGs are exported.

### Asset redistribution restrictions

The raw City Sample asset files (.uasset, meshes, textures) may NOT be redistributed. Our dataset ships only rendered PNG frames + JSON keypoint annotations, never UE assets - so we are within the permitted clause and outside the exclusion.

### Derivative renders

Rendered output is explicitly permitted to be distributed by the operative clause above. The exclusion for UE-Only Content does not reach rendered images; it reaches only redistributed asset files. Our pipeline emits only renders (PNG) and our own annotations (JSON), so derivative renders are cleared for publication.

### AI / NoAI note

The Fab NoAI tag means "must not be used for generative AI data collection". Our model is a discriminative keypoint detector, not generative AI, so it is out of NoAI scope. Nonetheless verify the City Sample Fab listing has no NoAI tag at dataset-generation time.

## Decision

- [x] **Path A - Cleared.** Synthetic renders can be published under Apache 2.0 with attribution to Epic Games City Sample. Proceed with Phase 0.
- [ ] **Path B - Ambiguous.** File a clarification ticket with Epic Legal via the support form. Document ticket number. Pause Phase 0 dataset generation until response. Plugin and Python tooling work (Tasks 2-22) can proceed in parallel.
- [ ] **Path C - Blocked.** EULA explicitly forbids derivative training data redistribution. Pivot renderer to CARLA (BSD license, no restrictions). Update spec accordingly. Tasks 7-21 (UE5 plugin) become CARLA equivalents. Re-plan.

Synthetic renders can be published (Apache-2.0 labels/code, attribution to Epic Games City Sample, no assets redistributed). Proceed with Phase 0.

An optional hardening step is to email Fab/Epic support for written confirmation; this is not a blocker. CARLA (BSD) remains the fallback only if Epic ever replies negatively.

## Attribution template

If Path A: every published dataset includes the attribution block:

> Renders in this dataset were produced using assets from Epic Games' City Sample project (https://www.unrealengine.com/marketplace/en-US/product/city-sample), used under the Epic Games Marketplace EULA. Original assets are not redistributed; only renders derived from them.
