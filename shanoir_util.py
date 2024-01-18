import os
import datetime

import requests
import json
import getpass
import sys
import logging
import http.client as http_client
from pathlib import Path

def init_logging(args):

    verbose = args.verbose

    logfile = Path(args.log_file)
    logfile.parent.mkdir(exist_ok=True, parents=True)

    logging.basicConfig(
        level=logging.INFO, # if verbose else logging.ERROR,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(str(logfile)),
            logging.StreamHandler(sys.stdout)
        ]
    )

    if verbose:
        http_client.HTTPConnection.debuglevel = 1

        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True


def initialize(args):

    server_domain = args.domain
    username = args.username

    init_logging(args)

    verify = args.certificate if hasattr(args, 'certificate') and args.certificate != '' else True

    proxy_url = None # 'user:pass@host:port'

    if hasattr(args, 'proxy_url') and args.proxy_url is not None:
        proxy_a = args.proxy_url.split('@')
        proxy_user = proxy_a[0]
        proxy_host = proxy_a[1]
        proxy_password = getpass.getpass(prompt='Proxy password for user ' + proxy_user + ' and host ' + proxy_host + ': ', stream=None)
        proxy_url = proxy_user + ':' + proxy_password + '@' + proxy_host

    else:

        configuration_folder = None

        if hasattr(args, 'configuration_folder') and args.configuration_folder:
            configuration_folder = Path(args.configuration_folder)
        else:
            cfs = sorted(list(Path.home().glob('.su_v*')))
            configuration_folder = cfs[-1] if len(cfs) > 0 else Path().home()

        proxy_settings = configuration_folder / 'proxy.properties'

        proxy_config = {}

        if proxy_settings.exists():
            with open(proxy_settings) as file:
                for line in file:
                    if line.startswith('proxy.'):
                        line_s = line.split('=')
                        proxy_key = line_s[0]
                        proxy_value = line_s[1].strip()
                        proxy_key = proxy_key.split('.')[-1]
                        proxy_config[proxy_key] = proxy_value

                if 'enabled' not in proxy_config or proxy_config['enabled'] == 'true':
                    if 'user' in proxy_config and len(proxy_config['user']) > 0 and 'password' in proxy_config and len(proxy_config['password']) > 0:
                        proxy_url = proxy_config['user'] + ':' + proxy_config['password']
                    proxy_url += '@' + proxy_config['host'] + ':' + proxy_config['port']
        else:
            print("Proxy configuration file not found. Proxy will be ignored.")

    proxies = None

    if proxy_url:

        proxies = {
            'http': 'http://' + proxy_url,
            # 'https': 'https://' + proxy_url,
        }

    return { 'domain': server_domain,
             'username': username,
             'verify': verify,
             'proxies': proxies,
             'timeout': args.timeout,
             }

access_token = None
refresh_token = None

# using user's password, get the first access token and the refresh token
def ask_access_token(config):
    try:
        password = os.environ['shanoir_password'] if 'shanoir_password' in os.environ else getpass.getpass(prompt='Password for Shanoir user ' + config['username'] + ': ', stream=None)
    except:
        sys.exit(0)
    url = 'https://' + config['domain'] + '/auth/realms/shanoir-ng/protocol/openid-connect/token'
    payload = {
        'client_id' : 'shanoir-uploader',
        'grant_type' : 'password',
        'username' : config['username'],
        'password' : password,
        'scope' : 'offline_access'
    }
    # curl -d '{"client_id":"shanoir-uploader", "grant_type":"password", "username": "amasson", "password": "", "scope": "offline_access" }' -H "Content-Type: application/json" -X POST

    headers = {'content-type': 'application/x-www-form-urlencoded'}
    print('get keycloak token...')
    response = requests.post(url, data=payload, headers=headers, proxies=config['proxies'], verify=config['verify'], timeout=config['timeout'])
    if not hasattr(response, 'status_code') or response.status_code != 200:
        print('Failed to connect, make sur you have a certified IP or are connected on a valid VPN.')
        raise ConnectionError(response.status_code)

    response_json = json.loads(response.text)
    if 'error_description' in response_json and response_json['error_description'] == 'Invalid user credentials':
        print('bad username or password')
        sys.exit(1)
    global refresh_token
    refresh_token = response_json['refresh_token']
    return response_json['access_token']

