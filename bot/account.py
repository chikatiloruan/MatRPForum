
import re
import time
from typing import Optional, Dict
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from .utils import normalize_url, log_info, log_error
import datetime
from .forum_tracker import build_cookies  

try:
    from config import FORUM_BASE, XF_LOGIN, XF_PASS
except Exception:
    FORUM_BASE = ""
    XF_LOGIN = ""
    XF_PASS = ""

class Account:
    def __init__(self, login: str = XF_LOGIN, password: str = XF_PASS, session: Optional[requests.Session] = None):
        self.login = login
        self.password = password
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (ForumTracker/1.0)"
        })
        self.logged = False
        self.last_login_ts = 0

    def _debug(self, msg: str):
        try:
            log_info(msg)
        except Exception:
            print(f"[ACCOUNT] {msg}")

    def login_if_needed(self, force: bool = False) -> bool:
        if not force and self.logged and time.time() - self.last_login_ts < 60*30:
            return True
        try:
            return self.login()
        except Exception as e:
            self._debug(f"login_if_needed error: {e}")
            return False

    def login(self) -> bool:
        if not FORUM_BASE:
            self._debug("FORUM_BASE not configured")
            return False
        login_url = urljoin(FORUM_BASE, "/index.php?login/login")
        page = self.session.get(FORUM_BASE, timeout=15)
        if page.status_code != 200:
            self._debug(f"login: fetch base failed {page.status_code}")
        soup = BeautifulSoup(page.text or "", "html.parser")
        t = soup.find("input", {"name": "_xfToken"})
        token = t.get("value") if t else ""

        payload = {
            "login": self.login,
            "password": self.password,
            "remember": "1",
            "_xfWithData": "1",
            "_xfResponseType": "json",
        }
        if token:
            payload["_xfToken"] = token

       
        try:
            r = self.session.post(login_url, data=payload, timeout=15)
           
            verify = self.session.get(FORUM_BASE, timeout=15)
            html = verify.text or ""
            logged = ("logout" in html.lower()) or ("выйти" in html.lower()) or ('data-logged-in="true"' in html)
            self.logged = bool(logged)
            if self.logged:
                self.last_login_ts = time.time()
            self._debug(f"Login attempt -> logged={self.logged} status={getattr(r,'status_code',None)}")
            return self.logged
        except Exception as e:
            self._debug(f"login error: {e}")
            self.logged = False
            return False

    def ensure_session_cookies(self):
  
        return {c.name: c.value for c in self.session.cookies}

    def fetch_profile(self, profile_url_or_id: str) -> Dict:
        """
        Return dictionary with available profile info.
        profile_url_or_id may be '/index.php?members/...' or numeric id.
        """
        out = {}
        try:
            if profile_url_or_id.isdigit():
                url = urljoin(FORUM_BASE, f"/index.php?members/{profile_url_or_id}/")
            else:
                url = normalize_url(profile_url_or_id)
                if not url.startswith(FORUM_BASE):
                    url = urljoin(FORUM_BASE, profile_url_or_id)
            r = self.session.get(url, timeout=15)
            if r.status_code != 200:
                return {"error": f"HTTP {r.status_code}"}
            soup = BeautifulSoup(r.text or "", "html.parser")
            out["display_name"] = (soup.select_one(".p-body-header h1") or soup.select_one(".message-name") or soup.select_one(".avatar-name")).get_text(strip=True) if soup.select_one(".p-body-header h1") else ""
          
            stats = {}
            for el in soup.select(".pairs.pairs--columns dd"):
             
                try:
                    k = el.previous_sibling.previous_sibling.get_text(strip=True)
                    stats[k] = el.get_text(strip=True)
                except Exception:
                    pass
            out["raw_stats"] = stats
            
            ava = soup.select_one(".p-memberHeader-avatar img")
            out["avatar"] = ava.get("src") if ava else ""
            return out
        except Exception as e:
            return {"error": str(e)}
