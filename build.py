import os
import subprocess
import requests
import pathlib
import tarfile
import shutil
import get_blender_release as gbr


def build_containers():
    releases = gbr.get_stable_and_prereleases(os="linux", arch="x64", min_ver=(2, 93))
    releases = gbr.order_releases(releases)
    prev_version = None
    for i, release in enumerate(releases):
        ok = build_container(release.url, release.version, release.stage)
        if ok:
            print(f"✅ {release.version} {release.stage} single build OK")
        else:
            print(f"❌ {release.version} {release.stage} single build FAILED")
        
        if i == 0:
            ok = multi_start(release.url, release.version, release.stage)
            if ok:
                print(f"✅ {release.version} {release.stage} multi build OK")
            prev_version = release.version
            continue

        ok = multi_add(release.url, release.version, release.stage, prev_version)
        if ok:
            print(f"✅ {release.version} {release.stage} multi build OK")
        else:
            print(f"❌ {release.version} {release.stage} multi build FAILED")
        
        if i == len(releases) - 1:
            ok = multi_push(release.version)

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


SINGLE_CONTAINERFILE = """FROM docker.io/accetto/ubuntu-vnc-xfce-opengl-g3
USER root

RUN apt-get update && apt-get install -y git unzip ca-certificates

ADD blender blender
LABEL blender_version={x}.{y}.{z}

ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
"""

def generate_single_containerfile(version):
    """Generate single version Containerfile. Single version Container contais just one version of Blender."""
    dockerfile = SINGLE_CONTAINERFILE.format(
        x=version[0],
        y=version[1],
        z=version[2]
    )
    return dockerfile

MULTI_CONTAINERFILE = """FROM blender_3_6
USER root

ADD {x}.{y} /home/headless/blenders/{x}.{y}
"""

def copy_containerfile(build_dir):
    src = os.path.join(os.path.dirname(__file__), "single-version", "Containerfile")
    dst = os.path.join(build_dir, "Containerfile")
    print(f"- copying {src} -> {dst}")
    shutil.copyfile(src, dst)


def build_container(url: str, version: tuple, stage: str) -> bool:
    """Build Single version Blender container."""
    if type(version) != tuple:
        print(f"Invalid version {version}")
        return False
    
    print(f"=== Building {version} ===")
    build_dir = os.path.join(os.path.dirname(__file__), "build", f"{version[0]}.{version[1]}")
    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    download_file(url, tar_path)
    extract_tar(tar_path, build_dir)

    #containerfile_path = os.path.join((os.path.dirname(__file__)), "single-version", "Containerfile")
    contairfile = generate_single_containerfile(version)
    print("build dir is", build_dir)
    os.chdir(build_dir)
    pb = subprocess.Popen(
        [
            'podman', 'build',
            '-t', f'blenderkit/headless-blender:blender-{version[0]}.{version[1]}',
            #'--label', f'blender_version={xyz}', # --label not working on podman 3, which is defailt on ubuntu/latest
            #'--label', f'stage={stage}',
            '-'
        ],
        cwd=build_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        )
    
    stdout, stderr = pb.communicate(input=contairfile.encode('utf-8'))
    print(f"STDOUT: '{stdout.decode()}'")
    print(f"STDERR: '{stderr.decode()}'")
    if pb.returncode!= 0:    
        return False
    print("-> BUILD DONE")
    
    shutil.rmtree(build_dir)

    pp = subprocess.run(['podman', 'push', f'blenderkit/headless-blender:blender-{version[0]}.{version[1]}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print( 'exit status:', pp.returncode )
    print( 'stdout:', pp.stdout.decode() )
    print( 'stderr:', pp.stderr.decode() )
    if pp.returncode!= 0:
        return False
    print("-> PUSH DONE")
    return True


def multi_start(url: str, version: tuple, stage: str) -> bool:
    """Build first image of multiversion Blender container.
    Later images ADD blenders to this base image."""
    print(f"=== Building base multi {version} ===")
    return True

def multi_add(url: str, version: tuple, stage: str, prev_version=tuple) -> bool:
    """ADD Blender to previous multiversion image."""
    print(f"=== Adding Blender {version} to multi {prev_version} ===")
    return True

def multi_push(version: tuple) -> bool:
    """Push multiversion Blender container."""
    print(f"=== Pushing multi {version} ===")
    return True


if __name__ == '__main__':
    build_containers()
