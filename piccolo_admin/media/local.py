from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import shutil
import typing as t
from concurrent.futures import ThreadPoolExecutor

from piccolo.apps.user.tables import BaseUser
from piccolo.utils.sync import run_sync

from .base import ALLOWED_CHARACTERS, ALLOWED_EXTENSIONS, MediaStorage

if t.TYPE_CHECKING:
    from concurrent.futures._base import Executor


logger = logging.getLogger(__file__)


class LocalMediaStorage(MediaStorage):
    def __init__(
        self,
        media_path: str,
        executor: t.Optional[Executor] = None,
        allowed_extensions: t.Optional[t.Sequence[str]] = ALLOWED_EXTENSIONS,
        allowed_characters: t.Optional[t.Sequence[str]] = ALLOWED_CHARACTERS,
        file_permissions: t.Optional[int] = 0o640,
    ):
        """
        Stores media files on a local path. This is good for simple
        applications, where you're happy with the media files being stored
        on a single server.

        :param media_path:
            This is the local folder where the media files will be stored. It
            should be an absolute path. For example, ``'/srv/piccolo-media/'``.
        :param executor:
            An executor, which file save operations are run in, to avoid
            blocking the event loop. If not specified, we use a sensibly
            configured :class:`ThreadPoolExecutor <concurrent.futures.ThreadPoolExecutor>`.
        :param allowed_extensions:
            Which file extensions are allowed. If ``None``, then all extensions
            are allowed (not recommended unless the users are trusted).
        :param allowed_characters:
            Which characters are allowed in the file name. By default, it's
            very strict. If set to ``None`` then all characters are allowed.
        :param file_permissions:
            If set to a value other than ``None``, then all uploaded files are
            given these file permissions.
        """  # noqa: E501
        self.media_path = media_path
        self.executor = executor or ThreadPoolExecutor(max_workers=10)
        self.file_permissions = file_permissions

        if not os.path.exists(media_path):
            os.mkdir(self.media_path)

        super().__init__(
            allowed_extensions=allowed_extensions,
            allowed_characters=allowed_characters,
        )

    async def store_file(
        self, file_name: str, file: t.IO, user: t.Optional[BaseUser] = None
    ) -> str:
        # If the file_name includes the entire path (e.g. /foo/bar.jpg) - we
        # just want bar.jpg.
        file_name = pathlib.Path(file_name).name

        file_id = self.generate_file_id(file_name=file_name, user=user)

        loop = asyncio.get_running_loop()
        file_permissions = self.file_permissions

        def save():
            path = os.path.join(self.media_path, file_id)

            if os.path.exists(path):
                logger.error(
                    "A file name clash has occurred - the chances are very "
                    "low. Could be malicious, or a serious bug."
                )
                raise IOError("Unable to save the file")

            with open(path, "wb") as new_file:
                shutil.copyfileobj(file, new_file)
                if file_permissions is not None:
                    os.chmod(path, 0o640)

        await loop.run_in_executor(self.executor, save)

        return file_id

    def store_file_sync(
        self, file_name: str, file: t.IO, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        A sync wrapper around :meth:`store_file`.
        """
        return run_sync(
            self.store_file(file_name=file_name, file=file, user=user)
        )

    async def generate_file_url(
        self, file_id: str, root_url: str, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        This retrieves an absolute URL for the file.
        """
        return "/".join((root_url.rstrip("/"), file_id))

    def generate_file_url_sync(
        self, file_id: str, root_url: str, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        A sync wrapper around :meth:`generate_file_url`.
        """
        return run_sync(
            self.generate_file_url(
                file_id=file_id, root_url=root_url, user=user
            )
        )