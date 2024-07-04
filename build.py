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
        build_dir = os.path.join(os.path.dirname(__file__), "build", f"{release.version[0]}.{release.version[1]}")
        ok = build_container(release.url, release.version, release.stage, build_dir)
        if ok:
            print(f"✅ {release.version} {release.stage} single build OK")
        else:
            print(f"❌ {release.version} {release.stage} single build FAILED")
        
        if i == 0:
            ok = multi_start(release.url, release.version, release.stage, build_dir)
            if ok:
                print(f"✅ {release.version} {release.stage} multi build OK")
            prev_version = release.version
            shutil.rmtree(build_dir)
            continue

        ok = multi_add(release.url, release.version, prev_version, build_dir)
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
LABEL blender_version={x}.{y}.{z} blender_stage={stage}
ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
"""

def generate_single_containerfile(version: tuple, stage: str):
    """Generate single version Containerfile. Single version Container contais just one version of Blender."""
    dockerfile = SINGLE_CONTAINERFILE.format(
        x=version[0],
        y=version[1],
        z=version[2],
        stage=stage,
    )
    return dockerfile

ADD_CONTAINERFILE = """FROM blender_{prev_x}_{prev_y}
USER root
ADD blender /home/headless/blenders/{x}.{y}
"""

def generate_add_containerfile(version, prev_version):
    """Generate Containerfile which adds blender to existing image. Used to create multi version image."""
    dockerfile = ADD_CONTAINERFILE.format(
        x=version[0],
        y=version[1],
        prev_x=prev_version[0],
        prev_y=prev_version[1]
    )
    return dockerfile


def copy_containerfile(build_dir):
    src = os.path.join(os.path.dirname(__file__), "single-version", "Containerfile")
    dst = os.path.join(build_dir, "Containerfile")
    print(f"- copying {src} -> {dst}")
    shutil.copyfile(src, dst)


def build_container(url: str, version: tuple, stage: str, build_dir: str) -> bool:
    """Build Single version Blender container."""
    if type(version) != tuple:
        print(f"Invalid version {version}")
        return False
    
    print(f"=== Building {version} ===")
    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    download_file(url, tar_path)
    extract_tar(tar_path, build_dir)

    containerfile = generate_single_containerfile(version, stage)
    cfpath = os.path.join(build_dir, "Containerfile")
    with open(cfpath, "w") as file:
        file.write(containerfile)

    print(os.listdir(build_dir))
    cmd = [
        'podman', 'build',
        '-f', cfpath,
        '-t', f'blenderkit/headless-blender:blender-{version[0]}.{version[1]}',
        '.'
    ]
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,)

    print( 'exit status:', pb.returncode )
    print( 'stdout:', pb.stdout.decode() )
    print( 'stderr:', pb.stderr.decode() )
    if pb.returncode!= 0:    
        return False
    print("-> BUILD DONE")

    pp = subprocess.run(['podman', 'push', f'blenderkit/headless-blender:blender-{version[0]}.{version[1]}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print( 'exit status:', pp.returncode )
    print( 'stdout:', pp.stdout.decode() )
    print( 'stderr:', pp.stderr.decode() )
    if pp.returncode!= 0:
        return False
    print("-> PUSH DONE")
    return True


def multi_start(url: str, version: tuple,  stage: str, build_dir: str) -> bool:
    """Build first image of multiversion Blender container.
    Later images ADD blenders to this base image."""
    print(f"=== Building base multi {version} ===")

    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    download_file(url, tar_path)
    extract_tar(tar_path, build_dir)

    containerfile = generate_single_containerfile(version, stage)
    cfpath = os.path.join(build_dir, "Containerfile")
    with open(cfpath, "w") as file:
        file.write(containerfile)
    
    print(os.listdir(build_dir))
    cmd = [
        'podman', 'build',
        '-f', cfpath,
        '-t', f'blenderkit/headless-blender:blender_{version[0]}_{version[1]}', #non-production tag, for multiversion only
        '.'
    ]
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    print( 'exit status:', pb.returncode )
    print( 'stdout:', pb.stdout.decode() )
    print( 'stderr:', pb.stderr.decode() )
    if pb.returncode!= 0:
        return False
    print("-> BUILD DONE")

    return True

def multi_add(url: str, version: tuple, prev_version:tuple, build_dir:str) -> bool:
    """ADD Blender to previous multiversion image."""
    print(f"=== Adding Blender {version} to multi {prev_version} ===")

    
    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    download_file(url, tar_path)
    extract_tar(tar_path, build_dir)

    containerfile = generate_add_containerfile(version, prev_version)
    cfpath = os.path.join(build_dir, "Containerfile")

    with open(cfpath, "w") as file:
        file.write(containerfile)

    print(os.listdir(build_dir))
    cmd = ['podman', 'build', '-f', cfpath, '-t', f'blenderkit/headless-blender:blender_{version[0]}_{version[1]}', '.']
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run( cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    print( 'exit status:', pb.returncode )
    print( 'stdout:', pb.stdout.decode() )
    print( 'stderr:', pb.stderr.decode() )
    if pb.returncode!= 0:
        return False
    return True

def multi_push(version: tuple) -> bool:
    """Push multiversion Blender container."""
    print(f"=== Pushing multi {version} ===")
    cmd = ['podman', 'push', f'blenderkit/headless-blender:blender_{version[0]}_{version[1]}']
    print(f"- running command {' '.join(cmd)}")
    pp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print( 'exit status:', pp.returncode )
    print( 'stdout:', pp.stdout.decode() )
    print( 'stderr:', pp.stderr.decode() )
    if pp.returncode!= 0:
        return False
    print("-> MULTI-VERSION PUSH DONE")
    return True


if __name__ == '__main__':
    build_containers()
