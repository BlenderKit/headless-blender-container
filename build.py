import os
import subprocess
import requests
import tarfile
import shutil
import get_blender_release as gbr


MIN_FREE_GB = float(os.environ.get("MIN_FREE_GB", "12"))
CONTAINER_RUNTIME = os.environ.get("CONTAINER_RUNTIME", "podman")
SKIP_IMAGE_PUSH = os.environ.get("SKIP_IMAGE_PUSH") == "1"
REVERSE_BUILD_ORDER = os.environ.get("REVERSE_BUILD_ORDER") == "1"

def runtime_cmd(*args):
        return [CONTAINER_RUNTIME, *args]

def build_containers(registry: str):
    releases = gbr.get_stable_and_prereleases(os="linux", arch="x64", min_ver=(2, 93))
    releases = list(gbr.order_releases(releases))
    if REVERSE_BUILD_ORDER:
        releases = list(reversed(releases))
        print("-> REVERSE_BUILD_ORDER=1, building newest to oldest")
    else:
        print("-> Building oldest to newest (default)")
    start_version = os.environ.get("START_VERSION")
    if start_version:
        try:
            start_tuple = tuple(int(part) for part in start_version.split('.'))
            if REVERSE_BUILD_ORDER:
                releases = [r for r in releases if r.version <= start_tuple]
            else:
                releases = [r for r in releases if r.version >= start_tuple]
            print(f"-> START_VERSION={start_version}, remaining releases: {len(releases)}")
        except ValueError:
            print(f"-> WARNING: invalid START_VERSION '{start_version}', ignoring filter")
    prev_version = None
    for i, release in enumerate(releases):
        print(f"\n\n\n====== Blender {release.version} ======")

        log_disk_usage(f"before {release.version}")
        ensure_disk_headroom(MIN_FREE_GB)

        build_dir = os.path.join(os.path.dirname(__file__), "build", f"{release.version[0]}.{release.version[1]}")
        ok = build_container(release.url, release.version, release.stage, build_dir, registry)
        if ok:
            print(f"✅ {release.version} {release.stage} single build OK")
        else:
            print(f"❌ {release.version} {release.stage} single build FAILED")

        if i == 0:
            ok = multi_start(release.url, release.version, release.stage, build_dir)
            prev_version = release.version
            if ok:
                print(f"✅ {release.version} {release.stage} multi build starter OK")
            else:
                print(f"❌ {release.version} {release.stage} multi build starter FAILED")
            clean_build_dir(build_dir)
            log_disk_usage(f"after cleanup {release.version}")
            if ok:
                print("-> Skipping prune to keep base multi image for next layer")
            else:
                prune_podman_storage(f"post {release.version}")
            continue

        ok = multi_add(release.url, release.version, prev_version, build_dir)
        if ok:
            print(f"✅ {release.version} {release.stage} multi build OK")
            remove_image(f"blender_{prev_version[0]}_{prev_version[1]}")
            prev_version = release.version
        else:
            print(f"❌ {release.version} {release.stage} multi build FAILED")
        clean_build_dir(build_dir)
        log_disk_usage(f"after cleanup {release.version}")
        if ok:
            prune_podman_storage(f"post {release.version}")
        else:
            print("-> Skipping prune to keep previous multi image intact")

        if i == len(releases) - 1:
            ok = multi_push(release.version, registry)
            if ok:
                prune_podman_storage("post multi push")


def clean_build_dir(dir: str):
    if os.path.isdir(dir):
        shutil.rmtree(dir)
        print(f"-> CLEANED directory {dir}")
    else:
        print(f"-> SKIPPED cleanup, directory {dir} not found")


