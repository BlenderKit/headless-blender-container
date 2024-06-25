# Blender Headless Container

Repository for builds of blender-headless (Docker) containers.
These can be used for rendering or other manipulation of Blender files as well as testing.
Containers are available at: https://hub.docker.com/r/blenderkit/headless-blender.

We provide single version container for every release minor Blender version since 2.93.
Multi-version is also provided, this container contains all Blender versions from 2.93 to the most recent.

Now you know all you need.
Details follows if you are interested in development of the images.

## How it is done

This repository is primarily focused on automated builds in Github Actions.
Doing the build locally would require some repetetive work, it could be scripted (pull requests welcomed!), but for us it is not use case we need.

Automated builds are done by Github actions in `.github/workflows/build.yml` file.
You can clone this repo and run it on its own.

### Single version
Containerfile for single version is available in `single-version` folder.
It requires the targeted version of Blender to be extracted in `blender` directory.
Container file pulls image docker.io/accetto/ubuntu-vnc-xfce-opengl-g3 annd just copies `blender` directory into the container.

### Multi version
Multiversion build is chained.
It starts with `Containerfile-blender_2_93` which pulls docker.io/accetto/ubuntu-vnc-xfce-opengl-g3.
`Containerfile-blender_2_93` is then pulled by `Containerfile-blender_3_0`, which is then pulled by `Containerfile-blender_3_1` until we reach latest version.
Result is container image which contains multiple Blender versions.
