from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Comparison(StrictModel):
    left: str=Field(min_length=1)
    right: str=Field(min_length=1)
    type: Literal['text','number']='text'
    tolerance: Decimal=Field(default=Decimal(0),ge=0,le=Decimal('1e20'),allow_inf_nan=False)
class Recipe(StrictModel):
    version: Literal[1]=1
    left_key: str=Field(min_length=1)
    right_key: str=Field(min_length=1)
    trim: bool=True
    ignore_case: bool=True
    include_missing: bool=True
    comparisons: list[Comparison]=Field(min_length=1,max_length=30)
class DatasetInput(StrictModel):
    name: str=Field(min_length=1,max_length=200)
    text: str=Field(max_length=3_500_000)
class Pair(StrictModel):
    left_id: str
    right_id: str
class PreviewInput(Pair):
    recipe: Recipe
class ExecuteInput(StrictModel):
    preview_id: str
    name: str = Field(default="",max_length=160)
class RecipeInput(StrictModel):
    name: str=Field(min_length=1,max_length=100)
    recipe: Recipe

