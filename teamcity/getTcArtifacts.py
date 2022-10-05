#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
The script gets Teamcity artifacts.

API: https://www.jetbrains.com/help/teamcity/rest/manage-finished-builds.html#Get+Build+Artifacts

"""
from argparse import ArgumentParser
import os
import sys
import re
import ssl
import json
import urllib.request


def parse_args(args=None):
    """
    Define command-line arguments.

    args parameter is for unittests. It defines arguments values when unittesting.
    """
    parser = ArgumentParser(prog=os.path.basename(__file__),
                            description="Teamcity artifacts downloader")
    parser.add_argument("--api-url", required=False, default="https://teamcity.corp.ru",
                        help="Teamcity api access user")
    parser.add_argument("--api-username", required=False, default="tcuser",
                        help="Teamcity api access user")
    parser.add_argument("--api-password", required=False, default='Tcuser$3cret!',
                        help="Teamcity api users' password")
    parser.add_argument("--build-locator", required=True,
                        help="Build locator to get artifacts from."
                             "For example, buildType:Proj_Stable_BuildAndroid,number:0.12.3,status:SUCCESS")
    parser.add_argument("--artifacts-path", required=False, default='/',
                        help="artifacts path to start download from. Archive content path is not supported")

    parser.add_argument("--include", required=False, default=r'.*',
                    help="Include artifacts regex patterns. Use ';' to separate patterns")
    parser.add_argument("--exclude", required=False, default='',
                    help="Exclude artifacts regex pattern. Use ';' to separate patterns")

    parser.add_argument("--directory", required=False, default=".",
                    help="Root directory to save artifacts to. Default is current.")
    parser.add_argument("--flattern", action='store_true',
                    help="flattern directory structure.")
    parser.add_argument("--dry-run", action='store_true',
                    help="Do not download anything.")
    parsed = parser.parse_args(args=None, namespace=None)

    parsed.exclude = [e.strip() for e in parsed.exclude.split(";") if e != '' ]
    parsed.include = [e.strip() for e in parsed.include.split(";") if e != '' ]

    # strip leading slash
    if parsed.artifacts_path[0] in ('/','\\'):
        parsed.artifacts_path=parsed.artifacts_path[1:]

    return parsed

def get_meta(url:str):
    """Return metainfo of available artifacts."""

    # Ignore SSL errors
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # create an authorization handler
    p = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    p.add_password(None, ARGS.api_url, ARGS.api_username, ARGS.api_password)

    auth_handler = urllib.request.HTTPBasicAuthHandler(p)
    opener = urllib.request.build_opener(auth_handler, urllib.request.HTTPSHandler(context=ctx))
    urllib.request.install_opener(opener)

    req = urllib.request.Request(url)
    req.add_header('Accept', 'Application/json')

    try:
        with urllib.request.urlopen(req) as r:
            content = r.read().decode()
            result = json.loads(content)
    except urllib.error.HTTPError as e:
        print(f'\nerror: Couldnt fetch url: {url}\n'
              f'Please check:\n'
              f' -  --artifacts-path ({ARGS.artifacts_path})\n'
              f' -  credentials are valid (user:{ARGS.api_username})\n'
              f' -  --build-locator is valid and builds are reachable by it ({ARGS.build_locator})\n'
              f' -  --api-url is valid ({ARGS.api_url})\n'
              f'\n --- return status ---\nreason: {e.reason}\nmsg:{e.msg}\nReturn code: {e.code}\n')

        webpage = '\n'.join(( l.decode() for l in e.readlines()))
        print(webpage)
        sys.exit(1)

    return result

def download_artifact(url:str, directory:str):
    print(f'downloading...{url} => {directory}')
    if ARGS.dry_run:
        return
    save_path = os.path.join(directory, os.path.basename(url))
    with urllib.request.urlopen(url) as response, open(save_path, 'wb') as out_file:
        data = response.read() # a `bytes` object
        out_file.write(data)

def ensure_directory(directory):
    directory=directory.replace('\\','/')
    if os.path.exists(directory):
        return
    else:
        print(f'[info] creating {directory}')
        if not ARGS.dry_run:
            os.makedirs(directory)

def need_to_download(path:str) -> bool:

    if any((re.compile(e).match(path) for e in ARGS.exclude)):
        return False

    if any((re.compile(e).match(path) for e in ARGS.include)):
        return True

    return False

def crawl_artifacts(url:str,path=''):
    """Recurse into artifact paths."""
    r=get_meta(url=url)
    for i in r['file']:
        if 'children' in i:
            crawl_artifacts(url=f'{ARGS.api_url}{i["children"]["href"]}', path=f'{path}{i["name"]}/')
        else:
            if not need_to_download(f'{path}{i["name"]}'):
                print(f'[info] skipping {path}{i["name"]}')
                continue

            if ARGS.flattern:
                save_path=ARGS.directory
            else:
                save_path=os.path.join(ARGS.directory,path)

            ensure_directory(save_path)
            download_artifact(url=f'{ARGS.api_url}{i["content"]["href"]}', directory=save_path)


if __name__ == "__main__":

    ARGS = parse_args()
    crawl_artifacts(url=f'{ARGS.api_url}/app/rest/builds/{ARGS.build_locator}/artifacts/{ARGS.artifacts_path}')