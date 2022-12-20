#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
The script gets Teamcity remote build status and set the REMOTE_BUILD_NUMBER parameter.

If no builds found the script will exit with errorcode 1. To change this behaviour add argument --no-fail-missing

You can customize messages with template strings. See expand_template function

"""
from argparse import ArgumentParser
import logging
import os
import sys
import ssl
import time
import json
import urllib.request

RETRY_SLEEP_TIME_SECONDS = 10


def parse_args(args=None):
    """
    Define command-line arguments.

    args parameter is for unittests. It defines arguments values when unittesting.
    """
    parser = ArgumentParser(prog=os.path.basename(__file__),
                            description="Teamcity artifacts downloader")
    parser.add_argument("--api-url", required=False, default="https://teamcity.corp.local",
                        help="Teamcity api access user")
    parser.add_argument("--api-username", required=False, default="tcuser",
                        help="Teamcity api access user")
    parser.add_argument("--api-password", required=False, default='tcpassword',
                        help="Teamcity api users' password")
    parser.add_argument("--build-locator", required=True,
                        help="Build locator to get artifacts from."
                             "For example, buildType:Project_Stable_BuildAndroid,number:1.11.0.56021,tag:xsolla,count:1")

    parser.add_argument("--failed-build-message",
                        default='build __buildTypeId__:__number__ is in __status__ state',
                        help="set teamcity status message on failed remote build")
    parser.add_argument("--cancelled-build-message",
                        default='build __buildTypeId__:__number__ cancelled',
                        help="set teamcity status message on cancelled remote build")
    parser.add_argument("--timeout-build-message",
                        default='timeout waitng for the build __buildTypeId__:__number__ finish',
                        help="set teamcity status message on waitng timeoute for the remote build finish")

    parser.add_argument("--max-wait-seconds", required=False, type=int, default=240,
                        help="Maximum seconds to wait for the remote build finish")
    parser.add_argument("--no-fail-missing", action='store_true',
                    help="Assume its OK if no build found. And log with warning.")
    parser.add_argument("--update-build-number", action='store_true',
                    help="Set own build number equal to remote build's")

    parsed = parser.parse_args(args, namespace=None)

    # ensure running builds are also returned.
    if not 'running:' in parsed.build_locator:
        parsed.build_locator += ',running:any'
    # ensure canceled builds are also returned.
    if not 'canceled:' in parsed.build_locator:
        parsed.build_locator += ',canceled:any'
    # ensure to return only latest build.
    if not 'count:1' in parsed.build_locator:
        parsed.build_locator += ',count:1'

    return parsed


def get_status(req):
    try:
        with urllib.request.urlopen(req) as r:
            content = r.read().decode()
            result = json.loads(content)
    except urllib.error.HTTPError as e:
        logging.error(f'Couldnt fetch status. Ensure:\n'
              f'  --build-locator is valid and builds are reachable by it ({ARGS.build_locator})\n'
              f'  --api-url is valid ({ARGS.api_url})\n'
              f'\n --- return status ---\nreason: {e.reason}\nmsg:{e.msg}\nReturn code: {e.code}\n')

        webpage = '\n'.join(( l.decode() for l in e.readlines()))
        print(webpage)
        sys.exit(1)

    if result['count'] == 0:
        msg = f'couldn\'t find any builds matching the request'
        if ARGS.no_fail_missing:
            logging.warning(msg)
        else:
            logging.error(msg)
            sys.exit(1)
    return result


def expand_template(tpl, schema):
    """ Expand build status fields found in template.

    the schema looks like this:
        'id': 533691,
        'buildTypeId': 'Tst_TstRunning',
        'number': '22',
        'status': 'SUCCESS',
        'state': 'finished',
        'href': '/httpAuth/app/rest/builds/id: 533691',
        'webUrl': 'https://teamcity.corp.local/viewLog.html?buildId=533691&buildTypeId=Tst_TstRunning',
        'finishOnAgentDate': '20221219T170121+0000'}

    you can insert any of the key in your string like this: "The build number is: __number__"
    """
    for k,v in schema.items():
        tpl = tpl.replace(f'__{k}__', str(v))
    return tpl


def get_build_info(url):
    """Return build status.

    The json returned will be structured like this:
       {'count': 1,
        'href': '/httpAuth/app/rest/builds/?locator=buildType:Tst_TstRunning,count: 1,number: 22',
        'nextHref': '/httpAuth/app/rest/builds/?locator=buildType:Tst_TstRunning,count: 1,number: 22,start: 1',
        'build': [
                {'id': 533691,
                    'buildTypeId': 'Tst_TstRunning',
                    'number': '22',
                    'status': 'SUCCESS',
                    'state': 'finished',
                    'href': '/httpAuth/app/rest/builds/id: 533691',
                    'webUrl': 'https://teamcity.corp.local/viewLog.html?buildId=533691&buildTypeId=Tst_TstRunning',
                    'finishOnAgentDate': '20221219T170121+0000'}
                ]
        }
    """

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

    logging.info(f'processing build matching request: "{url}"')

    timer = time.perf_counter()
    while True:
        status = get_status(req)
        if status['build'][0]['state'] == 'running':
            logging.info(f"build {status['build'][0]['buildTypeId']}:{status['build'][0]['number']} is still running. waiting till it finish...")
            if time.perf_counter()-timer > ARGS.max_wait_seconds:
                msg = expand_template(ARGS.timeout_build_message, status['build'][0])
                logging.warning(f"{msg}"
                              f"##teamcity[buildStatus text='{msg}']"
                              f"##teamcity[buildStop comment='{msg}' readdToQueue='false']")
        else:
            return status['build'][0]
        time.sleep(RETRY_SLEEP_TIME_SECONDS)


if __name__ == "__main__":

    # set loglevel to INFO. (by default its warning) and simplify format
    logging.getLogger().setLevel(logging.INFO)
    logging.basicConfig(format='[%(levelname)s] %(message)s')

    ARGS = parse_args()
    build = get_build_info(f'{ARGS.api_url}'
                   f'/httpAuth/app/rest/builds/?locator='
                   f'{ARGS.build_locator}')

    logging.info(f"setting REMOTE_BUILD_NUMBER to {build['number']}"
                f"##teamcity[setParameter name='REMOTE_BUILD_NUMBER' value='{build['number']}']")

    if ARGS.update_build_number:
        logging.info(f"setting my build number to {build['number']}"
                    f"##teamcity[buildNumber '{build['number']}']")

    if build['status'] == 'SUCCESS':
        logging.info('remote build status: SUCCESS')

    elif build['status'] == 'UNKNOWN':
        msg = expand_template(ARGS.cancelled_build_message, build)
        logging.warning(f"{msg}"
                        f"##teamcity[buildStatus text='{msg}']"
                        f"##teamcity[buildStop comment='{msg}' readdToQueue='false']")

    else:
        msg = expand_template(ARGS.failed_build_message, build)
        logging.error(f'{msg}'
                      f"##teamcity[buildStatus text='{msg}']")
        sys.exit(1)
