# Blender Headless Container

Repository for builds of blender-headless (Docker) containers.
These can be used for rendering or other manipulation of Blender files as well as testing.
Containers are available at: https://hub.docker.com/r/blenderkit/headless-blender.

We provide single version container for every release minor Blender version since 2.93.
Multi-version is also provided, this container contains all Blender versions from 2.93 to the most recent.

Now you know all you need.
Details follows if you are interested in development of the images.

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
	- You can skip dependency installation with `-SkipDependencyInstall` when re-running quickly.

### Single version
Containerfile for single version is available in `single-version` folder.
It requires the targeted version of Blender to be extracted in `blender` directory.
Container file pulls image docker.io/accetto/ubuntu-vnc-xfce-opengl-g3 annd just copies `blender` directory into the container.

### Multi version
Multiversion build is chained.
It starts with `Containerfile-blender_2_93` which pulls docker.io/accetto/ubuntu-vnc-xfce-opengl-g3.
`Containerfile-blender_2_93` is then pulled by `Containerfile-blender_3_0`, which is then pulled by `Containerfile-blender_3_1` until we reach latest version.
Result is container image which contains multiple Blender versions.
