"""Simple script to get daily builds of Blender."""

import requests
from bs4 import BeautifulSoup
import re
import urllib.parse

class Release:
    def __init__(self, version, stage, reference, date, arch, os, url):
        self.version = version
        self.stage = stage
        self.reference = reference
        self.date = date
        self.arch = arch
        self.os = os
        self.url = url
    def __str__(self):
        return f"{self.version} {self.stage} {self.reference} {self.date} {self.arch} {self.os} {self.url}"


def get_soup(url: str):
    """Download the blender daily builds page, parse it with BeautifulSoup4 and return the soup. If something wents wrong, return None."""
    response = requests.get(url)
    if response.status_code != 200:
        print(f"⚠️ Could not GET {url}, status code: {response.status_code}")
        return None
    return BeautifulSoup(response.text, "html.parser")


def get_blender_dailys(os="linux", arch="x64"):
    """Get a list of Blender daily prereleases for a given os and arch. If something went wrong, return empty list.
    Blender currently releases for these os and arch:
    
    - os = windows, linux, macos
    - arch = x64, arm64
    """
    os = os.lower()
    if os not in ["windows", "linux", "macos"]:
        print(f"Unsupported OS: {os}")
        return None
    
    arch = arch.lower()
    if arch not in ["x64", "arm64"]:
        print(f"Unsupported arch: {arch}")
        return None
    
    search_os = os
    search_arch = arch
    if os == "macos":
        search_os = "darwin"
        if arch == "x64":
            search_arch = "intel"
        if arch == "arm64":
            search_arch = "apple silicon"

    url = "https://builder.blender.org/download/daily/"
    soup = get_soup(url)
    if soup == None:
        return None
    
    platform_tab = soup.find("div", {"class": f"platform-{search_os}"})
    releases = platform_tab.find_all("li")
    prereleases = []
    for release in releases:
        verstring = release.find("a", {"class": "b-version"}).text
        version = parse_version(verstring)

        stage = release.find("a", {"class": "b-variant"}).text.lower()
        if stage == "stable":
            continue # not interested in stable versions

        reference = release.find("a", {"class": "b-reference"}).text
        date = release.find("div", {"class": "b-date"}).text
        arch_strings = release.find("div", {"class": "b-arch"}).text.split(" ")
        architecture = arch_strings[1].lower()
        operating_system = arch_strings[0].lower()
        if architecture != search_arch:
            print(f"Architecture does not match: {architecture} {search_arch}, this could be a bug!")
            continue
        if operating_system!= search_os:
            print(f"Operating system does not match: {operating_system} {search_os}, this could be a bug!")
            continue

        download = release.find("div", {"class": "b-down"})
        if download == None:
            print(f"No download link found for {version} {stage} {reference} {date} {architecture} {operating_system}, could be a bug.")
            continue

        url = download.find("a").get("href")
        if url.endswith(".sha256"):
            continue

        prereleases.append(Release(version, stage, reference, date, architecture, operating_system, url))

    return prereleases


def get_blender_releases(os: str="linux", arch: str="x64", min_ver=(2, 93)):
    """Get all minor releases of Blender. If the release is higher than min_ver, then open its directory and search for highest patch release.
    In the end, returns a list of releases, highest patch version.
    """
    url = "https://download.blender.org/release/"
    soup = get_soup(url)
    if soup == None:
        return None
    
    regex = re.compile(r"Blender(\d)\.(\d+)\/")
    links = soup.find_all("a")
    releases = []
    for link in links:
        href = link.get("href")
        if href == None:
            continue
        match = regex.search(href)
        if match == None:
            continue

        ver = (int(match.group(1)), int(match.group(2)))
        if ver < min_ver:
            continue

        release = parse_patch_releases(os, arch, urllib.parse.urljoin(url, href))
        if release!= None:
            releases.append(release)

    return releases

def parse_patch_releases(os: str, arch: str, url: str) -> Release:
    ver_soup = get_soup(url)
    if ver_soup == None:
        return
        
    if os == "windows":
        suffix = r"msi"
    if os == "linux":
        suffix = r"tar.xz"
    if os == "macos":
        suffix = r"dmg"

    regex = re.compile(f"blender-(\\d)\\.(\\d+)\\.(\\d+)-{os}-{arch}\\.{suffix}")
    links = ver_soup.find_all("a")
    release = None
    for link in links:
        href = link.get("href")
        if href == None:
            continue

        match = regex.search(href)
        if match == None:
            continue

        version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if match == None:
            continue

        if release == None:
            release = Release(version, "stable", "", "", arch, os, urllib.parse.urljoin(url, href))
            continue

        if version <= release.version:
            continue

        release = Release(version, "stable", "", "", arch, os, urllib.parse.urljoin(url, href))

    return release 


def merge_prefer_stable(releases: list[Release], dailys=list[Release]):
    """Prefer stable releases over daily prereleases releases.
    If stable minor version is available, do not append daily release.
    If no stable minor release is available, then append the daily release.
    """
    for daily in dailys:
        stable_available = False
        for release in releases:
            if release.version[:2] == daily.version[:2]:
                stable_available = True
                break
        if not stable_available:
            releases.append(daily)
    return releases

def get_stable_and_prereleases(os: str="linux", arch: str="amd64", min_ver=(2, 93)):
    releases = get_blender_releases(os, arch, min_ver)
    dailys = get_blender_dailys(os, arch, min_ver)
    return merge_prefer_stable(releases, dailys)

def parse_version(verstring: str) -> tuple[int]:
    """Parse a version string into a tuple of integers."""
    verstring = verstring.split(" ")[1]
    x, y, z = verstring.split(".")
    return (int(x), int(y), int(z))


if __name__ == "__main__":
    print("--- releases ---")
    releases = get_blender_releases("linux", "x64")
    for release in releases:
        print(release)

    print("--- prereleases ---")
    prereleases = get_blender_dailys("linux", "x64")
    prereleases.append(Release((3, 6, 15), "alpha", "", "", "x64", "linux", "https://download.blender.org/release/Blender2.93/blender-2.93.1-linux-x64.tar.xz"))
    for prerelease in prereleases:
        print(prerelease)

    print("--- merged ---")
    mixes = merge_prefer_stable(releases, prereleases)
    for mix in mixes:
        print(mix)
