from typing import Optional

from pydantic import BaseModel


class PushRequest(BaseModel):
    do_rest: Optional[int] = 0


class SearchRequest(BaseModel):
    text: str
    limit: Optional[int] = 10
