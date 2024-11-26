from typing import List, Optional
from pydantic import BaseModel, Field


class SearchConfig(BaseModel):
    herbs: List[str] = Field(..., description="需要搜索的草药列表")
    diseases: List[str] = Field(..., description="需要搜索的疾病列表")
    exact_match: bool = Field(
        False, description="是否进行精确匹配：True 表示精确匹配，False 表示模糊匹配"
    )


class SaveDirConfig(BaseModel):
    autonp: str = Field(..., description="保存汇总数据的目标路径")
    tcmsp: str = Field(..., description="保存 TCMSP 数据的目录路径")
    herbac: str = Field(..., description="保存 HERBac 数据的目录路径")
    swiss: str = Field(..., description="保存 Swiss 数据的目录路径")
    pubchem: str = Field(..., description="保存 PubChem 数据的目录路径")
    uniprot: str = Field(..., description="保存 UniProt 数据的目录路径")


class TCMSPFilterConfig(BaseModel):
    ob: Optional[float] = Field(
        None,
        description="生物利用度（oral bioavailability, OB）阈值，筛选 OB 大于此值的化合物",
    )
    dl: Optional[float] = Field(
        None,
        description="药物类药性（drug-likeness, DL）阈值，筛选 DL 大于此值的化合物",
    )


class HERBacFilterConfig(BaseModel):
    weight: Optional[float] = Field(
        None,
        description="分子量阈值，筛选分子量小于等于此值的化合物，以符合 Lipinski's Rule of Five",
    )


class PubChemFilterConfig(BaseModel):
    xlogp: Optional[float] = Field(
        None,
        description="脂溶性（log P）阈值，筛选 Log P 小于等于此值的化合物",
    )
    hbonddonor: Optional[int] = Field(
        None,
        description="氢键供体数阈值，筛选氢键供体数小于等于此值的化合物",
    )
    hbondacc: Optional[int] = Field(
        None,
        description="氢键受体数阈值，筛选氢键受体数小于等于此值的化合物",
    )


class SwissFilterConfig(BaseModel):
    prob: Optional[float] = Field(
        None,
        description="预测活性概率（Probability*）阈值，筛选概率大于等于此值的化合物",
    )


class FilterConfig(BaseModel):
    tcmsp: TCMSPFilterConfig = Field(
        default_factory=TCMSPFilterConfig,
        description="TCMSP 数据库的筛选条件",
    )
    herbac: HERBacFilterConfig = Field(
        default_factory=HERBacFilterConfig,
        description="HERBac 数据库的筛选条件",
    )
    pubchem: PubChemFilterConfig = Field(
        default_factory=PubChemFilterConfig,
        description="PubChem 数据库的筛选条件",
    )
    swiss: SwissFilterConfig = Field(
        default_factory=SwissFilterConfig,
        description="Swiss 数据库的筛选条件",
    )


# class AllDataConfig(BaseModel):
#     data_categories: List[str] = Field(..., description="需要下载的全量数据类别列表")
#     save_directory: str = Field(..., description="保存全量数据的目录路径")


# class PubChemURLConfig(BaseModel):
#     compound_id: str = Field(..., description="PubChem 查询化合物 ID 的 URL 模板")


class URLConfig(BaseModel):
    tcmsp: str = Field(..., description="TCMSP 的查询 URL")
    # pubchem: PubChemURLConfig


# class RequestSettingsConfig(BaseModel):
#     timeout: int = Field(10, description="请求超时时间（秒）")
#     delay_between_requests: int = Field(1, description="每次请求之间的延迟（秒）")


class Config(BaseModel):
    search: SearchConfig
    save_dir: SaveDirConfig
    filter: FilterConfig = Field(
        default_factory=FilterConfig, description="数据筛选条件"
    )
    # all_data: AllDataConfig
    url: URLConfig
    # request_settings: RequestSettingsConfig = Field(
    #     default_factory=RequestSettingsConfig, description="请求设置"
    # )
