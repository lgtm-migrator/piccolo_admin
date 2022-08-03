from __future__ import annotations

import abc
import asyncio
import logging
import pathlib
import string
import typing as t
import uuid

from piccolo.apps.user.tables import BaseUser
from piccolo.columns.column_types import Array, Text, Varchar

logger = logging.getLogger(__file__)


AUDIO_EXTENSIONS = (
    "mp3",
    "wav",
)

DATA_EXTENSIONS = (
    "csv",
    "tsv",
)

DOCUMENT_EXTENSIONS = ("pdf",)

IMAGE_EXTENSIONS = (
    "gif",
    "jpeg",
    "jpg",
    "png",
    "svg",
    "tif",
    "webp",
)

TEXT_EXTENSIONS = (
    "rtf",
    "txt",
)

VIDEO_EXTENSIONS = ("mov", "mp4", "webm")

ALLOWED_EXTENSIONS = (
    *AUDIO_EXTENSIONS,
    *DATA_EXTENSIONS,
    *DOCUMENT_EXTENSIONS,
    *IMAGE_EXTENSIONS,
    *TEXT_EXTENSIONS,
    *VIDEO_EXTENSIONS,
)

ALLOWED_CHARACTERS = (
    *string.ascii_letters,
    *string.digits,
    " ",
    "-",
    "_",
    ".",
)


ALLOWED_COLUMN_TYPES = (Varchar, Text)


# TODO - might move this to Piccolo API.
class MediaStorage(metaclass=abc.ABCMeta):
    """
    If you want to implement media uploads, use a subclass of this class.
    """

    def __init__(
        self,
        column: t.Union[Text, Varchar, Array],
        allowed_extensions: t.Optional[t.Sequence[str]] = ALLOWED_EXTENSIONS,
        allowed_characters: t.Optional[t.Sequence[str]] = ALLOWED_CHARACTERS,
    ):
        if not (
            isinstance(column, ALLOWED_COLUMN_TYPES)
            or (
                isinstance(column, Array)
                and isinstance(column.base_column, ALLOWED_COLUMN_TYPES)
            )
        ):
            raise ValueError(
                "The column must be a `Varchar`, `Text`, or `Array`."
            )

        self.column = column
        self.allowed_extensions = (
            [i.lower() for i in allowed_extensions]
            if allowed_extensions
            else None
        )
        self.allowed_characters = allowed_characters

    def generate_file_id(
        self, file_name: str, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        Generates a unique file ID. If you have your own strategy for naming
        files, you can override this method.

        By default we add a UUID to the filename, to make it unique::

            >>> self.generate_file_id(file_name='my-poster.jpg')
            my-poster-3beac950-7721-46c9-9e7d-5e908ef51011.jpg

        :raises ValueError:
            If the ``file_name`` is invalid.

        """
        if not file_name:
            # It's unlikely that the file_name is an empty string, but just in
            # case.
            raise ValueError("The file name can't be empty.")

        # If the file_name includes the entire path (e.g. /foo/bar.jpg) - we
        # just want bar.jpg.
        file_name = pathlib.Path(file_name).name

        # Don't allow the file name to begin with a dot, otherwise it will be a
        # hidden file on Unix.
        if file_name.startswith("."):
            raise ValueError("File names must not start with a period.")

        # Don't allow double dots in the file name, in case it allows a file to
        # be written to a parent folder.
        if ".." in file_name:
            raise ValueError("File names must not contain '..'.")

        if self.allowed_characters:
            # Having some restriction on the allowed characters is important,
            # in case there are things like null bytes in there.
            # https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html#extension-validation
            for character in file_name:
                if character not in self.allowed_characters:
                    raise ValueError(
                        f"'{character}' is not allowed in the filename."
                    )

        components = file_name.rsplit(".", 1)

        if len(components) == 2:
            name, extension = components

            if self.allowed_extensions:
                if extension.lower() not in self.allowed_extensions:
                    # TODO - inspect the files to make sure they are what
                    # they say they are.
                    raise ValueError("This file type isn't allowed.")
        else:
            raise ValueError("The file has no extension.")

        if len(file_name) > 50:
            # Truncate really long names. Otherwise they might be too long
            # for some operating systems, or too long to be stored in a
            # database field.
            name = name[:50]

        uuid_ = uuid.uuid4()

        file_id = f"{name}-{uuid_}"
        if extension:
            file_id += f".{extension}"

        return file_id

    ###########################################################################

    @abc.abstractmethod
    async def store_file(
        self, file_name: str, file: t.IO, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        Stores the file in whichever storage you're using, and returns a key
        which uniquely identifes the file.

        :param file:
            The file to store.
        :param user:
            The Piccolo ``BaseUser`` who requested this.

        """
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    async def generate_file_url(
        self, file_id: str, root_url: str, user: t.Optional[BaseUser] = None
    ):
        """
        This retrieves an absolute URL for the file. It might be a signed URL,
        if using S3 for storage.

        :param file_id:
            Get the URL for a file with this file_id.
        :param root_url:
            The URL the media is usually served from. The sub class might
            ignore this argument entirely, if it's fetching the data from
            an external source like S3.
        :param user:
            The Piccolo ``BaseUser`` who requested this.
        """
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    async def get_file(self, file_key: str) -> t.Optional[t.IO]:
        """
        Returns the file object matching the ``file_key``.
        """
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    async def delete_file(self, file_key: str):
        """
        Deletes the file object matching the ``file_key``.
        """
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    async def bulk_delete_files(self, file_keys: t.List[str]):
        raise NotImplementedError  # pragma: no cover

    @abc.abstractmethod
    async def get_file_keys(self) -> t.List[str]:
        """
        Returns the file key for each file we have stored.
        """
        raise NotImplementedError  # pragma: no cover

    ###########################################################################

    async def get_file_keys_from_db(self) -> t.List[str]:
        """
        Returns the file key for each file we have in the database.
        """
        table = self.column._meta.table
        return await table.select(self.column).output(as_list=True)

    async def get_unused_file_keys(self) -> t.List[str]:
        """
        Compares the file keys we have stored, vs what's in the database.
        """
        db_keys, disk_keys = await asyncio.gather(
            self.get_file_keys_from_db(), self.get_file_keys()
        )
        return list(set(disk_keys) - set(db_keys))

    async def delete_unused_files(
        self, number_shown: int = 10, auto: bool = False
    ):
        """
        Over time, you will end up with files stored which are no longer
        needed. For example, if a row is deleted in the database, which
        referenced a stored file.

        By periodically running this method, it will clean up these unused
        files.

        It's important that each column uses its own folder for storing files.
        If multiple columns store data in the same folder, then we could
        delete some files which are needed by another column.

        :param number_shown:
            This number of unused file names are printed out, so you can be
            sure nothing strange is going on.
        :param auto:
            If ``True``, no confirmation is required before deletion takes
            place.

        """
        unused_file_keys = await self.get_unused_file_keys()

        number_unused = len(unused_file_keys)

        print(f"There are {number_unused} unused files.")

        if number_unused:
            print("Here are some examples:")
            print("\n".join(i for i in unused_file_keys[:number_shown]))

            if auto or (
                input("Would you like to delete them? Enter y to confirm")
                == "y"
            ):
                await self.bulk_delete_files(unused_file_keys)
