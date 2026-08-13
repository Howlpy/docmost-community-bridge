import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("DOCMOST_EMAIL", "bot@example.test")
os.environ.setdefault("DOCMOST_PASSWORD", "test-password")
os.environ.setdefault("BRIDGE_TOKEN", "test-token")

from server import DocmostClient


class CreateSpaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = DocmostClient()

    async def asyncTearDown(self) -> None:
        await self.client._client.aclose()

    async def test_new_space_is_shared_with_everyone(self) -> None:
        self.client.post = AsyncMock(side_effect=[
            {"id": "space-1", "name": "Product", "slug": "product"},
            {"items": [{"id": "everyone-1", "name": "Everyone", "isDefault": True}]},
            {"success": True},
        ])

        created = await self.client.create_space("Product")

        self.assertEqual(created["id"], "space-1")
        self.assertEqual(
            self.client.post.await_args_list[2].args,
            (
                "spaces/members/add",
                {
                    "spaceId": "space-1",
                    "role": "writer",
                    "userIds": [],
                    "groupIds": ["everyone-1"],
                },
            ),
        )

    async def test_membership_failure_rolls_back_space(self) -> None:
        self.client.post = AsyncMock(side_effect=[
            {"id": "space-1", "name": "Product", "slug": "product"},
            {"items": []},
            {"success": True},
        ])

        with self.assertRaisesRegex(RuntimeError, "Everyone"):
            await self.client.create_space("Product")

        self.assertEqual(
            self.client.post.await_args_list[-1].args,
            ("spaces/delete", {"spaceId": "space-1"}),
        )

    async def test_private_space_skips_group_membership(self) -> None:
        self.client.post = AsyncMock(return_value={
            "id": "space-1", "name": "Private", "slug": "private"
        })

        await self.client.create_space("Private", visible_to_everyone=False)

        self.client.post.assert_awaited_once()

    async def test_delete_space_uses_validated_immutable_id(self) -> None:
        self.client.post = AsyncMock(return_value={"deleted": True})
        space_id = "019ffb2a-1234-7abc-8def-1234567890ab"

        await self.client.delete_space(space_id)

        self.client.post.assert_awaited_once_with(
            "spaces/delete", {"spaceId": space_id}
        )

    async def test_delete_space_rejects_unvalidated_ids(self) -> None:
        self.client.post = AsyncMock()

        with self.assertRaisesRegex(ValueError, "valid space_id"):
            await self.client.delete_space("General")

        self.client.post.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
