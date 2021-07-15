#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Xbox dlc build wrapper for Teamcity.

The script is for Teamcity autobuilds wich wraps around a batch file that generates xbox DLC

FEATURES
- harvest all of the commit messages from teamcity
- check for Validator errors
- builds (through batch) and commits the resultant dlc into subversion.

REQUIREMENTS
- Script should be run from the dlc directory
- working copy should be clean

RUNTIME REQUIREMENTS:
    Teamcity role access right: View all registered users to get the user friendly name
    pip install requests
    pip install lxml

"""

from argparse import ArgumentParser, RawTextHelpFormatter
import glob
import os
import re
import sys
import shlex
import subprocess
import requests
from lxml import etree


ARGS = None

# This parameter is used to publish artifacts to the teamcity build
TC_ARTIFACTS_PARAMETER = 'BUILD_ARTIFACTS'

# will use cookie for auth
SESSION = requests.Session()

def parse_args(args=None):
    """Define command-line arguments."""
    #defaults
    dlc_batchfile = 'make_one_dlc.bat'
    rest_api_version = "latest"
    max_depth = 100
    teamcity_url = "http://tc.corp.local"
    header = "xbox dlc autobuild:"
    exclude_authors = "builduser,buildbot"
    timeout = 60.0

    parser = ArgumentParser(prog=os.path.basename(__file__),
                            formatter_class=RawTextHelpFormatter,
                            description="Xbox dlc builder for Teamcity")

    parser.add_argument("--buildtype-id",
                        dest="buildtype_id",
                        help="teamcity buildtype.id")

    parser.add_argument("--commit-message",
                        dest="commit_msg",
                        help="svn commit message.")

    parser.add_argument("--commit-message-file",
                        dest="commit_msg_file",
                        help="svn commit message file.")

    parser.add_argument("--dlc-dirs",
                        dest="dlc_dirs",
                        help="DLC subdirectories to process. Comma-separated. If not specified, use teamcity build changes.")

    parser.add_argument("--dlc-batchfile",
                        dest="dlc_batchfile",
                        default=dlc_batchfile,
                        help=f"batch file for dlc processing. Default is {dlc_batchfile}")

    parser.add_argument("--rest-api-version",
                        dest="rest_api_version",
                        default=rest_api_version,
                        help="Default is latest. For older versions see "
                        "https://www.jetbrains.com/help/teamcity/rest-api.html#RESTAPI-RESTAPIVersions")

    parser.add_argument("--build-id",
                        dest="build_id",
                        help="teamcity build.id")

    parser.add_argument("--skip-commit",
                        dest="skip_commit", action='store_true',
                        help="Do not commit")

    parser.add_argument("--no-failed-builds",
                        dest="no_failed_builds", action='store_true',
                        help="Do not search all subsequent failed builds")

    parser.add_argument("--header",
                        dest="header", default=header, help="Default: {}".format(header))

    parser.add_argument("--max-depth",
                        dest="max_depth", type=int, default=max_depth,
                        help="Number of latest builds to parse. Default: {}".format(max_depth))

    parser.add_argument("--exclude-authors",
                        dest="exclude_authors", default=exclude_authors,
                        help="usernames to exclude from commits. Comma-separated,"
                             "Default: {}".format(exclude_authors))

    parser.add_argument("--password",
                        dest="password", help="user password")

    parser.add_argument("--username",
                        dest="username", help="username")

    parser.add_argument("--teamcity-url",
                        dest="teamcity_url",
                        default=teamcity_url,
                        help="Default: {}".format(teamcity_url))

    parser.add_argument("--timeout", dest="timeout", default=timeout, type=float,
                        help="Requests timeout in seconds. Default: {}".format(timeout))

    parser.add_argument("-v", dest="debug", action='store_true', help="be more verbose")


    # make some arguments adjacements.
    args = parser.parse_args(args=None, namespace=None)

    # reverse windows path backslashes.For them not be parsed like a screening chars.
    if args.commit_msg_file:
        args.commit_msg_file = args.commit_msg_file.replace('\\', '/')

    # convert to list
    if args.dlc_dirs:
        args.dlc_dirs = args.dlc_dirs.replace(' ', '').split(",")

    # convert to list and locase.
    if args.exclude_authors:
        args.exclude_authors = args.exclude_authors.replace(' ','').lower().split(",")

    return args


def get_paths_from_change(href):
    """Return set of directories from teamcity chande id."""
    href_diff = set()

    url = '{0}{1}'.format(ARGS.teamcity_url, href)
    resp = SESSION.get(url, timeout=ARGS.timeout)
    fail_on_response_error(resp)
    xml = etree.fromstring(resp.content)

    revision = xml.xpath('/change/@version')[0]
    username = xml.xpath('/change/@username')[0]

    if username.lower() in ARGS.exclude_authors:
        print("[info] skiping commit {} from {}".format(revision, username))
    else:
        # exclude removed and directory elements
        filelist = xml.xpath("//file[not(@directory='true' or @changeType='removed')]/@relative-file")

        # strip filenames and remove dups.
        href_diff = set(map(os.path.dirname, filelist))

    if ARGS.debug:
        print(f"[debug] {href} diff:\n - [raw] {filelist}\n - [compressed] {href_diff}")
    return href_diff


def filter_paths(unique_paths):
    """Filters-out non-relevant paths that may be in commits."""
    contains = re.compile(r"work_version/xbox/dlc/.+")
    restrict = re.compile(r"work_version/xbox/dlc/.+/out$")
    filtered_paths = unique_paths.copy()

    for path in unique_paths:
        if not contains.search(path) or restrict.search(path):
            print(f'[info] filtering out {path}')
            filtered_paths.remove(path)
    return filtered_paths


def get_changed_paths(ids):
    """Return list of changed (added or modified) paths."""
    global SESSION
    unique_paths = set()

    for build_id in [h['id'] for h in ids]:
        url = f'{ARGS.teamcity_url}/httpAuth/app/rest/{ARGS.rest_api_version}/changes?locator=build:(id:{build_id})'
        resp = SESSION.get(url, timeout=ARGS.timeout)
        fail_on_response_error(resp)

        xml = etree.fromstring(resp.content)
        hrefs = xml.xpath('/changes/change/@href')

        if ARGS.debug:
            print(f"[debug] got changes from build id {build_id}\n ",
                  etree.tostring(xml, pretty_print=True).decode())

        for href in hrefs:
            change_id_paths = get_paths_from_change(href)
            unique_paths.update(change_id_paths)

    if ARGS.debug:
        print(f"[debug] extracted paths: {unique_paths}")

    filtered_paths = filter_paths(unique_paths)
    return filtered_paths


def fail_on_response_error(resp):
    """Exit with error message."""
    if not resp.ok:
        print("error: couldnt reach teamcity api because of the errors:\n"
              "status code: {}\nerror message: {}".format(resp.status_code, resp.text))
        sys.exit(1)


def get_build_ids():
    """Return filterd list of builds for a given config.id.

    Also store auth info in cookies.
    """
    global SESSION

    if not ARGS.buildtype_id:
        print("[error] missing --buildtype-id argument")
        sys.exit(1)

    # if --build-id is not set, get the latest one.
    if ARGS.build_id:
        build_id = ARGS.build_id
    else:
        #http://tc.corp.local/app/rest/builds?locator=buildType:TcTests_mdfs,running:any,count:1
        url = '{}/httpAuth/app/rest/{}/builds?locator=buildType:{},running:any,count:1'.format(ARGS.teamcity_url, ARGS.rest_api_version, ARGS.buildtype_id)
        resp = SESSION.get(url, auth=(ARGS.username, ARGS.password), timeout=ARGS.timeout)
        fail_on_response_error(resp)
        xml = etree.fromstring(resp.content)
        build_id = xml.xpath('/builds/build/@id')[0]


    ids = []
    #http://tc.corp.local/app/rest/builds?locator=buildType:TcTests_mdfs,running:any,untilBuild:(id:38736)&fields=build(id,status,href)
    url = ('{url}/httpAuth/app/rest/{api_ver}/builds?'
           'locator=buildType:{buildTypeid},'
           'running:any,untilBuild:(id:{id})'
           '&count={count}&fields=build(id,status,href)').format(
               url=ARGS.teamcity_url,
               api_ver=ARGS.rest_api_version,
               buildTypeid=ARGS.buildtype_id,
               id=build_id,
               count=ARGS.max_depth)

    resp = SESSION.get(url, auth=(ARGS.username, ARGS.password), timeout=ARGS.timeout)
    fail_on_response_error(resp)

    xml = etree.fromstring(resp.content)

    for build in xml.xpath('/builds/build'):
        ids.append({
            'id':build.xpath('@id')[0],
            'status':build.xpath('@status')[0],
            'href':build.xpath('@href')[0]
            })

    # determine element index of the oldest failed build and before the success one
    i = 1
    if not ARGS.no_failed_builds:
        for build in ids[1:]:
            if build['status'] != 'SUCCESS':
                i += 1
            else:
                break

    if ARGS.debug:
        print(etree.tostring(xml, pretty_print=True).decode())
        print("[debug] will use builds: {}".format(ids[:i]))
    return ids[:i]

def svn_commit(dlc):
    """Commit changes to svn."""
    if not ARGS.commit_msg_file and not ARGS.commit_msg:
        print("[error] need to specify --commit-message-file or --commit-message")
        sys.exit(1)

    if ARGS.commit_msg_file and ARGS.commit_msg:
        print("[error] need to specify either --commit-message-file"
              "or --commit-message. But not both of them")
        sys.exit(1)

    if ARGS.commit_msg_file:
        commit_msg_args = f"-F {ARGS.commit_msg_file}"
    else:
        commit_msg_args = f'-m "{ARGS.commit_msg}"'

    for cmd in [ f'svn.exe add --force --parents {dlc}/out',
                 f'svn.exe commit --username {ARGS.username} --password {ARGS.password} --encoding UTF-8 {commit_msg_args}']:

        c = shlex.split(cmd)
        exitcode = subprocess.call(c)
        if exitcode != 0:
            print(f"[error] exited with code {exitcode}")
            sys.exit(exitcode)


def process_validator_logs(dlc):
    """Test if there were any errors in processing dlc.

    also publish validator log to teamcity artifacts via its parameter.
    """
    failures = re.compile(r"<failure>.+</failure>")

    for file in glob.glob(f"{dlc}/out/Validator_*.xml"):
        f = open(file, "r")
        content = f.read()
        f.close()
        if failures.search(content):
            print(f"[error] failures found in {file}")
            cwd = os.getcwd()
            print(f"##teamcity[setParameter name='{TC_ARTIFACTS_PARAMETER}' value='{cwd}/{file}']")
            sys.exit(1)


def process_dlcs(dlcs):
    """Run batch file for every new or modified dlc."""
    for dlc in dlcs:
        print(f"[info] forking \"{ARGS.dlc_batchfile} {dlc}\"...")

        exitcode = subprocess.call([ARGS.dlc_batchfile, dlc])
        if exitcode != 0:
            print(f"[error] exited with code {exitcode}")
            sys.exit(exitcode)


        process_validator_logs(dlc)

        if not ARGS.skip_commit:
            svn_commit(dlc)
        else:
            print("[warn] skip svn commit because of --skip-commit argument.")


def process_teamcity():
    """Get changes from teamcity and process dlc according to those changes."""
    if not ARGS.buildtype_id:
        print("[error] need to specify at least --buildtype-id")
        sys.exit(1)
    build_ids = get_build_ids()

    changed_paths = get_changed_paths(build_ids)
    if not changed_paths:
        print("[warn] seems like thereis nothing to do here...")
        sys.exit(0)

    dlcs = list(map(os.path.basename, changed_paths))
    process_dlcs(dlcs)


if __name__ == "__main__":
    ARGS = parse_args()

    if ARGS.dlc_dirs:
        process_dlcs(ARGS.dlc_dirs)
    else:
        process_teamcity()
