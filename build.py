import os
import subprocess
import requests
import tarfile
import shutil
import get_blender_release as gbr


def build_prereleases():
    prereleases = gbr.get_blender_prereleases(os="linux", arch="x64")
    for prerelease in reversed(prereleases):
        build_container(prerelease.url, prerelease.version)

def download_file(url, dst):
    if os.path.exists(dst):
        print(f"- skipping download, {dst} exists")
        return

    print(f"- downloading {url} to {dst}", end="")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dst, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    print("✅ download complete")


def extract_tar(tar_path, target_dir):
    dst = os.path.join(target_dir, "blender")
    if os.path.exists(dst):
        print(f"- skipping extraction, {dst} exists")
        return

    print(f"- extracting {tar_path} -> {target_dir}")
    with tarfile.open(tar_path) as tar:
        tar.extractall(path=target_dir)

    for item in os.listdir(target_dir):
        if item == "blender.tar.xz":
            continue
        src = os.path.join(target_dir, item)
        print(f"- moving {src} -> {dst}")
        shutil.move(src, dst)
    print("✅ extraction complete")

def generate_dockerfile(version):
    """Generate """
    x = version[0]
    y = version[1]
    dockerfile = f"""
FROM docker.io/accetto/ubuntu-vnc-xfce-opengl-g3
USER root
RUN apt-get update && apt-get install -y git unzip ca-certificates python3-pip
ADD {x}.{y}/blender /home/headless/blenders/{x}.{y}
ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
"""


def build_container(url, version: tuple):
    if type(version) != tuple:
        raise ValueError("Version must be a tuple (major, minor, patch)")
    print(f"--- Building {version} ---")

    version = f"{version[0]}.{version[1]}"
    build_dir = os.path.join("build", version)
    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    download_file(url, tar_path)
    
    extract_tar(tar_path, build_dir)
    
    print("file is:", __file__)
    cf_path = os.path.join((os.path.dirname(__file__)), "single-version", "Containerfile")
    out = subprocess.run(['podman', 'build', '-f', cf_path, '-t', f'blenderkit/headless-blender:blender-{version}'], cwd=build_dir, check=True)
    print(out)
    out = out = subprocess.run(['podman', 'push', 'blenderkit/headless-blender:blender-{version}'], check=True)
    print(out)
    print("--- Done ---")

if __name__ == '__main__':
    build_prereleases()

