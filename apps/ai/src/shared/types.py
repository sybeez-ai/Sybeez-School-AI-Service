from typing import Annotated
from uuid import UUID

from pydantic import Field

SchoolId = Annotated[UUID, Field(description="Tenant school id")]
StudentId = Annotated[UUID, Field(description="Student id")]
UserId = Annotated[UUID, Field(description="User id")]
