import os
import re
import subprocess
import requests
import tarfile
import shutil
import get_blender_release as gbr


MIN_FREE_GB = float(os.environ.get("MIN_FREE_GB", "12"))
CONTAINER_RUNTIME = os.environ.get("CONTAINER_RUNTIME", "podman")
SKIP_IMAGE_PUSH = os.environ.get("SKIP_IMAGE_PUSH") == "1"
REVERSE_BUILD_ORDER = os.environ.get("REVERSE_BUILD_ORDER") == "1"
KEEP_IMAGES = os.environ.get("KEEP_IMAGES") == "1"
KEEP_BUILD_DIRS = os.environ.get("KEEP_BUILD_DIRS") == "1"


def runtime_cmd(*args):
        return [CONTAINER_RUNTIME, *args]


def build_containers(registry: str):
    releases = gbr.get_stable_and_prereleases(os="linux", arch="x64", min_ver=(2, 93))
    releases = gbr.order_releases(releases)
    for release in releases:
        print(f"\n\n\n====== Blender {release.version} ======")

        log_disk_usage(f"before {release.version}")
        ensure_disk_headroom(MIN_FREE_GB)

        build_dir = os.path.join(os.path.dirname(__file__), "build", f"{release.version[0]}.{release.version[1]}")
        ok = build_container(release.url, release.version, release.stage, build_dir, registry)
        clean_build_dir(build_dir)

        if ok:
            print(f"✅ {release.version} {release.stage} single build OK")
        else:
            print(f"❌ {release.version} {release.stage} single build FAILED")


def build_multi_version(registry: str) -> bool:
    """Build ONE multi-version image containing the latest stable patch of every minor
    Blender release (>= 2.93). Alpha/beta/rc prereleases are intentionally skipped.

    Versions are layered oldest -> newest via chained ADD instructions and end up at
    /home/headless/blenders/X.Y. The final image is tagged headless-blender:multi-version.
    """
    releases = gbr.get_blender_releases(os="linux", arch="x64", min_ver=(2, 93))
    if not releases:
        print("-> ERROR: could not fetch stable releases, aborting multi-version build")
        return False
    releases = gbr.order_releases(releases)
    print(f"-> Multi-version build: {len(releases)} stable releases (oldest to newest), skipping all prereleases")
    for release in releases:
        print(f"   - {release.version[0]}.{release.version[1]}.{release.version[2]}")

    prev_version = None
    for release in releases:
        print(f"\n\n\n====== Multi Blender {release.version} ======")
        log_disk_usage(f"before {release.version}")
        ensure_disk_headroom(MIN_FREE_GB)

        build_dir = os.path.join(os.path.dirname(__file__), "build", f"{release.version[0]}.{release.version[1]}")

        if prev_version is None:
            ok = multi_start(release.url, release.version, build_dir)
        else:
            ok = multi_add(release.url, release.version, prev_version, build_dir)

        clean_build_dir(build_dir)
        log_disk_usage(f"after cleanup {release.version}")

        if not ok:
            print(f"❌ {release.version} multi build FAILED, aborting")
            return False

        print(f"✅ {release.version} multi build OK")
        if prev_version is not None and not KEEP_IMAGES:
            remove_image(multi_image_tag(prev_version))
        prev_version = release.version

    if prev_version is None:
        print("-> No stable releases found, nothing to push")
        return False

    ok = multi_push(prev_version, registry)
    if not KEEP_IMAGES:
        remove_image(multi_image_tag(prev_version))
    if ok:
        print("✅ multi-version image complete")
    else:
        print("❌ multi-version push FAILED")
    return ok


def clean_build_dir(dir: str):
    if KEEP_BUILD_DIRS:
        print(f"-> KEEPING build directory {dir} (KEEP_BUILD_DIRS=1)")
        return
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


