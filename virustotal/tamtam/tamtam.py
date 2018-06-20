#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import requests


URL_RE = re.compile(r'(https?://[^\s]+)')
TAMTAM_URL = 'https://api.tamtam.im/api/message'
# ed :test: vM5j4RrKylZvbbpQ28ajdGRea
# tokenizer: test: PmA8aLQRYRbgmnn835n9WDedQ
TAMTAM_TOKENS = {'test':"vM5j4R",
         'antivir':"GjRP59OelMLQ",
        }

def tagify(tag):
    """Substitute every whitespace with underscore"""
    return re.sub('[^\w_]+', '_', tag)


def do_wrap_links(message):
    repl = r'[details](\1)'
    return URL_RE.sub(repl, message)


def send_message(message, token, bot_name = 'Wall-E', timeout=10, url = TAMTAM_URL):
  message=message[:9999] #limit of 10000 chars
  # We need SNI suppport for verify=True, but we do not want to force python update or too much dependencies
  # https://stackoverflow.com/questions/18578439/using-requests-with-tls-doesnt-give-sni-support
  # Tamtam does not require SNI any more so we can use verify=True here
  r = requests.post(url, json={'token':token,'text':message,'name':bot_name}, verify=True, timeout=timeout)
  r.raise_for_status()
  if not r.json()['result'] == 'OK':
      raise RuntimeError('Failed to push to tamtam: {0}'.format(r.text))

#post_mention = ''
#post_mention = '@all'

#post_msg = '[CLEAN] emo-1.2.3.25678 : 5/60 positives.\n https://www.virustotal.com/file/9a4b8d748301fb3f166f34b72d67a1a245cd60745bb2243d404c1ac21dfdc595/analysis/1495548291/\n' + post_mention
#bot_name = 'virustotal scan results'

#send_message(do_wrap_links(post_msg), token['test'], bot_name )