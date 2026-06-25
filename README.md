# Blender Headless Container

A repository providing Docker containers for headless Blender builds.

Single-version containers are available for every minor release of Blender since 2.93, including both official releases and pre-release versions (alpha, beta, and release candidates) of upcoming Blender versions.

These can be used for rendering or other manipulation of Blender files as well as testing.
Containers are available at on Docker https://hub.docker.com/r/blenderkit/headless-blender and also in Github Container Registry https://github.com/BlenderKit/headless-blender-container/pkgs/container/headless-blender.

NOTE: a multi-version variant of the container which contains many Blender versions in one image is also available as `blenderkit/headless-blender:multi-version`.
It bundles the latest stable patch of every minor release (>= 2.93) at `/home/headless/blenders/X.Y`. Prerelease builds (alpha/beta/rc) are intentionally skipped, and only the newest patch of each minor version is kept.
Because this image is large, it is not built on every CI run; build it on demand (see "Multi-version" below). If you prefer not to maintain it yourself, you can fork at https://github.com/BlenderKit/blenderkit_asset_tasks/tree/a2f0f13225b01e90ada5a39e9346b7f03aa83f30.

## How it is done

This repository is primarily focused on automated builds in Github Actions, but you can also rehearse the workflow locally if you need to debug issues before pushing changes.

Automated builds are done by Github actions in `.github/workflows/build.yml` file.
You can clone this repo and run it on its own. By default the pipeline iterates releases from oldest to newest to ensure legacy builds still run, but you can flip the direction by exporting `REVERSE_BUILD_ORDER=1` before calling `build.py` (our reverse-order workflow in CI does this). When debugging locally you can also resume from a specific release via `START_VERSION` (example: `START_VERSION=4.2 pwsh -File scripts/local-workflow.ps1`).

### Local dry run (Windows or PowerShell)

1. Install Python 3.10+ and Docker Desktop (or Podman) and make sure both `python` and `docker` are on your `PATH`.
2. Login to the registry you plan to push to (`docker login docker.io` or equivalent). If you only want to test the build flow locally, you can skip pushing.
3. From the repository root, run:

	```powershell
	pwsh -File scripts/local-workflow.ps1 -Registry docker.io -Runtime docker
	```

	- The script mirrors the CI steps: checks free disk space, installs Python dependencies, prints `docker info`, and calls `python build.py`.
	- Pushing images is disabled by default (`SKIP_IMAGE_PUSH=1`). Pass `-PushImages` to enable it.
	- Set `-Runtime podman` if you have Podman installed instead of Docker.
	- Pass `-ReverseOrder` to build newest releases first (sets `REVERSE_BUILD_ORDER=1`).
	- Built images are kept locally by default so you can inspect them (the script sets `KEEP_IMAGES=1`). Pass `-RemoveImages` to delete each image after building to save disk space.
	- You can skip dependency installation with `-SkipDependencyInstall` when re-running quickly.

### Single version
Containerfile for single version is available in `single-version` folder, however the latest and actually used version is in build.py in SINGLE_CONTAINERFILE variable.

Containerfile requires the targeted version of Blender to be extracted in `blender` directory.
Container file pulls image docker.io/accetto/ubuntu-vnc-xfce-opengl-g3 annd just copies `blender` directory into the container.

### Multi-version
The multi-version image bundles the latest stable patch of every minor Blender release (>= 2.93) into a single image, each at `/home/headless/blenders/X.Y`. All prereleases (alpha/beta/rc) are skipped.

It is built by layering versions oldest -> newest (each version is added on top of the previous image) and the final image is tagged `blenderkit/headless-blender:multi-version`.

Because the result is large, build it on demand rather than on every CI run. Set `BUILD_MULTI=1` to switch `build.py` from single-version builds to the multi-version build:

```powershell
# local dry run (no push)
pwsh -File scripts/local-workflow.ps1 -Multi -Registry docker.io -Runtime docker

# build and push
pwsh -File scripts/local-workflow.ps1 -Multi -PushImages -Registry docker.io -Runtime docker
```

Or directly:

```powershell
$env:BUILD_MULTI = "1"; python build.py
```

When run via `scripts/local-workflow.ps1` the built images are kept locally by default so you can inspect them, e.g. `docker run --rm -it blenderkit/headless-blender:multi-version ls /home/headless/blenders` (pass `-RemoveImages` to clean them up instead). Note that `build.py` on its own removes images after building unless `KEEP_IMAGES=1` is set.

Make sure the build host has plenty of free disk space; the accumulated image grows with every version added (raise `MIN_FREE_GB` accordingly). `REVERSE_BUILD_ORDER` and `START_VERSION` do not apply to the multi-version build because the layered chain must be built oldest -> newest.
