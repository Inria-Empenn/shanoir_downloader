"""
Keycloak authorization-code (+ PKCE) login for the Shanoir command line tools.

This is a Python transliteration of the flow used by shanoir-uploader
(``KeycloakAuthCodeLoginService.java``): a cookie-aware HTTP session with
redirect following disabled drives Keycloak's form-post authentication
entirely in-process -- no external browser is involved.

The point of using this flow rather than the direct grant
(``grant_type=password``) is that Keycloak itself tells us whether a
second factor is needed: the realm's browser flow contains a conditional
OTP sub-flow, so the ``kc-otp-login-form`` page is only ever returned for
users who actually have an OTP credential configured. A user without 2FA
is redirected straight to the callback URI and is never asked for a code.
"""

import base64
import hashlib
import html as html_lib
import os
import re
import secrets
import sys
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

import requests

REALM_PATH = '/auth/realms/shanoir-ng/protocol/openid-connect'
CLIENT_ID = 'shanoir-uploader'
REDIRECT_URI = 'http://localhost:12345/callback'
MAX_REDIRECTS = 15
MAX_OTP_ATTEMPTS = 3

# Authentication steps, mirroring KeycloakAuthCodeLoginService.AuthStep
SUCCESS = 'SUCCESS'
OTP_REQUIRED = 'OTP_REQUIRED'
OTP_SETUP_REQUIRED = 'OTP_SETUP_REQUIRED'
ACTION_REQUIRED = 'ACTION_REQUIRED'
BAD_CREDENTIALS = 'BAD_CREDENTIALS'


class AuthenticationError(Exception):
	"""Raised when the login flow cannot produce an access token."""
	pass


class AuthResult:

	def __init__(self, step, access_token=None, refresh_token=None, message=None):
		self.step = step
		self.access_token = access_token
		self.refresh_token = refresh_token
		self.message = message


# --- HTML parsing helpers -------------------------------------------------

_FORM_TAG_RE = re.compile(r'<form\b[^>]*>', re.IGNORECASE | re.DOTALL)
_ACTION_RE = re.compile(r'\baction="([^"]*)"', re.IGNORECASE)
_ID_RE = re.compile(r'\bid="([^"]*)"', re.IGNORECASE)


def _strip_tags(fragment):
	return html_lib.unescape(re.sub(r'<[^>]+>', '', fragment)).strip()


def _extract_form_action(html, form_id=None):
	"""Returns the action URL of the form with the given id, falling back to
	the first Keycloak authentication form found on the page."""
	forms = _FORM_TAG_RE.findall(html)
	chosen = None
	if form_id:
		for tag in forms:
			match = _ID_RE.search(tag)
			if match and match.group(1) == form_id:
				chosen = tag
				break
	if chosen is None:
		for tag in forms:
			action = _ACTION_RE.search(tag)
			if action and ('login-actions' in action.group(1) or 'authenticate' in action.group(1)):
				chosen = tag
				break
	if chosen is None and forms:
		chosen = forms[0]
	if chosen is None:
		return None
	action = _ACTION_RE.search(chosen)
	return html_lib.unescape(action.group(1)) if action else None


def _extract_hidden_value(html, name):
	match = re.search(r'<input[^>]*\bname="' + re.escape(name) + r'"[^>]*>', html, re.IGNORECASE)
	if not match:
		return None
	value = re.search(r'\bvalue="([^"]*)"', match.group(), re.IGNORECASE)
	return html_lib.unescape(value.group(1)) if value else None


def _extract_error_message(html):
	"""Best effort extraction of the message Keycloak displays on the page."""
	match = re.search(r'<span\s+id="input-error"[^>]*>(.*?)</span>', html, re.IGNORECASE | re.DOTALL)
	if match:
		text = _strip_tags(match.group(1))
		if text:
			return text
	match = re.search(r'class="alert alert-(?:error|warning)[^"]*"', html, re.IGNORECASE)
	if match:
		# The alert wraps an empty icon span followed by the title span holding the message.
		for span in re.finditer(r'<span[^>]*>(.*?)</span>', html[match.end():match.end() + 4000], re.DOTALL):
			text = _strip_tags(span.group(1))
			if text:
				return text
	return None


