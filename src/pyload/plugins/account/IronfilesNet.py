# -*- coding: utf-8 -*-

import json
import time

from pyload.plugins.internal.account import Account


class IronfilesNet(Account):
    __name__ = "IronfilesNet"
    __type__ = "account"
    __version__ = "0.01"
    __status__ = "testing"

    __pyload_version__ = "0.5"

    __description__ = """Ironfiles.net account plugin"""
    __license__ = "GPLv3"
    __authors__ = [("GammaC0de", "nitzo2001[AT]yahoo[DOT]com")]

    API_URL = "https://ironfiles.net/api/"

    def api_response(self, method, **kwargs):
        json_data = self.load(self.API_URL + method, get=kwargs)
        return json.loads(json_data)

    def grab_info(self, user, password, data):
        json_data = self.api_response("accountStatus")

        expires = json_data["expires"].split("T", 1)
        validuntil = time.mktime(
            time.strptime(expires[0] + expires[1][:8], "%Y-%m-%d%H:%M:%S")
        )

        return {
            "validuntil": validuntil,
            "trafficleft": -1,
            "premium": json_data["premium"],
        }

    def signin(self, user, password, data):
        json_data = self.api_response("auth", login=user, password=password)

        if not json_data["result"]:
            self.fail_login(json_data["message"])