def download_file(url, dst, force=False):
    if os.path.exists(dst):
        if force:
            os.remove(dst)
        else:
            print(f"- skipping download, {dst} exists")
            return

    print(f"- downloading {url} to {dst}", end="")
    tmp_dst = dst + ".tmp"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(tmp_dst, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    print("✅ download complete")
    os.replace(tmp_dst, dst)


def extract_tar(tar_path, target_dir):
    dst = os.path.join(target_dir, "blender")
    if os.path.exists(dst):
        print(f"- skipping extraction, {dst} exists")
        return

    print(f"- validating archive {tar_path}")
    with tarfile.open(tar_path) as tar:
        try:
            tar.getmembers()
        except EOFError:
            print("-> ERROR: archive truncated, deleting and retrying download")
            os.remove(tar_path)
            raise RuntimeError("Corrupted archive")

    print(f"- extracting {tar_path} -> {target_dir}")
    with tarfile.open(tar_path) as tar:
        if os.name == "nt":
            safe_extract_with_symlink_copy(tar, target_dir)
        else:
            tar.extractall(path=target_dir)

    for item in os.listdir(target_dir):
        if item == "blender.tar.xz":
            continue
        src = os.path.join(target_dir, item)
        print(f"- moving {src} -> {dst}")
        shutil.move(src, dst)
    print("✅ extraction complete")


def safe_extract_with_symlink_copy(tar: tarfile.TarFile, target_dir: str):
    for member in tar.getmembers():
        try:
            tar.extract(member, target_dir)
        except OSError as exc:
            win_err = getattr(exc, "winerror", None)
            if win_err == 1314 and (member.issym() or member.islnk()):
                print(f"-> symlink fallback for {member.name} -> {member.linkname}")
                copy_link_target(tar, member, target_dir)
            else:
                raise


def copy_link_target(tar: tarfile.TarFile, member: tarfile.TarInfo, target_dir: str):
    try:
        target_member = tar.getmember(member.linkname)
    except KeyError:
        print(f"-> WARNING: link target {member.linkname} missing; skipping {member.name}")
        return

    dest_path = os.path.join(target_dir, member.name)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    if target_member.isdir():
        tar.extract(target_member, target_dir)
        source_dir = os.path.join(target_dir, target_member.name)
        if os.path.exists(dest_path):
            shutil.rmtree(dest_path)
        shutil.copytree(source_dir, dest_path)
        return

    extracted_path = os.path.join(target_dir, target_member.name)
    if not os.path.exists(extracted_path):
        tar.extract(target_member, target_dir)

    fileobj = tar.extractfile(target_member)
    if fileobj is None:
        with open(extracted_path, 'rb') as src, open(dest_path, 'wb') as dst:
            shutil.copyfileobj(src, dst)
    else:
        with fileobj as src, open(dest_path, 'wb') as dst:
            shutil.copyfileobj(src, dst)


SINGLE_CONTAINERFILE = """FROM docker.io/accetto/ubuntu-vnc-xfce-opengl-g3
USER root
RUN apt-get update && apt-get install -y git unzip ca-certificates
ADD blender blender
LABEL blender_version={x}.{y}.{z} blender_stage={stage}
ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
"""

def generate_single_containerfile(version: tuple, stage: str):
    """Generate single version Containerfile. Single version Container contains just one version of Blender."""
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


def build_container(url: str, version: tuple, stage: str, build_dir: str, registry: str) -> bool:
    """Build Single version Blender container and push it into the registry."""
    if type(version) != tuple:
        print(f"Invalid version {version}")
        return False

    print(f"=== Building {version} ===")
    os.makedirs(build_dir, exist_ok=True)

    tar_path = os.path.join(build_dir, "blender.tar.xz")
    attempts = 2
    for attempt in range(attempts):
        download_file(url, tar_path, force=attempt > 0)
        try:
            extract_tar(tar_path, build_dir)
            break
        except RuntimeError as exc:
            if attempt == attempts - 1:
                print(f"-> FAILED extraction after retry: {exc}")
                return False
            print("-> Retrying download due to extraction failure")
            continue

    containerfile = generate_single_containerfile(version, stage)
    cfpath = os.path.join(build_dir, "Containerfile")
    with open(cfpath, "w") as file:
        file.write(containerfile)

    print(os.listdir(build_dir))
    cmd = runtime_cmd(
        'build',
        '-f', cfpath,
        '-t', f'{registry}/blenderkit/headless-blender:blender-{version[0]}.{version[1]}',
        '.'
    )
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run(cmd, cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,)

    print( 'exit status:', pb.returncode )
    print( 'stdout:', pb.stdout.decode() )
    print( 'stderr:', pb.stderr.decode() )
    if pb.returncode!= 0:
        return False
    print("-> SINGLE BUILD DONE")

    if SKIP_IMAGE_PUSH:
        print("-> SKIPPING PUSH (SKIP_IMAGE_PUSH=1)")
    else:
        print("-> PUSHING SINGLE IMAGE")
        push_cmd = runtime_cmd('push', f'{registry}/blenderkit/headless-blender:blender-{version[0]}.{version[1]}')
        pp = subprocess.run(
            push_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print( 'exit status:', pp.returncode )
        print( 'stdout:', pp.stdout.decode() )
        print( 'stderr:', pp.stderr.decode() )
        if pp.returncode!= 0:
            return False
        print("-> PUSH DONE")

    remove_image(f"{registry}/blenderkit/headless-blender:blender-{version[0]}.{version[1]}")

    return True


def multi_start(url: str, version: tuple,  stage: str, build_dir: str) -> bool:
    """Build first image of multiversion Blender container.
    Later images ADD blenders to this base image via function multi_add().
    """
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
    cmd = runtime_cmd('build', '-f', cfpath, '-t', f'blender_{version[0]}_{version[1]}:latest', '.')
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run(cmd, cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print( 'exit status:', pb.returncode )
    print( 'stdout:', pb.stdout.decode() )
    print( 'stderr:', pb.stderr.decode() )
    if pb.returncode!= 0:
        return False
    print("-> BUILD DONE")

    return True

def multi_add(url: str, version: tuple, prev_version:tuple, build_dir:str) -> bool:
    """ADD Blender to already existing multiversion image."""
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
    cmd = runtime_cmd('build', '-f', cfpath, '-t', f'blender_{version[0]}_{version[1]}:latest', '.')
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run(cmd, cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print( 'exit status:', pb.returncode )
    print( 'stdout:', pb.stdout.decode() )
    print( 'stderr:', pb.stderr.decode() )
    if pb.returncode!= 0:
        return False
    return True

def multi_push(version: tuple, registry: str) -> bool:
    """Push multiversion Blender container."""
    print(f"=== Pushing multi {version} as headless-blender:multi-version ===")
    if SKIP_IMAGE_PUSH:
        print("-> SKIPPING MULTI PUSH (SKIP_IMAGE_PUSH=1)")
        return True
    cmd = runtime_cmd("image", "tag", f"blender_{version[0]}_{version[1]}", f"{registry}/blenderkit/headless-blender:multi-version")
    print(f"- running command {' '.join(cmd)}")
    pt = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print( 'exit status:', pt.returncode )
    print( 'stdout:', pt.stdout.decode() )
    print( 'stderr:', pt.stderr.decode() )

    cmd = runtime_cmd('push', f'{registry}/blenderkit/headless-blender:multi-version')
    print(f"- running command {' '.join(cmd)}")
    pp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print( 'exit status:', pp.returncode )
    print( 'stdout:', pp.stdout.decode() )
    print( 'stderr:', pp.stderr.decode() )
    if pp.returncode!= 0:
        return False
    print("-> MULTI-VERSION PUSH DONE")
    return True


def remove_image(name):
    cmd = runtime_cmd('rmi', name)
    print(f"- running command {' '.join(cmd)}")
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print( 'exit status:', p.returncode )
    print( 'stdout:', p.stdout.decode() )
    print( 'stderr:', p.stderr.decode() )
    if p.returncode!= 0:
        print(f"-> FAILED to remove {name}")
    else:
        print(f"-> REMOVED image {name}")


def prune_podman_storage(reason: str):
    if os.environ.get("DISABLE_PODMAN_PRUNE") == "1":
        print(f"-> Skipping podman prune ({reason})")
        return

    print(f"-> Pruning podman storage ({reason})")
    cmd = runtime_cmd('system', 'prune', '-a', '--volumes', '--force')
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('exit status:', p.returncode)
    print('stdout:', p.stdout.decode())
    print('stderr:', p.stderr.decode())
    if p.returncode != 0:
        print("-> Podman prune failed")


def _bytes_to_gib(value: int) -> float:
    return value / (1024 ** 3)


def log_disk_usage(label: str):
    total, used, free = shutil.disk_usage("/")
    print(
        f"[disk] {label}: total {_bytes_to_gib(total):.1f} GiB | "
        f"used {_bytes_to_gib(used):.1f} GiB | free {_bytes_to_gib(free):.1f} GiB"
    )


def ensure_disk_headroom(min_free_gb: float, strict: bool = False):
    _, _, free = shutil.disk_usage("/")
    free_gb = _bytes_to_gib(free)
    if free_gb < min_free_gb:
        if strict:
            raise RuntimeError(
                f"Insufficient disk space: {free_gb:.1f} GiB free, need at least {min_free_gb:.1f} GiB"
            )
        else:
            print(
                'stderr:',
                f"-> WARNING: Low disk space: {free_gb:.1f} GiB free, "
                f"recommended at least {min_free_gb:.1f} GiB"
            )


if __name__ == '__main__':
    registry = os.environ.get("DOCKER_REGISTRY", "docker.io")
    build_containers(registry)
