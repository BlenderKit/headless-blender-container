"""Simple script to get daily builds of Blender."""

import requests
from bs4 import BeautifulSoup

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

def get_blender_release_soup():
    """Download the blender releases page, parse it with BeautifulSoup4 and return the soup. If something wents wrong, return None."""
    url = "https://builder.blender.org/download/release"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Could not get blender releases from builder.blender.org, status code: {response.status_code}")
        return None
    return BeautifulSoup(response.text, "html.parser")


def get_blender_prereleases(os="linux", arch="x64"):
    """Get a list of Blender prereleases for a given os and arch. If something went wrong, return empty list.
    Blender currently releases for these os and arch:
    windows - x64
    windows - arm64
    linux - x64
    darwin - intel
    darwin - apple silicon
    """
    os = os.lower()
    if os not in ["windows", "linux", "darwin"]:
        print(f"Unsupported OS: {os}")
        return None
    
    arch = arch.lower()
    if arch not in ["x64", "arm64", "apple silicon", "intel"]:
        print(f"Unsupported arch: {arch}")
        return None 

    soup = get_blender_release_soup()
    if soup == None:
        return None
    
    platform_tab = soup.find("div", {"class": f"platform-{os}"})
    releases = platform_tab.find_all("li")
    prereleases = []
    for release in releases:
        verstring = release.find("a", {"class": "b-version"}).text
        version = parse_version(verstring)

        stage = release.find("a", {"class": "b-variant"}).text
        if stage.lower() == "stable":
            continue # not interested in stable versions

        reference = release.find("a", {"class": "b-reference"}).text
        date = release.find("div", {"class": "b-date"}).text
        arch_strings = release.find("div", {"class": "b-arch"}).text.split(" ")
        architecture = arch_strings[1].lower()
        operating_system = arch_strings[0].lower()
        if architecture != arch:
            print(f"Architecture does not match: {architecture} {arch}, this could be a bug!")
            continue
        if operating_system!= os:
            print(f"Operating system does not match: {operating_system} {os}, this could be a bug!")
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

def parse_version(verstring: str) -> tuple[int]:
    """Parse a version string into a tuple of integers."""
    verstring = verstring.split(" ")[1]
    x, y, z = verstring.split(".")
    return (int(x), int(y), int(z))

if __name__ == "__main__":
    releases = get_blender_prereleases("linux", "x64")
    for release in releases:
        print(release)

