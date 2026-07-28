from pydantic import BeforeValidator
from typing_extensions import Annotated


SnowflakeId = Annotated[str, BeforeValidator(lambda value: str(value))]
