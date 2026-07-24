from sqlalchemy import func
from sqlalchemy.future import select

from .BaseDataModel import BaseDataModel
from .db_schemas import Project


class ProjectModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_project(self, project: Project):
        async with self.db_client() as session:
            session.add(project)
            await session.commit()
            await session.refresh(project)

        return project

    async def get_project_or_create_one(self, project_id: int):
        async with self.db_client() as session:
            query = select(Project).where(Project.project_id == project_id)
            result = await session.execute(query)
            project = result.scalar_one_or_none()

            if project:
                return project

            project = Project(project_id=project_id)
            session.add(project)
            await session.commit()
            await session.refresh(project)

            return project

    async def get_all_projects(self, page: int = 1, page_size: int = 10):
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10

        async with self.db_client() as session:
            count_result = await session.execute(select(func.count(Project.project_id)))
            total_documents = count_result.scalar_one()

            total_pages = (total_documents + page_size - 1) // page_size

            projects_result = await session.execute(
                select(Project)
                .order_by(Project.project_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            projects = projects_result.scalars().all()

            return projects, total_pages
