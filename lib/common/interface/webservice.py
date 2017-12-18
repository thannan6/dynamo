import sys
import os
import urllib
import urllib2
import httplib
import time
import json
import re
import logging

from dataformat import Configuration
from common.transform import unicode2str

LOG = logging.getLogger(__name__)

GET, POST = range(2) # enumerators

class HTTPSCertKeyHandler(urllib2.HTTPSHandler):
    """
    HTTPS handler authenticating by x509 user key and certificate.
    """

    def __init__(self, config):
        urllib2.HTTPSHandler.__init__(self)
        self.key = config.x509_key
        self.cert = self.key

    def https_open(self, req):
        return self.do_open(self.create_connection, req)

    def create_connection(self, host, timeout = 300):
        return httplib.HTTPSConnection(host, key_file = self.key, cert_file = self.cert)


class CERNSSOCookieAuthHandler(urllib2.HTTPSHandler):
    """
    HTTPS handler for CERN single sign-on service. Requires a cookie file
    generated by cern-get-sso-cookie.
    """

    def __init__(self, config):
        urllib2.HTTPSHandler.__init__(self)

        self.cookies = {}

        with open(config.cookie_file) as cookie_file:
            # skip the header
            while cookie_file.readline().strip():
                pass

            for line in cookie_file:
                domain, dom_specified, path, secure, expires, name, value = line.split()

                # for some reason important entries are commented out
                if domain.startswith('#'):
                    domain = domain[1:]

                domain = domain.replace('HttpOnly_', '')

                if domain not in self.cookies:
                    self.cookies[domain] = [(name, value)]
                else:
                    self.cookies[domain].append((name, value))

    def https_request(self, request):
        try:
            cookies = self.cookies[request.get_host()]
            # concatenate all cookies for the domain with '; '
            request.add_unredirected_header('Cookie', '; '.join(['%s=%s' % c for c in cookies]))
        except KeyError:
            pass

        return urllib2.HTTPSHandler.https_request(self, request)


class RESTService(object):
    """
    An interface to RESTful APIs (e.g. PhEDEx, DBS) with X509 authentication.
    make_request will take the REST "command" and a list of options as arguments.
    Options are chained together with '&' and appended to the url after '?'.
    Returns python-parsed content.
    """

    def __init__(self, config):
        """
        @param config  Required parameters:
                       str url_base      There is no strict rule on separating the URL base and
                                         individual request REST command ('resource' in make_request).
                                         All requests are made to url_base + '/' + resource.
                       Optional parameters:
                       list headers      Additional request headers (All standard headers including
                                         Accept are automatically passed). Default empty.
                       str  accept       Accept header value. Default 'application/json'.
                       type auth_handler Handler class for authentication. Use 'None' for no auth.
                                         default HTTPSCertKeyHandler.
                       conf auth_handler_conf
                       int  num_attempts
        """

        self.url_base = config['url_base']
        self.headers = list(config.get('headers', []))
        self.accept = config.get('accept', 'application/json')
        self.auth_handler = eval(config.get('auth_handler', 'HTTPSCertKeyHandler'))
        self.auth_handler_conf = config.get('auth_handler_conf', Configuration())
        self.num_attempts = config.get('num_attempts', 1)

        self.last_errorcode = 0
        self.last_exception = None

    def make_request(self, resource = '', options = [], method = GET, format = 'url', retry_on_error = True):
        """
        @param resource       What comes after url_base
        @param options        For GET calls, compiled into key=value&key=value&... For POST calls, becomes data
        @param method         GET or POST
        @param format         Format to send data in.
        @param retry_on_error Retry on general error (error code != 400 - Bad request).
        """

        url = self.url_base
        if resource:
            url += '/' + resource

        if method == GET and len(options) != 0:
            if type(options) is list:
                option_tuples = []
                for option in options:
                    if type(option) is tuple:
                        option_tuples.append(option)
                    else:
                        key, _, value = option.partition('=')
                        option_tuples.append((key, value))

                url += '?' + urllib.urlencode(option_tuples)
            elif type(options) is str:
                url += '?' + options

        if LOG.getEffectiveLevel() == logging.DEBUG:
            LOG.debug(url)

        # now query the URL
        request = urllib2.Request(url)

        if method == POST:
            if format == 'url':
                # Options can be a dict or a list of key=value strings or 2-tuples. The latter case allows repeated keys (e.g. dataset=A&dataset=B)
                if type(options) is list:
                    # convert key=value strings to (key, value) 2-tuples
                    optlist = []
                    for opt in options:
                        if type(opt) is tuple:
                            optlist.append(opt)
    
                        elif type(opt) is str:
                            key, eq, value = opt.partition('=')
                            if eq == '=':
                                if re.match('^\[.+\]$', value):
                                    value = map(str.strip, value[1:-1].split(','))

                                optlist.append((key, value))
    
                    options = optlist

                data = urllib.urlencode(options)

            elif format == 'json':
                # Options must be jsonizable.
                request.add_header('Content-type', 'application/json')
                data = json.dumps(options)

            request.add_data(data)

        wait = 1.
        exceptions = []
        last_errorcode = 0
        last_except = None
        while len(exceptions) != self.num_attempts:
            try:
                if self.auth_handler:
                    opener = urllib2.build_opener(self.auth_handler(self.auth_handler_conf))
                else:
                    opener = urllib2.build_opener()

                if 'Accept' not in self.headers:
                    opener.addheaders.append(('Accept', self.accept))

                opener.addheaders.extend(self.headers)

                response = opener.open(request)

                # clean up - break reference cycle so python can free the memory up
                for handler in opener.handlers:
                    handler.parent = None
                del opener

                content = response.read()
                del response

                if self.accept == 'application/json':
                    result = json.loads(content)
                    unicode2str(result)

                elif self.accept == 'application/xml':
                    # TODO implement xml -> dict
                    result = content

                del content

                return result
    
            except urllib2.HTTPError as err:
                self.last_errorcode = err.code
                self.last_exception = (str(err)) + '\nBody:\n' + err.read()
            except:
                self.last_errorcode = 0
                self.last_exception = sys.exc_info()[:2]

            exceptions.append((self.last_errorcode, self.last_exception))

            if not retry_on_error or self.last_errorcode == 400:
                break

            LOG.info('Exception "%s" occurred in %s. Trying again in %.1f seconds.', str(self.last_exception), url, wait)

            time.sleep(wait)
            wait *= 1.5

        # exhausted allowed attempts
        LOG.error('Too many failed attempts in webservice')
        LOG.error('Last error code %d', self.last_errorcode)
        LOG.error('%s' % ' '.join(map(str, exceptions)))

        raise RuntimeError('webservice too many attempts')
