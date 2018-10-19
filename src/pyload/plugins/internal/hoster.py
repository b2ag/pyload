# -*- coding: utf-8 -*-

import mimetypes
import os
import re
from builtins import _, range

from pyload.network.http_request import BadHeader
from pyload.plugins.internal.base import Base
from pyload.plugins.internal.plugin import Fail
from pyload.plugins.utils import encode, exists, parse_name, safejoin


class Hoster(Base):
    __name__ = "Hoster"
    __type__ = "hoster"
    __version__ = "0.73"
    __status__ = "stable"

    __pyload_version__ = "0.5"

    __pattern__ = r"^unmatchable$"
    __config__ = [
        ("activated", "bool", "Activated", True),
        ("use_premium", "bool", "Use premium account if available", True),
        ("fallback", "bool", "Fallback to free download if premium fails", True),
    ]

    __description__ = """Base hoster plugin"""
    __license__ = "GPLv3"
    __authors__ = [("Walter Purcaro", "vuolter@gmail.com")]

    @property
    def last_download(self):
        return self._last_download if exists(self._last_download) else ""

    @last_download.setter
    def last_download(self, value):
        if exists(value):
            self._last_download = value or ""

    def init_base(self):
        #: Enable simultaneous processing of multiple downloads
        self.limitDL = 0  # TODO: Change to `limit_dl` in 0.6.x

        #:
        self.chunk_limit = None

        #:
        self.resume_download = False

        #: Location where the last call to download was saved
        self._last_download = ""

        #: Re match of the last call to `checkDownload`
        self.last_check = None

        #: Restart flag
        self.restart_free = False  # TODO: Recheck in 0.6.x

        #: Download is possible with premium account only, don't fallback to free download
        self.no_fallback = False

    def setup_base(self):
        self.last_download = None
        self.last_check = None
        self.restart_free = False
        self.no_fallback = False

        if self.account:
            self.chunk_limit = -1  #: -1 for unlimited
            self.resume_download = True
        else:
            self.chunk_limit = 1
            self.resume_download = False

    def load_account(self):
        if self.restart_free:
            self.account = False
            self.user = None  # TODO: Remove in 0.6.x
        else:
            Base.load_account(self)
            # self.restart_free = False

    def _process(self, thread):
        self.thread = thread

        try:
            self._initialize()
            self._setup()

            # TODO: Enable in 0.6.x
            # self.pyload.addonManager.downloadPreparing(self.pyfile)
            # self.check_status()
            self.check_duplicates()

            self.pyfile.setStatus("starting")

            try:
                self.log_info(_("Processing url: ") + self.pyfile.url)
                self.process(self.pyfile)
                self.check_status()

                self._check_download()

            except Fail as e:  # TODO: Move to PluginThread in 0.6.x
                self.log_warning(
                    _("Premium download failed")
                    if self.premium
                    else _("Free download failed"),
                    e,
                )
                if (
                    not self.no_fallback
                    and self.config.get("fallback", True)
                    and self.premium
                ):
                    self.restart(premium=False)

                else:
                    raise Fail(encode(e))

        finally:
            self._finalize()

    # TODO: Remove in 0.6.x
    def _finalize(self):
        pypack = self.pyfile.package()

        self.pyload.addonManager.dispatchEvent("download_processed", self.pyfile)

        try:
            unfinished = any(
                fdata.get("status") in (3, 7)
                for fid, fdata in pypack.getChildren().items()
                if fid != self.pyfile.id
            )
            if unfinished:
                return

            self.pyload.addonManager.dispatchEvent("package_processed", pypack)

            failed = any(
                fdata.get("status") in (1, 6, 8, 9, 14)
                for fid, fdata in pypack.getChildren().items()
            )

            if not failed:
                return

            self.pyload.addonManager.dispatchEvent("package_failed", pypack)

        finally:
            self.check_status()

    def isresource(self, url, redirect=True, resumable=None):
        resource = False
        maxredirs = 5

        if resumable is None:
            resumable = self.resume_download

        if isinstance(redirect, int):
            maxredirs = max(redirect, 1)

        elif redirect:
            maxredirs = (
                int(self.config.get("maxredirs", plugin="UserAgentSwitcher"))
                or maxredirs
            )  # TODO: Remove `int` in 0.6.x

        header = self.load(url, just_header=True)

        for i in range(1, maxredirs):
            if not redirect or header.get("connection") == "close":
                resumable = False

            if "content-disposition" in header:
                resource = url

            elif header.get("location"):
                location = self.fixurl(header.get("location"), url)
                code = header.get("code")

                if code in (301, 302) or resumable:
                    self.log_debug("Redirect #{} to: {}".format(i, location))
                    header = self.load(location, just_header=True)
                    url = location
                    continue

            else:
                contenttype = header.get("content-type")
                extension = os.path.splitext(parse_name(url))[-1]

                if contenttype:
                    mimetype = contenttype.split(";")[0].strip()

                elif extension:
                    mimetype = (
                        mimetypes.guess_type(extension, False)[0]
                        or "application/octet-stream"
                    )

                else:
                    mimetype = None

                if mimetype and (resource or "html" not in mimetype):
                    resource = url
                else:
                    resource = False

            return resource

    def _download(
        self, url, filename, get, post, ref, cookies, disposition, resume, chunks
    ):
        # TODO: Safe-filename check in HTTPDownload in 0.6.x
        file = encode(filename)
        resume = self.resume_download if resume is None else bool(resume)

        dl_chunks = self.pyload.config.get("download", "chunks")
        chunk_limit = chunks or self.chunk_limit or -1

        if -1 in (dl_chunks, chunk_limit):
            chunks = max(dl_chunks, chunk_limit)
        else:
            chunks = min(dl_chunks, chunk_limit)

        try:
            newname = self.req.httpDownload(
                url,
                file,
                get,
                post,
                ref,
                cookies,
                chunks,
                resume,
                self.pyfile.setProgress,
                disposition,
            )

        except IOError as e:
            self.log_error(e)
            self.fail(_("IOError {}").format(e.errno))

        except BadHeader as e:
            self.req.http.code = e.code
            raise

        else:
            if self.req.code in (404, 410):
                bad_file = os.path.join(os.path.dirname(filename), newname)
                if self.remove(bad_file):
                    return ""
            else:
                self.log_info(_("File saved"))

            return newname

        finally:
            self.pyfile.size = self.req.size
            self.captcha.correct()

    def download(
        self,
        url,
        get={},
        post={},
        ref=True,
        cookies=True,
        disposition=True,
        resume=None,
        chunks=None,
        fixurl=True,
    ):
        """
        Downloads the content at url to download folder.

        :param url:
        :param get:
        :param post:
        :param ref:
        :param cookies:
        :param disposition: if True and server provides content-disposition header\
        the filename will be changed if needed
        :return: The location where the file was saved
        """
        self.check_status()

        if self.pyload.debug:
            self.log_debug(
                "DOWNLOAD URL " + url,
                *[
                    "{}={}".format(key, value)
                    for key, value in locals().items()
                    if key not in ("self", "url", "_[1]")
                ],
            )

        dl_url = self.fixurl(url) if fixurl else url
        dl_basename = parse_name(self.pyfile.name)

        self.pyfile.name = dl_basename

        self.check_duplicates()

        self.pyfile.setStatus("downloading")

        dl_folder = self.pyload.config.get("general", "download_folder")
        dl_dirname = safejoin(dl_folder, self.pyfile.package().folder)
        dl_filename = safejoin(dl_dirname, dl_basename)

        dl_dir = encode(dl_dirname)
        dl_file = encode(dl_filename)

        os.makedirs(dl_dir, exist_ok=True)
        self.set_permissions(dl_dir)

        self.pyload.addonManager.dispatchEvent(
            "download_start", self.pyfile, dl_url, dl_filename
        )
        self.check_status()

        newname = self._download(
            dl_url, dl_filename, get, post, ref, cookies, disposition, resume, chunks
        )

        # TODO: Recheck in 0.6.x
        if disposition and newname:
            safename = parse_name(newname.split(" filename*=")[0])

            if safename != newname:
                try:
                    old_file = os.path.join(dl_dirname, newname)
                    new_file = os.path.join(dl_dirname, safename)
                    os.rename(old_file, new_file)

                except OSError as e:
                    self.log_warning(
                        _("Error renaming `{}` to `{}`").format(newname, safename), e
                    )
                    safename = newname

                self.log_info(
                    _("`{}` saved as `{}`").format(self.pyfile.name, safename)
                )

            self.pyfile.name = safename

            dl_filename = os.path.join(dl_dirname, safename)
            dl_file = encode(dl_filename)

        self.set_permissions(dl_file)

        self.last_download = dl_filename

        return dl_filename

    def scan_download(self, rules, read_size=1_048_576):
        """
        Checks the content of the last downloaded file, re match is saved to
        `last_check`

        :param rules: dict with names and rules to match (compiled regexp or strings)
        :param delete: delete if matched
        :return: dictionary key of the first rule that matched
        """
        dl_file = encode(self.last_download)  # TODO: Recheck in 0.6.x

        if not self.last_download:
            self.log_warning(_("No file to scan"))
            return

        with open(dl_file, mode="rb") as f:
            content = f.read(read_size)

        #: Produces encoding errors, better log to other file in the future?
        # self.log_debug("Content: {}".format(content))
        for name, rule in rules.items():
            if isinstance(rule, str):
                if rule in content:
                    return name

            elif hasattr(rule, "search"):
                m = rule.search(content)
                if m is not None:
                    self.last_check = m
                    return name

    def _check_download(self):
        self.log_info(_("Checking download..."))
        self.pyfile.setCustomStatus(_("checking"))

        if not self.last_download:
            if self.captcha.task:
                self.retry_captcha()
            else:
                self.error(_("No file downloaded"))

        elif self.scan_download({"Empty file": re.compile(r"\A((.|)(\2|\s)*)\Z")}):
            if self.remove(self.last_download):
                self.last_download = ""
            self.error(_("Empty file"))

        else:
            self.pyload.addonManager.dispatchEvent("download_check", self.pyfile)
            self.check_status()

        self.log_info(_("File is OK"))

    def out_of_traffic(self):
        if not self.account:
            return

        traffic = self.account.get_data("trafficleft")

        if traffic is None:
            return True

        elif traffic == -1:
            return False

        else:
            # TODO: Rewrite in 0.6.x
            size = self.pyfile.size >> 10
            self.log_info(
                _("Filesize: {} KiB").format(size),
                _("Traffic left for user `{}`: {} KiB").format(
                    self.account.user, traffic
                ),
            )
            return size > traffic

    # def check_size(self, file_size, size_tolerance=1 << 10, delete=False):
    # """
    # Checks the file size of the last downloaded file

    # :param file_size: expected file size
    # :param size_tolerance: size check tolerance
    # """
    # self.log_info(_("Checking file size..."))

    # if not self.last_download:
    # self.log_warning(_("No file to check"))
    # return

    # dl_file = encode(self.last_download)
    # dl_size = os.stat(dl_file).st_size

    # try:
    # if dl_size == 0:
    # delete = True
    # self.fail(_("Empty file"))

    # elif file_size > 0:
    # diff = abs(file_size - dl_size)

    # if diff > size_tolerance:
    # self.fail(_("File size mismatch | Expected file size: {} bytes | Downloaded file size: {} bytes").format((file_size), dl_size))

    # elif diff != 0:
    # self.log_warning(_("File size is not equal to expected download size, but does not exceed the tolerance threshold"))
    # self.log_debug("Expected file size: {} bytes".format(file_size)
    # "Downloaded file size: {} bytes".format(dl_size)
    # "Tolerance threshold: {} bytes".format(size_tolerance))
    # else:
    # delete = False
    # self.log_info(_("File size match"))

    # finally:
    # if delete:
    # self.remove(dl_file, trash=False)

    # def check_hash(self, type, digest, delete=False):
    # hashtype = type.strip('-').upper()

    # self.log_info(_("Checking file hashsum {}...").format(hashtype))

    # if not self.last_download:
    # self.log_warning(_("No file to check"))
    # return

    # dl_file = encode(self.last_download)

    # try:
    # dl_hash   = digest
    # file_hash = compute_checksum(dl_file, hashtype)

    # if not file_hash:
    # self.fail(_("Unsupported hashing algorithm: ") + hashtype)

    # elif dl_hash == file_hash:
    # delete = False
    # self.log_info(_("File hashsum {} match").format(hashtype))

    # else:
    # self.fail(_("File hashsum {} mismatch | Expected file hashsum: {} | Downloaded file hashsum: {}").format(hashtype, dl_hash, file_hash))
    # finally:
    # if delete:
    # self.remove(dl_file, trash=False)

    def check_duplicates(self):
        """
        Checks if same file was downloaded within same package.

        :raises Skip:
        """
        pack_folder = self.pyfile.package().folder

        for pyfile in self.pyload.files.cache.values():
            if (
                pyfile != self.pyfile
                and pyfile.name == self.pyfile.name
                and pyfile.package().folder == pack_folder
            ):
                if pyfile.status in (
                    0,
                    12,
                    5,
                    7,
                ):  #: finished / downloading / waiting / starting
                    self.skip(pyfile.pluginname)

        dl_folder = self.pyload.config.get("general", "download_folder")
        dl_file = os.path.join(dl_folder, pack_folder, self.pyfile.name)

        if not exists(dl_file):
            return

        if os.stat(dl_file).st_size == 0:
            if self.remove(self.last_download):
                self.last_download = ""
            return

        if self.pyload.config.get("download", "skip_existing"):
            plugin = self.pyload.db.findDuplicates(
                self.pyfile.id, pack_folder, self.pyfile.name
            )
            msg = plugin[0] if plugin else _("File exists")
            self.skip(msg)

        else:
            # Same file exists but it does not belongs to our pack, add a trailing
            # counter
            m = re.match(r"(.+?)(?: \((\d+)\))?(\..+)?$", self.pyfile.name)
            dl_n = int(m.group(2) or "0")

            while True:
                name = "{} ({}){}".format(m.group(1), dl_n + 1, m.group(3) or "")
                dl_file = os.path.join(dl_folder, pack_folder, name)
                if not exists(dl_file):
                    break

                dl_n += 1

            self.pyfile.name = name

    #: Deprecated method (Recheck in 0.6.x)
    def checkForSameFiles(self, *args, **kwargs):
        pass