MULTI_BASE_CONTAINERFILE = """FROM docker.io/accetto/ubuntu-vnc-xfce-opengl-g3
USER root
RUN apt-get update && apt-get install -y git unzip ca-certificates
ADD blender /home/headless/blenders/{x}.{y}
ENTRYPOINT [ "/usr/bin/tini", "--", "/dockerstartup/startup.sh" ]
"""


MULTI_ADD_CONTAINERFILE = """FROM blender_{prev_x}_{prev_y}
USER root
ADD blender /home/headless/blenders/{x}.{y}
"""


def generate_multi_base_containerfile(version: tuple):
    """Generate the base Containerfile for the multi-version image.

    Unlike the single image, every Blender lives under a versioned directory
    /home/headless/blenders/X.Y so all versions coexist at predictable paths.
    """
    return MULTI_BASE_CONTAINERFILE.format(x=version[0], y=version[1])


def generate_multi_add_containerfile(version: tuple, prev_version: tuple):
    """Generate a Containerfile that ADDs one more Blender on top of the previous multi layer."""
    return MULTI_ADD_CONTAINERFILE.format(
        x=version[0],
        y=version[1],
        prev_x=prev_version[0],
        prev_y=prev_version[1],
    )


def stage_tag_suffix(stage: str) -> str:
    """Normalize a build stage into a tag-safe suffix.

    Examples: 'stable' -> 'stable', 'alpha' -> 'alpha', 'release candidate' -> 'rc'.
    Always returns a non-empty, registry-safe token ([a-z0-9-]).
    """
    s = (stage or "").strip().lower()
    if "candidate" in s:
        return "rc"
    safe = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return safe or "unknown"