# get a new acess token using the refresh token
def refresh_access_token(config):
    url = 'https://' + config['domain'] + '/auth/realms/shanoir-ng/protocol/openid-connect/token'
    payload = {
        'grant_type' : 'refresh_token',
        'refresh_token' : refresh_token,
        'client_id' : 'shanoir-uploader'
    }
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    logging.info('refresh keycloak token...')
    response = requests.post(url, data=payload, headers=headers, proxies=config['proxies'], verify=config['verify'], timeout=config['timeout'])
    if response.status_code != 200:
        logging.error('response status : {response.status_code}, {responses[response.status_code]}')
    response_json = response.json()
    return response_json['access_token']

def perform_rest_request(config, rtype, url, **kwargs):
    response = None
    if rtype == 'get':
        response = requests.get(url, proxies=config['proxies'], verify=config['verify'], timeout=config['timeout'], **kwargs)
    elif rtype == 'post':
        response = requests.post(url, proxies=config['proxies'], verify=config['verify'], timeout=config['timeout'], **kwargs)
    else:
        print('Error: unimplemented request type')

    return response


# perform a request on the given url, asks for a new access token if the current one is outdated
def rest_request(config, rtype, url, raise_for_status=True, **kwargs):
    global access_token
    if access_token is None:
        access_token = ask_access_token(config)
    headers = {
        'Authorization' : 'Bearer ' + access_token,
        'content-type' : 'application/json',
        'charset' : 'utf-8'
    }
    response = perform_rest_request(config, rtype, url, headers=headers, **kwargs)
    # if token is outdated, refresh it and try again
    if response.status_code == 401:
        access_token = refresh_access_token(config)
        headers['Authorization'] = 'Bearer ' + access_token
        response = perform_rest_request(config, rtype, url, headers=headers, **kwargs)
    if raise_for_status:
        response.raise_for_status()
    return response

def log_response(e):
    logging.error('Response status code: {e.response.status_code}')
    logging.error('		 reason: {e.response.reason}')
    logging.error('		 text: {e.response.text}')
    logging.error('		 headers: {e.response.headers}')
    logging.error(str(e))
    return

# perform a GET request on the given url, asks for a new access token if the current one is outdated
def rest_get(config, url, params=None, stream=None):
    return rest_request(config, 'get', url, params=params, stream=stream)

# perform a POST request on the given url, asks for a new access token if the current one is outdated
def rest_post(config, url, params=None, files=None, stream=None, json=None, data=None, raise_for_status=True):
    return rest_request(config, 'post', url, raise_for_status, params=params, files=files, stream=stream, json=json, data=data)

def createExecution(config, execution, silent=False):
    global refresh_token
    global access_token
    if access_token is None:
        access_token = ask_access_token(config)
    execution["identifier"]=""
    execution["name"] += "_" + datetime.datetime.now().strftime("%m%d%Y%H%M%S")
    execution["refreshToken"] = refresh_token
    execution["studyIdentifier"] = 1
    execution["client"]="shanoir-uploader"
    url = 'https://' + config['domain'] + '/shanoir-ng/datasets/carmin-data/createExecution'
    response = rest_post(config, url, {}, data=json.dumps(execution), raise_for_status=False)
    if response.status_code != 200:
        logging.error('Error while creating execution' + str(response.status_code) + " : " + str(response.text))
    return response.json()

def getExecutionStatus(config, identifier):
    url = 'https://' + config['domain'] + '/shanoir-ng/datasets/carmin-data/execution/' + identifier
    response = rest_get(config, url)
    return response.content