# --- Login session --------------------------------------------------------

class LoginSession:
	"""One complete login attempt. Keep the instance across the OTP steps:
	it holds the Keycloak authentication session cookies and the action URL
	of the page currently being displayed."""

	def __init__(self, config, client_id=CLIENT_ID, redirect_uri=REDIRECT_URI):
		self.base_url = 'https://' + config['domain']
		self.client_id = client_id
		self.redirect_uri = redirect_uri
		self.timeout = config.get('timeout')
		self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')
		digest = hashlib.sha256(self.code_verifier.encode('ascii')).digest()
		self.code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip('=')
		self.session = requests.Session()
		self.session.verify = config.get('verify', True)
		if config.get('proxies'):
			self.session.proxies = config['proxies']
		# Action URL of the Keycloak page currently displayed, updated at each step.
		self.current_action_url = None
		self.current_credential_id = ''

	def _to_base_url(self, url):
		"""Rewrites a Keycloak URL onto the configured server host.

		Keycloak advertises its own frontend host in form actions and redirects,
		which behind a reverse proxy may be an internal hostname. Following it
		would send the request to a host the authentication session cookies were
		not set for, and Keycloak would answer HTTP 400. The whole flow lives
		under the configured server, so everything but the callback URI is
		pinned to it."""
		if url is None or url.startswith(self.redirect_uri):
			return url
		parsed = urlparse(url)
		if not parsed.netloc:
			return urljoin(self.base_url, url)
		return self.base_url + parsed.path + (('?' + parsed.query) if parsed.query else '')

	def submit_credentials(self, username, password):
		"""Step 1: start a fresh Keycloak authentication session and post the
		credentials to the login form action URL."""
		auth_url = self.base_url + REALM_PATH + '/auth?' + urlencode({
			'client_id': self.client_id,
			'response_type': 'code',
			'redirect_uri': self.redirect_uri,
			'code_challenge': self.code_challenge,
			'code_challenge_method': 'S256',
			'scope': 'openid offline_access',
		})
		response = self.session.get(auth_url, allow_redirects=False, timeout=self.timeout)
		if response.status_code != 200:
			raise AuthenticationError(
				'Keycloak login page returned HTTP %s. Make sure you have a certified IP '
				'or are connected on a valid VPN.' % response.status_code)

		self.current_action_url = self._to_base_url(_extract_form_action(response.text, 'kc-form-login'))
		if self.current_action_url is None:
			raise AuthenticationError('Could not extract the login form action URL from the Keycloak page.')

		return self._post(self.current_action_url, {
			'username': username,
			'password': password,
			'credentialId': '',
		})

	def submit_otp(self, otp_code):
		"""Step 2: post the one-time code to the OTP form action URL."""
		return self._post(self.current_action_url, {
			'otp': otp_code,
			'credentialId': self.current_credential_id,
		})

	# --- internals --------------------------------------------------------

	def _post(self, action_url, data):
		response = self.session.post(
			action_url, data=data,
			headers={'Content-Type': 'application/x-www-form-urlencoded'},
			allow_redirects=False, timeout=self.timeout)
		return self._process_response(response)

	def _process_response(self, response):
		if response.status_code in (301, 302):
			return self._follow_redirects(self._to_base_url(urljoin(response.url, response.headers['Location'])))
		if response.status_code == 200:
			return self._classify_page(response.text)
		raise AuthenticationError('Unexpected HTTP status %s during the Keycloak authentication flow.'
			% response.status_code)

	def _follow_redirects(self, start_location):
		"""Follows the Keycloak internal redirects until either the callback URI
		is reached (carrying the authorization code) or a page requires user action."""
		location = start_location
		for _ in range(MAX_REDIRECTS):
			if location.startswith(self.redirect_uri):
				query = parse_qs(urlparse(location).query)
				if 'error' in query:
					raise AuthenticationError('Keycloak returned an error: %s' % query['error'][0])
				if 'code' not in query:
					raise AuthenticationError('No authorization code found in the callback URL.')
				access_token, refresh_token = self._exchange_code(query['code'][0])
				return AuthResult(SUCCESS, access_token=access_token, refresh_token=refresh_token)

			response = self.session.get(location, allow_redirects=False, timeout=self.timeout)
			if response.status_code in (301, 302):
				location = self._to_base_url(urljoin(response.url, response.headers['Location']))
			elif response.status_code == 200:
				return self._classify_page(response.text)
			else:
				raise AuthenticationError('Unexpected HTTP status %s during the Keycloak authentication flow.'
					% response.status_code)
		raise AuthenticationError('Exceeded the maximum redirect count during the Keycloak authentication flow.')

	def _classify_page(self, html):
		"""Determines which Keycloak page was returned, and updates the action URL."""
		message = _extract_error_message(html)

		if 'id="kc-totp-settings-form"' in html:
			return AuthResult(OTP_SETUP_REQUIRED, message=message)

		if 'id="kc-otp-login-form"' in html:
			self.current_action_url = self._to_base_url(_extract_form_action(html, 'kc-otp-login-form'))
			self.current_credential_id = _extract_hidden_value(html, 'credentialId') or ''
			return AuthResult(OTP_REQUIRED, message=message)

		if 'id="kc-passwd-update-form"' in html:
			return AuthResult(ACTION_REQUIRED, message=message or 'You must update your password.')

		if 'id="kc-update-profile-form"' in html:
			return AuthResult(ACTION_REQUIRED, message=message or 'You must update your profile.')

		if 'id="kc-form-login"' in html:
			return AuthResult(BAD_CREDENTIALS, message=message)

		return AuthResult(ACTION_REQUIRED, message=message or 'Unexpected Keycloak page returned.')

	def _exchange_code(self, code):
		response = self.session.post(
			self.base_url + REALM_PATH + '/token',
			data={
				'grant_type': 'authorization_code',
				'code': code,
				'redirect_uri': self.redirect_uri,
				'client_id': self.client_id,
				'code_verifier': self.code_verifier,
			},
			headers={'Content-Type': 'application/x-www-form-urlencoded'},
			timeout=self.timeout)
		if response.status_code != 200:
			raise AuthenticationError('Authorization code exchange failed: HTTP %s' % response.status_code)
		payload = response.json()
		return payload['access_token'], payload.get('refresh_token')


