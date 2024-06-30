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
    print(" ...done ✅")


def extract_tar(tar_path, target_dir):
    dst = os.path.join(dst, "blender")
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
        print(f"moving {src} -> {dst}")
        shutil.move(src, dst)
    print(" ...done ✅")

def generate_dockerfile(version):
    dockerfile = f"""
    FROM fedora:34"""


def build_container(url, version: tuple):
    if type(version) != tuple:
        raise ValueError("Version must be a tuple (major, minor, patch)")
    print(f"--- Building {version} ---")
    version = f"{version[0]}.{version[1]}"
    build_dir = os.path.join("build", version)
    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    download_file(url, tar_path)
    
    dst = os.path.join(build_dir, "blender")
    if not os.path.exists(dst):
        extract_tar(tar_path, build_dir, dst)

    #subprocess.run(['podman', 'build', '-f', './single-version/Containerfile', '-t', 'blenderkit/headless-blender:blender-4.0'], check=True)
    #subprocess.run(['podman', 'push', 'blenderkit/headless-blender:blender-4.0'], check=True)

if __name__ == '__main__':
    build_prereleases()