def prepare_blender(url: str, build_dir: str, attempts: int = 2) -> bool:
    """Download and extract Blender into build_dir/blender, retrying once on a corrupted archive."""
    os.makedirs(build_dir, exist_ok=True)
    tar_path = os.path.join(build_dir, "blender.tar.xz")
    for attempt in range(attempts):
        download_file(url, tar_path, force=attempt > 0)
        try:
            extract_tar(tar_path, build_dir)
            return True
        except RuntimeError as exc:
            if attempt == attempts - 1:
                print(f"-> FAILED extraction after retry: {exc}")
                return False
            print("-> Retrying download due to extraction failure")
    return False


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
    base_tag = f'{registry}/blenderkit/headless-blender:blender-{version[0]}.{version[1]}'
    # Extra, stage-qualified tag (e.g. blender-5.2-stable / -alpha / -rc) pointing
    # at the same image. Purely additive: the base tag above is unchanged, so
    # existing consumers that pull blender-X.Y keep working exactly as before.
    stage_tag = f'{base_tag}-{stage_tag_suffix(stage)}'
    cmd = runtime_cmd(
        'build',
        '-f', cfpath,
        '-t', base_tag,
        '-t', stage_tag,
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
        push_cmd = runtime_cmd('push', base_tag)
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

        # Best-effort: a failure to push the extra stage tag must never fail a
        # build that already pushed the base tag successfully.
        print(f"-> PUSHING STAGE-TAGGED IMAGE {stage_tag}")
        ps = subprocess.run(
            runtime_cmd('push', stage_tag),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print( 'exit status:', ps.returncode )
        print( 'stdout:', ps.stdout.decode() )
        print( 'stderr:', ps.stderr.decode() )
        if ps.returncode!= 0:
            print(f"-> WARNING: failed to push stage tag {stage_tag} (non-fatal)")
        else:
            print("-> STAGE PUSH DONE")

    if KEEP_IMAGES:
        print(f"-> KEEPING images {base_tag} and {stage_tag} (KEEP_IMAGES=1)")
    else:
        remove_image(base_tag)
        remove_image(stage_tag)

    return True


def multi_image_tag(version: tuple) -> str:
    return f"blender_{version[0]}_{version[1]}"


def multi_start(url: str, version: tuple, build_dir: str) -> bool:
    """Build the base layer of the multi-version image from the oldest stable release."""
    print(f"=== Building base multi {version[0]}.{version[1]} ===")
    if not prepare_blender(url, build_dir):
        return False

    containerfile = generate_multi_base_containerfile(version)
    cfpath = os.path.join(build_dir, "Containerfile")
    with open(cfpath, "w") as file:
        file.write(containerfile)

    print(os.listdir(build_dir))
    cmd = runtime_cmd('build', '-f', cfpath, '-t', f'{multi_image_tag(version)}:latest', '.')
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run(cmd, cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('exit status:', pb.returncode)
    print('stdout:', pb.stdout.decode())
    print('stderr:', pb.stderr.decode())
    if pb.returncode != 0:
        return False
    print("-> MULTI BASE BUILD DONE")
    return True


def multi_add(url: str, version: tuple, prev_version: tuple, build_dir: str) -> bool:
    """ADD one more stable Blender on top of the existing multi-version image."""
    print(f"=== Adding Blender {version[0]}.{version[1]} on top of {prev_version[0]}.{prev_version[1]} ===")
    if not prepare_blender(url, build_dir):
        return False

    containerfile = generate_multi_add_containerfile(version, prev_version)
    cfpath = os.path.join(build_dir, "Containerfile")
    with open(cfpath, "w") as file:
        file.write(containerfile)

    print(os.listdir(build_dir))
    cmd = runtime_cmd('build', '-f', cfpath, '-t', f'{multi_image_tag(version)}:latest', '.')
    print(f"- running command {' '.join(cmd)}")
    pb = subprocess.run(cmd, cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('exit status:', pb.returncode)
    print('stdout:', pb.stdout.decode())
    print('stderr:', pb.stderr.decode())
    if pb.returncode != 0:
        return False
    print("-> MULTI ADD DONE")
    return True


def multi_push(version: tuple, registry: str) -> bool:
    """Tag the final accumulated multi-version image and push it as headless-blender:multi-version."""
    multi_tag = f"{registry}/blenderkit/headless-blender:multi-version"
    print(f"=== Tagging multi {version[0]}.{version[1]} as {multi_tag} ===")
    tag_cmd = runtime_cmd("image", "tag", multi_image_tag(version), multi_tag)
    print(f"- running command {' '.join(tag_cmd)}")
    pt = subprocess.run(tag_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('exit status:', pt.returncode)
    print('stdout:', pt.stdout.decode())
    print('stderr:', pt.stderr.decode())
    if pt.returncode != 0:
        return False

    if SKIP_IMAGE_PUSH:
        print("-> SKIPPING MULTI PUSH (SKIP_IMAGE_PUSH=1)")
        return True

    print("-> PUSHING MULTI-VERSION IMAGE")
    push_cmd = runtime_cmd('push', multi_tag)
    print(f"- running command {' '.join(push_cmd)}")
    pp = subprocess.run(push_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print('exit status:', pp.returncode)
    print('stdout:', pp.stdout.decode())
    print('stderr:', pp.stderr.decode())
    if pp.returncode != 0:
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
    # Use prune without -a so tagged multi images stay available for the next layer
    cmd = runtime_cmd('system', 'prune', '--volumes', '--force')
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
    print("====== build.py configuration ======")
    print(f"  CONTAINER_RUNTIME = {CONTAINER_RUNTIME}")
    print(f"  DOCKER_REGISTRY   = {registry}")
    print(f"  BUILD_MULTI       = {os.environ.get('BUILD_MULTI') == '1'}")
    print(f"  SKIP_IMAGE_PUSH   = {SKIP_IMAGE_PUSH}")
    print(f"  KEEP_IMAGES       = {KEEP_IMAGES}  (images are {'KEPT' if KEEP_IMAGES else 'REMOVED'} after building)")
    print(f"  KEEP_BUILD_DIRS   = {KEEP_BUILD_DIRS}  (build/X.Y dirs are {'KEPT' if KEEP_BUILD_DIRS else 'REMOVED'} after building)")
    print("====================================")
    if os.environ.get("BUILD_MULTI") == "1":
        build_multi_version(registry)
    else:
        build_containers(registry)
