import asyncio
import tempfile
import uuid
from unittest import TestCase
from unittest.mock import MagicMock, patch

from piccolo.table import create_db_tables_sync, drop_db_tables_sync

from piccolo_admin.example import Director, Movie, Studio
from piccolo_admin.media.local import LocalMediaStorage


class TestGenerateFileID(TestCase):
    def setUp(self) -> None:
        self.media_path = tempfile.gettempdir()
        self.storage = LocalMediaStorage(
            column=Movie.poster, media_path=self.media_path
        )

    def test_starts_with_period(self):
        with self.assertRaises(ValueError) as manager:
            self.storage.generate_file_id(file_name=".private_file.jpeg")

        self.assertEqual(
            str(manager.exception), "File names must not start with a period."
        )

    def test_double_period(self):
        """
        A file_name containing a double period shouldn't be allowed, as it
        could potentially be used to traverse the file system.
        """
        with self.assertRaises(ValueError) as manager:
            self.storage.generate_file_id(file_name="test..file.jpeg")

        self.assertEqual(
            str(manager.exception), "File names must not contain '..'."
        )

    def test_empty_file_name(self):
        with self.assertRaises(ValueError) as manager:
            self.storage.generate_file_id(file_name="")

        self.assertEqual(
            str(manager.exception), "The file name can't be empty."
        )

    def test_allowed_extensions(self):
        with self.assertRaises(ValueError) as manager:
            self.storage.generate_file_id(
                file_name="test.abcdefghijklmonpqrstuvwxyz123"
            )

        self.assertEqual(
            str(manager.exception), "This file type isn't allowed."
        )

    def test_allowed_characters(self):
        with self.assertRaises(ValueError) as manager:
            self.storage.generate_file_id(file_name="@{£}%^*jpeg")

        self.assertEqual(
            str(manager.exception), "'@' is not allowed in the filename."
        )

    @patch("piccolo_admin.media.base.uuid")
    def test_long_file_name(self, uuid_module: MagicMock):
        """
        Make sure that really long file names are truncated.
        """
        uuid_module.uuid4.return_value = uuid.UUID(
            "fd0125c7-8777-4976-83c1-81605d5ab155"
        )

        truncated_file_id = self.storage.generate_file_id(
            file_name="".join("a" for _ in range(200)) + ".jpg"
        )
        self.assertEqual(
            truncated_file_id,
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-fd0125c7-8777-4976-83c1-81605d5ab155.jpg",  # noqa: E501
        )


class TestGetFileKeysFromDB(TestCase):
    def setUp(self):
        create_db_tables_sync(Movie, Director, Studio)

    def tearDown(self):
        drop_db_tables_sync(Movie, Director, Studio)

    def test_get_file_keys_from_db(self):
        Movie.insert(
            Movie(poster="image-1.jpg"),
            Movie(poster="image-2.jpg"),
            Movie(poster="image-3.jpg"),
        ).run_sync()

        storage = LocalMediaStorage(column=Movie.poster, media_path="/tmp/")

        response = asyncio.run(storage.get_file_keys_from_db())

        self.assertListEqual(
            sorted(response), ["image-1.jpg", "image-2.jpg", "image-3.jpg"]
        )
