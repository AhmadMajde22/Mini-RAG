from sqlalchemy.future import select

from .BaseDataModel import BaseDataModel
from .db_schemas import Asset


class AssetModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_asset(self, asset: Asset):
        async with self.db_client() as session:
            session.add(asset)
            await session.commit()
            await session.refresh(asset)

        return asset

    async def get_all_project_assets(self, asset_project_id: int, asset_type: str):
        async with self.db_client() as session:
            result = await session.execute(
                select(Asset)
                .where(Asset.asset_project_id == asset_project_id)
                .where(Asset.asset_type == asset_type)
                .order_by(Asset.asset_id)
            )

            return result.scalars().all()

    async def get_asseet_record(self, asset_project_id: int, asset_name: str):
        async with self.db_client() as session:
            result = await session.execute(
                select(Asset)
                .where(Asset.asset_project_id == asset_project_id)
                .where(Asset.asset_name == asset_name)
            )

            return result.scalar_one_or_none()