# --- Interactive driver ---------------------------------------------------

def _ask_password(username):
	import getpass
	if 'shanoir_password' in os.environ:
		return os.environ['shanoir_password']
	if not sys.stdin.isatty():
		raise AuthenticationError(
			'No terminal available to ask for the password: set the shanoir_password environment variable.')
	return getpass.getpass(prompt='Password for Shanoir user ' + username + ': ', stream=None)


def _ask_otp(username, attempt):
	"""Asks for the one-time code. The environment variable is only consumed on
	the first attempt, so that a stale value does not loop forever."""
	if attempt == 0 and 'shanoir_otp' in os.environ:
		return os.environ['shanoir_otp']
	if not sys.stdin.isatty():
		raise AuthenticationError(
			'Two-factor authentication is enabled for user ' + username + ' but no terminal is '
			'available to ask for the code: set the shanoir_otp environment variable.')
	return input('\nOne-time 2FA code for Shanoir user ' + username + ': ').strip()


def login(config):
	"""Logs in and returns ``(access_token, refresh_token)``.

	The 2FA code is only asked for if Keycloak actually challenges for it."""
	username = config['username']
	password = _ask_password(username)

	session = LoginSession(config)
	print('get keycloak token...', end=' ', flush=True)
	result = session.submit_credentials(username, password)

	attempt = 0
	while result.step == OTP_REQUIRED:
		if attempt >= MAX_OTP_ATTEMPTS:
			raise AuthenticationError('Too many invalid 2FA codes.')
		if result.message and attempt > 0:
			print(result.message)
		result = session.submit_otp(_ask_otp(username, attempt))
		attempt += 1

	if result.step == SUCCESS:
		print('done.')
		return result.access_token, result.refresh_token

	if result.step == OTP_SETUP_REQUIRED:
		raise AuthenticationError(
			'Two-factor authentication must be set up for user ' + username + '. '
			'Please log in to the Shanoir web interface once to register your authenticator application.')

	if result.step == BAD_CREDENTIALS:
		raise AuthenticationError(result.message or 'Bad username or password.')

	raise AuthenticationError(result.message or 'Login failed.')
