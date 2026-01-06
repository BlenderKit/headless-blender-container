# Blender Headless Container

A repository providing Docker containers for headless Blender builds.

Single-version containers are available for every minor release of Blender since 2.93, including both official releases and pre-release versions (alpha, beta, and release candidates) of upcoming Blender versions.

These can be used for rendering or other manipulation of Blender files as well as testing.
Containers are available at on Docker https://hub.docker.com/r/blenderkit/headless-blender and also in Github Container Registry https://github.com/BlenderKit/headless-blender-container/pkgs/container/headless-blender. 

NOTE: multi-version variant of the container which contained all the Blender versions in one image was also provided.
Due to size constraints of Github Actions and Docker Hub and low usage of this image, this variant is no longer built or provided.
Please use single version images instead, or feel free to fork at https://github.com/BlenderKit/blenderkit_asset_tasks/tree/a2f0f13225b01e90ada5a39e9346b7f03aa83f30 and build your own multi-version image if you need it.

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
	- You can skip dependency installation with `-SkipDependencyInstall` when re-running quickly.

### Single version
Containerfile for single version is available in `single-version` folder, however the latest and actually used version is in build.py in SINGLE_CONTAINERFILE variable.

Containerfile requires the targeted version of Blender to be extracted in `blender` directory.
Container file pulls image docker.io/accetto/ubuntu-vnc-xfce-opengl-g3 annd just copies `blender` directory into the container.
