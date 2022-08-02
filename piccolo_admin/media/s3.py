from __future__ import annotations

import asyncio
import functools
import sys
import typing as t
from concurrent.futures import ThreadPoolExecutor

from piccolo.apps.user.tables import BaseUser

from .base import ALLOWED_CHARACTERS, ALLOWED_EXTENSIONS, MediaStorage

if t.TYPE_CHECKING:
    from concurrent.futures._base import Executor


class S3MediaStorage(MediaStorage):
    def __init__(
        self,
        bucket_name: str,
        connection_kwargs: t.Dict[str, t.Any] = None,
        signed_url_expiry: int = 3600,
        executor: t.Optional[Executor] = None,
        allowed_extensions: t.Optional[t.Sequence[str]] = ALLOWED_EXTENSIONS,
        allowed_characters: t.Optional[t.Sequence[str]] = ALLOWED_CHARACTERS,
    ):
        """
        Stores media files in S3 compatible storage. This is a good option when
        you have lots of files to store, and don't want them stored locally
        on a server. Many cloud providers provide S3 compatible storage,
        besides from Amazon Web Services.

        :param bucket_name:
            Which S3 bucket the files are stored in.
        :param connection_kwargs:
            These kwargs are passed directly to ``boto3``. Learn more about
            `available options <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/core/session.html#boto3.session.Session.client>`_.
            For example::

                S3MediaStorage(
                    connection_kwargs={
                        'aws_access_key_id': 'abc123',
                        'aws_secret_access_key': 'xyz789',
                        'endpoint_url': 's3.cloudprovider.com',
                        'region_name': 'uk'
                    }
                )

        :param signed_url_expiry:
            Files are accessed via signed URLs, which are only valid for this
            number of seconds.
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
        """  # noqa: E501

        try:
            import boto3  # noqa
        except ImportError:
            sys.exit(
                "Please install boto3 to use this feature "
                "`pip install 'piccolo_admin[s3]'`"
            )
        else:
            self.boto3 = boto3

        self.bucket_name = bucket_name
        self.connection_kwargs = connection_kwargs
        self.signed_url_expiry = signed_url_expiry
        self.executor = executor or ThreadPoolExecutor(max_workers=10)

        super().__init__(
            allowed_extensions=allowed_extensions,
            allowed_characters=allowed_characters,
        )

    def get_client(self):
        """
        Returns an S3 clent.
        """
        session = self.boto3.session.Session()
        client = session.client(
            "s3",
            **self.connection_kwargs,
        )
        return client

    async def store_file(
        self, file_name: str, file: t.IO, user: t.Optional[BaseUser] = None
    ) -> str:
        loop = asyncio.get_running_loop()

        blocking_function = functools.partial(
            self.store_file_sync, file_name=file_name, file=file, user=user
        )

        file_id = await loop.run_in_executor(self.executor, blocking_function)

        return file_id

    def store_file_sync(
        self, file_name: str, file: t.IO, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        A sync wrapper around :meth:`store_file`.
        """
        file_id = self.generate_file_id(file_name=file_name, user=user)

        client = self.get_client()

        client.upload_fileobj(
            file,
            self.bucket_name,
            file_id,
        )

        return file_id

    async def generate_file_url(
        self, file_id: str, root_url: str, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        This retrieves an absolute URL for the file.
        """
        loop = asyncio.get_running_loop()

        blocking_function: t.Callable = functools.partial(
            self.generate_file_url_sync,
            file_id=file_id,
            root_url=root_url,
            user=user,
        )

        return await loop.run_in_executor(self.executor, blocking_function)

    def generate_file_url_sync(
        self, file_id: str, root_url: str, user: t.Optional[BaseUser] = None
    ) -> str:
        """
        A sync wrapper around :meth:`generate_file_url`.
        """
        s3_client = self.get_client()

        return s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket_name, "Key": file_id},
            ExpiresIn=self.signed_url_expiry,
        )