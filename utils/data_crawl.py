import json
import os
import random
import re
import time
import warnings
from typing import Any, Dict, List, Optional, Union

import lxml.html
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pandas import DataFrame
from tqdm import tqdm

from .config_models import Config

warnings.simplefilter(action="ignore", category=pd.errors.ParserWarning)


class Tcmsp:
    def __init__(self, config: Config):
        self.base_url: str = config.url.tcmsp
        self.headers: Dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; NCE-AL10 Build/HUAWEINCE-AL10; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/55.0.2883.91 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        self.herb_names: List[str] = config.search.herbs
        self.exact_match: bool = config.search.exact_match
        self.save_directory: str = config.save_dir.tcmsp

        self.download_status: pd.DataFrame
        self.success_herbs: list[str] = []
        self.failure_herbs: list[str] = []

        self.ob: float | None = config.filter.tcmsp.ob
        self.dl: float | None = config.filter.tcmsp.dl
        self.ingredient_target_match: pd.DataFrame
        self.match_file_name = "tcmsp_ingredient_target_match.csv"

    def fetch_html_content(self, url: str, params: dict = None) -> str:
        """
        发送GET请求并获取HTML内容

        Args:
            url (str): 请求的URL
            params (dict, optional): URL参数

        Returns:
            str: 返回的HTML内容
        """
        try:
            response = requests.get(url=url, headers=self.headers, params=params)
            response.raise_for_status()
            html_content = response.content.decode("utf-8")
            return html_content
        except requests.exceptions.RequestException:
            return ""

    def fetch_token(self) -> str:
        """
        获取页面中的token值

        Returns:
            str: token值
        """
        html_content = self.fetch_html_content(self.base_url)
        if html_content:
            root = lxml.html.fromstring(html_content)
            token_list = root.xpath(
                '//form[@id="SearchForm"]//input[@name="token"]/@value'
            )
            if token_list:
                token = token_list[0]
                return token
            else:
                return ""
        else:
            return ""


    @staticmethod
    def is_chinese_char(char: str) -> bool:
        """Determine if a character is Chinese."""
        return "\u4e00" <= char <= "\u9fff"

    def exact_match_filter(
        self, herb_name: str, herb_three_names: List[dict]
    ) -> Optional[List[dict]]:
        """Filter the herb_three_names based on exact match with herb_name."""
        if not herb_three_names:
            return None

        first_char = herb_name[0]
        if self.is_chinese_char(first_char):
            # Compare herb_name with herb_cn_name
            matched_items = [
                item for item in herb_three_names if item["herb_cn_name"] == herb_name
            ]
        else:
            herb_name_lower = herb_name.lower()
            # Compare herb_name with herb_en_name and herb_pinyin, after converting to lower case
            matched_items = [
                item
                for item in herb_three_names
                if item["herb_en_name"].lower() == herb_name_lower
                or item["herb_pinyin"].lower() == herb_name_lower
            ]
        return matched_items if matched_items else None

    def fetch_herb_info(
        self, herb_name: str, token: str, exact_match: bool = False
    ) -> Optional[List[dict]]:
        params = {"qs": "herb_all_name", "q": herb_name, "token": token}
        html_content = self.fetch_html_content(self.base_url, params=params)

        if html_content:
            soup = BeautifulSoup(html_content, "html.parser")
            scripts = soup.find_all("script")
            for script in scripts:
                if "data:" in script.text:
                    herb_three_names = re.findall(r"data:\s(.*),", script.text)
                    if herb_three_names and herb_three_names[0] != "[]":
                        herb_three_names = json.loads(herb_three_names[0])
                        if exact_match:
                            herb_three_names = self.exact_match_filter(
                                herb_name, herb_three_names
                            )
                        return herb_three_names
            return None
        else:
            return None

    @staticmethod
    def parse_json_from_html(html_content: str, pattern_id: str) -> List[dict]:
        """
        从HTML内容中提取指定的JSON数据

        Args:
            html_content (str): HTML内容
            pattern_id (str): 正则表达式的模式，用于匹配数据

        Returns:
            List[dict]: 提取的JSON数据
        """
        soup = BeautifulSoup(html_content, "html.parser")
        scripts = soup.find_all("script")

        for script in scripts:
            if pattern_id in script.text:
                pattern = rf"\$\(\"\#{pattern_id}\".*\n.*\n.*data\:\s(\[.*\])"
                match = re.compile(pattern).search(script.text)
                if match:
                    json_data_str = match.group(1)
                    data = json.loads(json_data_str)
                    return data
        return []

    @staticmethod
    def save_data_to_csv(
        data: List[dict],
        directory_path: str,
        file_name: str,
        index_column: Union[bool, str] = False,
    ) -> bool:
        """
        将数据保存为CSV文件

        Args:
            data (List[dict]): 数据列表
            directory_path (str): 文件保存目录
            file_name (str): 文件名
            index_column (Union[bool, str], optional): 索引列名或False。默认值为False。

        Returns:
            bool: 是否保存成功
        """
        if data:
            df = pd.DataFrame(data)
            full_path = os.path.join(directory_path, f"{file_name}.csv")

            if index_column:
                df.set_index(index_column, inplace=True)
                df.to_csv(full_path, index=True)
            else:
                df.to_csv(full_path, index=False)

            return True
        return False

    def download_single_herb(
        self,
        herb_name: str,
        herb_info: dict,
        token: str,
        save_directory: str,
    ) -> List[dict]:
        """
        下载指定药材的相关数据

        Args:
            herb_name (str): 用户在config指定的药名，用来保存
            herb_info (dict): 药材信息字典
            token (str): token值
            save_directory (str): 数据保存目录

        Returns:
            List[dict]: 包含下载状态和数据行数的信息
        """
        chinese_name = herb_info["herb_cn_name"]
        english_name = herb_info["herb_en_name"]
        pinyin_name = herb_info["herb_pinyin"]

        params = {"qr": english_name, "qsr": "herb_en_name", "token": token}
        html_content = self.fetch_html_content(self.base_url, params=params)

        download_info = []
        if html_content:
            # 导出成分数据
            ingredients_data = self.parse_json_from_html(
                html_content, pattern_id="grid"
            )
            ingredients_status = self.save_data_to_csv(
                ingredients_data,
                directory_path=save_directory,
                file_name=f"{herb_name}_ingredients",
                index_column="MOL_ID",
            )
            download_info.append(
                {
                    "中文名": chinese_name,
                    "英文名": english_name,
                    "拼音名": pinyin_name,
                    "文件类型": "ingredients",
                    "下载状态": "成功" if ingredients_status else "失败",
                    "数据行数": len(ingredients_data) if ingredients_data else 0,
                }
            )

            # 导出靶点数据
            targets_data = self.parse_json_from_html(html_content, pattern_id="grid2")
            targets_status = self.save_data_to_csv(
                targets_data,
                directory_path=save_directory,
                file_name=f"{herb_name}_targets",
                index_column="MOL_ID",
            )
            download_info.append(
                {
                    "中文名": chinese_name,
                    "英文名": english_name,
                    "拼音名": pinyin_name,
                    "文件类型": "targets",
                    "下载状态": "成功" if targets_status else "失败",
                    "数据行数": len(targets_data) if targets_data else 0,
                }
            )

            # 导出疾病数据
            diseases_data = self.parse_json_from_html(html_content, pattern_id="grid3")
            diseases_status = self.save_data_to_csv(
                diseases_data,
                directory_path=save_directory,
                file_name=f"{herb_name}_diseases",
                index_column=False,
            )
            download_info.append(
                {
                    "中文名": chinese_name,
                    "英文名": english_name,
                    "拼音名": pinyin_name,
                    "文件类型": "diseases",
                    "下载状态": "成功" if diseases_status else "失败",
                    "数据行数": len(diseases_data) if diseases_data else 0,
                }
            )
        else:
            # 如果下载失败，记录失败信息
            for file_type in ["ingredients", "targets", "diseases"]:
                download_info.append(
                    {
                        "中文名": chinese_name,
                        "英文名": english_name,
                        "拼音名": pinyin_name,
                        "文件类型": file_type,
                        "下载状态": "失败",
                        "数据行数": 0,
                    }
                )
        return download_info

    def download_herbs_data(self) -> pd.DataFrame:
        """
        根据药材名称列表查询并保存数据

        Args:
            herb_names (List[str]): 药材名称列表
            save_directory (str): 数据保存目录

        Returns:
            pd.DataFrame: 包含下载信息的数据框
        """
        os.makedirs(self.save_directory, exist_ok=True)

        token = self.fetch_token()
        if not token:
            print("无法获取token，程序终止。")
            return pd.DataFrame()

        # 首先收集所有的药物信息
        all_download_info = []
        herb_info_list_all = []

        with tqdm(total=len(self.herb_names), desc="Collecting herb info") as pbar:
            for herb_name in self.herb_names:
                herb_name = herb_name.strip()
                if not herb_name:
                    pbar.update(1)
                    continue

                # 获取药材信息
                herb_info_list = self.fetch_herb_info(
                    herb_name, token, exact_match=self.exact_match
                )
                if herb_info_list:
                    herb_info_list_all.extend(herb_info_list)
                    pbar.set_postfix_str(f"{herb_name} 信息收集成功")

                    self.success_herbs.append(herb_name)

                else:
                    # 如果未找到，添加占位符
                    herb_info_list_all.append(
                        {
                            "herb_cn_name": herb_name,
                            "herb_en_name": "",
                            "herb_pinyin": "",
                            "downloadable": False,
                        }
                    )
                    pbar.set_postfix_str(f"{herb_name} 信息收集失败")

                    self.failure_herbs.append(herb_name)

                pbar.update(1)
            pbar.set_postfix_str("")

        # 使用 tqdm 进度条，更新每个药物的下载状态
        with tqdm(total=len(herb_info_list_all), desc="Processing herbs") as pbar:
            for index, herb_info in enumerate(herb_info_list_all):
                chinese_name = herb_info.get("herb_cn_name", "")
                if not herb_info.get("downloadable", True):
                    pbar.set_description(f"{chinese_name}")
                    pbar.set_postfix_str("下载失败")
                    # 添加失败信息到 all_download_info
                    for file_type in ["ingredients", "targets", "diseases"]:
                        all_download_info.append(
                            {
                                "中文名": chinese_name,
                                "英文名": herb_info.get("herb_en_name", ""),
                                "拼音名": herb_info.get("pinyin_name", ""),
                                "文件类型": file_type,
                                "下载状态": "失败",
                                "数据行数": 0,
                            }
                        )
                    pbar.update(1)
                    continue

                download_info = self.download_single_herb(
                    self.herb_names[index], herb_info, token, self.save_directory
                )
                all_download_info.extend(download_info)

                # 检查下载状态
                statuses = [info["下载状态"] for info in download_info]
                if all(status == "成功" for status in statuses):
                    pbar.set_description(f"{chinese_name}")
                    pbar.set_postfix_str("下载完成")
                else:
                    pbar.set_description(f"{chinese_name}")
                    pbar.set_postfix_str("下载失败")

                pbar.update(1)
            pbar.set_postfix_str("")

        self.download_status = pd.DataFrame(all_download_info)



    # Function to read and process ingredients data for a single herb
    def __read_ingredients_files(self, herb_name, directory):
        filepath = os.path.join(directory, f"{herb_name}_ingredients.csv")
        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            df["Herb"] = herb_name
            # Ensure 'ob' and 'dl' are numeric
            df["ob"] = pd.to_numeric(df["ob"], errors="coerce")
            df["dl"] = pd.to_numeric(df["dl"], errors="coerce")

            # Filter based on 'ob' and 'dl' thresholds
            # df_filtered = df[(df["ob"] > self.ob) & (df["dl"] > self.dl)]
            # df_filtered = df

            if self.ob is not None:
                df = df[df["ob"] > self.ob]
            if self.dl is not None:
                df = df[df["dl"] > self.dl]
            return df
        else:
            print(f"Ingredients file not found for {herb_name}")
            return pd.DataFrame()

    # Function to read targets data for a single herb
    @staticmethod
    def __read_targets_files(herb_name, directory):
        filepath = os.path.join(directory, f"{herb_name}_targets.csv")
        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            df["Herb"] = herb_name
            return df
        else:
            print(f"Targets file not found for {herb_name}")
            return pd.DataFrame()

    def match_targets(self):
        # Read and process ingredients data for all herbs

        columns = ["Herb", "MOL_ID", "Molecule_Name", "Target_Name", "OB", "DL"]
        merged_df = pd.DataFrame(columns=columns)

        ingredients_list = [
            self.__read_ingredients_files(herb, self.save_directory)
            for herb in self.success_herbs
        ]

        if ingredients_list:
            tcmsp_ingredients = pd.concat(ingredients_list, ignore_index=True)
            tcmsp_ingredients = tcmsp_ingredients.drop_duplicates()

            # Read targets data for all herbs
            targets_list = [
                self.__read_targets_files(herb, self.save_directory)
                for herb in self.success_herbs
            ]
            tcmsp_targets = pd.concat(targets_list, ignore_index=True)

            # Merge ingredients and targets on 'MOL_ID'
            merged_df = (
                pd.merge(
                    tcmsp_ingredients,
                    tcmsp_targets,
                    on=["MOL_ID", "Herb"],
                    how="left",
                    suffixes=("_ingredient", "_target"),
                )
                .dropna(subset=["target_name"])
                .drop_duplicates(subset=["target_name"])
                .rename(
                    columns={
                        "molecule_name_ingredient": "Molecule_Name",
                        "target_name": "Target_Name",
                        "ob": "OB",
                        "dl": "DL",
                    }
                )
                .loc[:, columns]
            )

            # Save the final DataFrame to an Excel file
            output_filepath = os.path.join(self.save_directory, self.match_file_name)
            merged_df.to_csv(output_filepath, index=False)

        self.ingredient_target_match = merged_df

    '''
    def __download_all_data(
        self, data_categories: List[str], save_directory: str
    ) -> None:
        """
        下载指定类别的所有数据

        Args:
            data_categories (List[str]): 数据类别列表，例如 ["herbs", "ingredients", "targets", "diseases"]
            save_directory (str): 数据保存目录
        """
        os.makedirs(save_directory, exist_ok=True)

        self.base_url = self.base_url.replace("tcmspsearch.php", "browse.php")
        for category in data_categories:
            params = {"qc": category}
            html_content = self.fetch_html_content(self.base_url, params=params)
            if html_content:
                data = self.parse_json_from_html(html_content, pattern_id="grid")
                self.save_data_to_csv(
                    data,
                    directory_path=save_directory,
                    file_name=f"{category}_data",
                    index_column=False,
                )
            else:
                print(f"获取 {category} 的数据失败！")
    '''


class HerbAC:
    def __init__(self, config: Config):
        self.save_directory = config.save_dir.herbac

        self.herb_names: list[str] = config.search.herbs

        self.download_status: pd.DataFrame = pd.DataFrame()
        self.success_herbs: list[str] = []
        self.failure_herbs: list[str] = []

        self.weight: float | None = config.filter.herbac.weight
        self.xlogp: float | None = config.filter.pubchem.xlogp
        self.hbonddonor: float | None = config.filter.pubchem.hbonddonor
        self.hbondacc: float | None = config.filter.pubchem.hbondacc

        self.ingredient_target_predict: pd.DataFrame
        self.predict_file_name = "herbac_ingredient_target_predict.csv"

    # 网络请求工具函数
    @staticmethod
    def __make_request(
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """
        发送HTTP请求并返回响应对象。

        Args:
            url (str): 请求的URL。
            method (str): HTTP方法，"GET"或"POST"。默认为"GET"。
            headers (Optional[Dict[str, str]]): 请求头字典。
            params (Optional[Dict[str, Any]]): 查询参数字典。
            data (Optional[Union[Dict[str, Any], str]]): 表单数据。
            json_data (Optional[Dict[str, Any]]): JSON格式的数据。

        Returns:
            requests.Response: HTTP响应对象。
        """
        default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/117.0.0.0 Safari/537.36 Edg/117.0.2045.40"
            )
        }
        if headers:
            default_headers.update(headers)

        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=default_headers, params=params)
            elif method.upper() == "POST":
                response = requests.post(
                    url,
                    headers=default_headers,
                    params=params,
                    data=data,
                    json=json_data,
                )
            else:
                raise ValueError("Unsupported HTTP method: {}".format(method))

            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"HTTP请求失败: {e}")
            raise

    '''
    # 辅助函数
    def __get_herb_id(self, herb_name: str) -> Optional[str]:
        """
        获取药材的ID。

        Args:
            herb_name (str): 药材名称。

        Returns:
            Optional[str]: 药材ID，如果未找到则返回None。
        """
        url = "http://herb.ac.cn/chedi/api/"
        json_data = {
            "label": "Herb",
            "keyword": herb_name,
            "func_name": "search_api",
        }

        response = self.__make_request(url, method="POST", json_data=json_data)
        response_data = response.json()

        herb_id = None
        for item in response_data.get("res_data", [])[1:]:
            herb_info = {
                "Herb_id": item[0].get("title") if item[0] != "NA" else "NA",
                "Herb_pinyin_name": item[1],
                "Herb_Chinese_name": item[2],
                "Herb_English_name": item[3],
                "Herb_Latin_name": item[4].get("title") if item[4] != "NA" else "NA",
            }

            herb_names = [
                herb_info["Herb_id"],
                herb_info["Herb_pinyin_name"],
                herb_info["Herb_Chinese_name"],
                herb_info["Herb_English_name"],
                herb_info["Herb_Latin_name"],
            ]

            if herb_name in herb_names or herb_name.upper() in herb_names:
                herb_id = herb_info["Herb_id"]
                break

        if herb_id:
            print(f'找到 "{herb_name}" 的ID: {herb_id}')
        else:
            print(f'"{herb_name}" 的ID未找到！')

        return herb_id
    '''

    # TODO: 待抽象化
    @staticmethod
    def is_chinese_char(char: str) -> bool:
        """Determine if a character is Chinese."""
        return "\u4e00" <= char <= "\u9fff"

    '''
    # TODO: 待调整，目前和Tcmsp中相同
    def exact_match_filter(
        self, herb_name: str, herb_three_names: List[dict]
    ) -> Optional[List[dict]]:
        """Filter the herb_three_names based on exact match with herb_name."""
        if not herb_three_names:
            return None

        first_char = herb_name[0]
        if self.is_chinese_char(first_char):
            # Compare herb_name with herb_cn_name
            matched_items = [
                item for item in herb_three_names if item["herb_cn_name"] == herb_name
            ]
        else:
            """
            herb_name_lower = herb_name.lower()
            # Compare herb_name with herb_en_name and herb_pinyin, after converting to lower case
            matched_items = [
                item
                for item in herb_three_names
                if item["herb_en_name"].lower() == herb_name_lower
                or item["herb_pinyin"].lower() == herb_name_lower
            ]
            """
            raise ValueError("药名必须为中文")

        return matched_items if matched_items else None
    '''

    # 辅助函数
    def __get_herb_info(self, herb_name: str) -> Optional[str]:
        """
        获取药材的ID。

        Args:
            herb_name (str): 药材名称。

        Returns:
            Optional[str]: 药材ID，如果未找到则返回None。
        """
        url = "http://herb.ac.cn/chedi/api/"
        json_data = {
            "label": "Herb",
            "keyword": herb_name,
            "func_name": "search_api",
        }

        response = self.__make_request(url, method="POST", json_data=json_data)
        response_data = response.json()

        # herb_id = None
        for item in response_data.get("res_data", [])[1:]:
            herb_info = {
                "herb_id": item[0].get("title") if item[0] != "NA" else "NA",
                "herb_pinyin": item[1],
                "herb_cn_name": item[2],
                "herb_en_name": item[3],
                "herb_latin_name": item[4].get("title") if item[4] != "NA" else "NA",
            }

            herb_names = [
                herb_info["herb_id"],
                herb_info["herb_pinyin"],
                herb_info["herb_cn_name"],
                herb_info["herb_en_name"],
                herb_info["herb_latin_name"],
            ]

            if herb_name in herb_names or herb_name.upper() in herb_names:
                # herb_id = herb_info["Herb_id"]
                # break

                # if herb_id:
                #     print(f'找到 "{herb_name}" 的ID: {herb_id}')
                # else:
                #     print(f'"{herb_name}" 的ID未找到！')

                return herb_info

    def __get_herb_ingredients(self, herb_id: str) -> Optional[List[List[str]]]:
        """
        获取指定药材ID的成分信息。

        Args:
            herb_id (str): 药材ID。

        Returns:
            Optional[List[List[str]]]: 成分信息列表，如果未找到则返回None。
        """
        url = "http://herb.ac.cn/chedi/api/"
        json_data = {
            "v": herb_id,
            "label": "Herb",
            "key_id": herb_id,
            "func_name": "detail_api",
        }

        response = self.__make_request(url, method="POST", json_data=json_data)
        response_data = response.json()

        ingredients = response_data.get("herb_ingredient")
        if ingredients:
            # 提取链接文本
            for item in ingredients[1:]:
                item[0] = item[0].get("title", "NA")
            return ingredients
        else:
            print(f'未找到ID为 "{herb_id}" 的成分信息！')
            return None

    @staticmethod
    def __save_to_excel(
        data: List[List[str]], columns: List[str], file_path: str
    ) -> bool:
        """
        将数据保存为Excel文件并返回DataFrame。

        Args:
            data (List[List[str]]): 数据列表。
            columns (List[str]): 列名列表。
            file_path (str): 保存路径。

        Returns:
            pd.DataFrame: 保存的数据框。
        """
        #! 修改了返回值
        if data:
            df = pd.DataFrame(data, columns=columns)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            df.to_excel(file_path, index=False)
            # print(f'数据已保存到 "{file_path}"')
            return True
        return False

    @staticmethod
    def __save_to_csv(
        data: List[List[str]], columns: List[str], file_path: str
    ) -> bool:
        """
        将数据保存为Excel文件并返回保存状态。

        Args:
            data (List[List[str]]): 数据列表。
            columns (List[str]): 列名列表。
            file_path (str): 保存路径。

        Returns:
            pd.DataFrame: 保存的数据框。
        """
        #! 修改了返回值
        if data:
            df = pd.DataFrame(data, columns=columns)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            df.to_csv(file_path, index=False)
            # print(f'数据已保存到 "{file_path}"')
            return True
        return False

    def __download_file(self, url: str, file_path: str) -> None:
        """
        从指定URL下载文件并保存。

        Args:
            url (str): 文件URL。
            file_path (str): 保存路径。
        """
        response = self.__make_request(url)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(response.content)
        print(f'文件已下载到 "{file_path}"')

    @staticmethod
    def __read_csv_file(
        file_path: str, sep: str = ",", index_col: Union[bool, int, str] = False
    ) -> pd.DataFrame:
        """
        读取CSV文件为DataFrame。

        Args:
            file_path (str): 文件路径。
            sep (str): 分隔符。
            index_col (Union[bool, int, str]): 索引列。

        Returns:
            pd.DataFrame: 数据框。
        """
        try:
            df = pd.read_csv(file_path, sep=sep, index_col=index_col)
            print(f'成功加载数据文件 "{file_path}"')
            return df
        except FileNotFoundError:
            print(f'文件 "{file_path}" 不存在！')
            raise
        except pd.errors.EmptyDataError:
            print(f'文件 "{file_path}" 内容为空！')
            raise

    # 用户可调用的功能函数
    def load_herb_ingredient(self, herb_info: str) -> dict:
        """
        加载指定药材的成分信息，并保存为Excel文件。

        Args:

        Returns:
            Optional[pd.DataFrame]: 药材成分信息的数据框，如果未找到则返回None。
        """
        # herb_id = self.__get_herb_id(herb_name)

        herb_id = herb_info["herb_id"]
        herb_cn_name = herb_info["herb_cn_name"]
        herb_en_name = herb_info["herb_en_name"]
        herb_pinyin = herb_info["herb_pinyin"]

        # if not herb_id:
        #     return None

        ingredients = self.__get_herb_ingredients(herb_id)
        if not ingredients:
            return None

        # TODO: 文件名写死在这里不妥
        file_path = os.path.join(self.save_directory, f"{herb_cn_name}_ingredients.csv")
        ingredients_status = self.__save_to_csv(
            ingredients[1:], ingredients[0], file_path
        )

        download_info = {
            "中文名": herb_cn_name,
            "英文名": herb_en_name,
            "拼音名": herb_pinyin,
            "文件类型": "ingredients",
            "下载状态": "成功" if ingredients_status else "失败",
            "数据行数": len(ingredients) if ingredients else 0,
        }

        return download_info

    def load_all_ingredients(self) -> pd.DataFrame:
        """
        加载所有药材的成分信息。

        Returns:
            pd.DataFrame: 所有药材成分信息的数据框。
        """
        file_name = "HERB_ingredient_info.txt"
        file_path = os.path.join(self.save_directory, file_name)
        url = "http://herb.ac.cn/download/file/?file_path=/data/Web_server/HERB_web/static/download_data/HERB_ingredient_info.txt"

        # TODO: 校验本地文件的MD5值，防止篡改
        if not os.path.exists(file_path):
            print(f'文件 "{file_name}" 不存在，开始下载...')
            self.__download_file(url, file_path)

        df = self.__read_csv_file(file_path, sep="\t")
        return df

    # TODO
    def download_herbs_data(self):
        all_download_info = []
        herb_info_list_all = []

        with tqdm(total=len(self.herb_names), desc="Collecting herb info") as pbar:
            for herb_name in self.herb_names:
                herb_name = herb_name.strip()

                #! 跳过了非中文药名，待优化
                if not herb_name or not self.is_chinese_char(herb_name[0]):
                    pbar.update(1)
                    continue

                # 获取药材信息
                herb_info = self.__get_herb_info(herb_name)

                # TODO: 抽象化特殊处理
                # * json: list.extend
                # * dict: list.append
                if herb_info:
                    herb_info_list_all.append(herb_info)
                    pbar.set_postfix_str(f"{herb_name} 信息收集成功")
                    self.success_herbs.append(herb_name)

                else:
                    # 如果未找到，添加占位符
                    herb_info_list_all.append(
                        {
                            "herb_id": "",
                            "herb_pinyin": "",
                            "herb_cn_name": herb_name,
                            "herb_en_name": "",
                            "herb_latin_name": "",
                            "downloadable": False,
                        }
                    )
                    pbar.set_postfix_str(f"{herb_name} 信息收集失败")
                    self.failure_herbs.append(herb_name)

                pbar.update(1)
            pbar.set_postfix_str("")

        # 使用 tqdm 进度条，更新每个药物的下载状态
        with tqdm(total=len(herb_info_list_all), desc="Processing herbs") as pbar:
            for herb_info in herb_info_list_all:
                chinese_name = herb_info.get("herb_cn_name", "")
                if not herb_info.get("downloadable", True):
                    pbar.set_description(f"{chinese_name}")
                    pbar.set_postfix_str("下载失败")
                    # 添加失败信息到 all_download_info
                    for file_type in ["ingredients", "targets", "diseases"]:
                        all_download_info.append(
                            {
                                "中文名": chinese_name,
                                "英文名": herb_info.get("herb_en_name", ""),
                                "拼音名": herb_info.get("pinyin_name", ""),
                                "文件类型": file_type,
                                "下载状态": "失败",
                                "数据行数": 0,
                            }
                        )
                    pbar.update(1)
                    continue

                # TODO: 抽象化特殊处理
                download_info = self.load_herb_ingredient(herb_info)
                all_download_info.append(download_info)

                if download_info["下载状态"] == "成功":
                    pbar.set_description(f"{chinese_name}")
                    pbar.set_postfix_str("下载完成")
                else:
                    pbar.set_description(f"{chinese_name}")
                    pbar.set_postfix_str("下载失败")

                pbar.update(1)
            pbar.set_postfix_str("")

        self.download_status = pd.DataFrame(all_download_info)

        # status_groups = self.download_status.groupby("下载状态")["中文名"]
        # self.success_herbs = (
        #     status_groups.get_group("成功").drop_duplicates().tolist()
        #     if "成功" in status_groups.groups
        #     else []
        # )
        # self.failure_herbs = (
        #     status_groups.get_group("失败").drop_duplicates().tolist()
        #     if "失败" in status_groups.groups
        #     else []
        # )

    # Function to read and process ingredients data for a single herb
    def __read_ingredients_files(self, herb_name, directory):
        filepath = os.path.join(directory, f"{herb_name}_ingredients.csv")

        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            df["Herb"] = herb_name
            return df
        else:
            print(f"Ingredients file not found for {herb_name}")
            return pd.DataFrame()

    def predict_targets(self):
        # 合并药物成分信息
        ingredients_list = [
            self.__read_ingredients_files(herb, self.save_directory)
            for herb in self.success_herbs
        ]
        herbac_ingredients = pd.concat(
            ingredients_list, ignore_index=True
        ).drop_duplicates()

        # 下载全站所有药物详细信息
        herbac_all_ingredients = self.load_all_ingredients()

        merged_df = (
            pd.merge(
                herbac_ingredients,
                herbac_all_ingredients,
                left_on=["Ingredient id", "Ingredient name"],
                right_on=["Ingredient_id", "Ingredient_name"],
                how="left",
            )
            .dropna(subset=["PubChem_id"])
            .astype({"PubChem_id": "int"})
            .assign(
                Ingredient_weight_numeric=lambda df: pd.to_numeric(
                    df["Ingredient_weight"].str.extract(r"(\d+\.?\d*)", expand=False),
                    errors="coerce",
                )
            )
        )

        # Index(['Herb', 'Ingredient_id', 'Ingredient_name', 'Ingredient_formula', 'PubChem_id', 'isosmiles'])
        compounds_filtered = self.apply_filters(merged_df)

        smiles = "\r\n".join(compounds_filtered["isosmiles"].astype(str))

        # Index(['Molecule', 'Canonical SMILES', 'Formula'])
        swiss_adme = self.load_swissadme(smiles)

        # Index(['Target', 'Common name', 'Uniprot ID', 'ChEMBL ID', 'Target Class', 'Probability*', 'Known actives (3D/2D)', 'Canonical SMILES'])
        success_swiss_target, failure_swiss_target = (
            SwissPredict().process_smiles_dataframe(swiss_adme, "Canonical SMILES")
        )

        self.ingredient_target_predict = (
            pd.merge(
                compounds_filtered,
                swiss_adme[["Formula", "Canonical SMILES"]],
                left_on="Ingredient_formula",
                right_on="Formula",
                how="left",
            )
            .drop(columns=["Formula"])
            .merge(
                success_swiss_target[
                    [
                        "Target",
                        "Common name",
                        "Uniprot ID",
                        "Probability*",
                        "Canonical SMILES",
                    ]
                ],
                on="Canonical SMILES",
                how="left",
            )
            .drop(columns=["Canonical SMILES"])
        )

        self.ingredient_target_predict.to_csv(
            os.path.join(self.save_directory, self.predict_file_name), index=False
        )


    def apply_filters(self, df: pd.DataFrame):
        """
        判断筛选条件是否存在，并应用相应的筛选。
        """

        # 获取PubChem_id列表并查询化合物信息
        ids = " ".join(df["PubChem_id"].astype(str))
        compounds: DataFrame = self.load_pubchem_compounds(ids)

        # 根据提供的筛选条件进行筛选
        if self.weight is not None:
            df = df[df["Ingredient_weight_numeric"] <= self.weight]
        if self.xlogp is not None:
            compounds = compounds[compounds["xlogp"] <= self.xlogp]
        if self.hbonddonor is not None:
            compounds = compounds[compounds["hbonddonor"] <= self.hbonddonor]
        if self.hbondacc is not None:
            compounds = compounds[compounds["hbondacc"] <= self.hbondacc]

        compounds_filtered: DataFrame = pd.merge(
            left=df,
            right=compounds,
            left_on="PubChem_id",
            right_on="cid",
            how="inner",
        ).loc[
            :,
            [
                "Herb",
                "Ingredient_id",
                "Ingredient_name",
                "Ingredient_formula",
                "PubChem_id",
                "isosmiles",
            ],
        ]

        return compounds_filtered

    def load_pubchem_compounds(
        self, compound_ids: Union[str, List[str]]
    ) -> pd.DataFrame:
        """
        从PubChem加载化合物信息。
        http://pubchem.ncbi.nlm.nih.gov/pug_rest/PUG_REST.html

        Args:
            compound_ids (Union[str, List[str]]): 化合物ID列表，字符串或字符串列表。

        Returns:
            pd.DataFrame: 包含化合物信息的数据框。
        """
        if isinstance(compound_ids, list):
            compound_ids_str = " ".join(map(str, compound_ids))
        else:
            compound_ids_str = compound_ids

        # 获取缓存键
        cache_url = "https://pubchem.ncbi.nlm.nih.gov/list_gateway/list_gateway.cgi"
        cache_data = {
            "format": "json",
            "action": "post_to_cache",
            "id_type": "cid",
            "ids": compound_ids_str,
        }
        response = self.__make_request(cache_url, method="POST", data=cache_data)
        cache_key = response.json()["Response"]["cache_key"]

        # 获取化合物信息
        compounds_url = "https://pubchem.ncbi.nlm.nih.gov/sdq/sdqagent.cgi"
        query = {
            "select": "*",
            "collection": "compound",
            "where": {
                "ands": [
                    {
                        "input": {
                            "type": "netcachekey",
                            "idtype": "cid",
                            "key": cache_key,
                        }
                    }
                ]
            },
            "order": ["relevancescore,desc"],
            "start": 1,
            "limit": len(compound_ids_str.split()) + 1,
            "width": 1000000,
            "listids": 0,
        }
        params = {"infmt": "json", "outfmt": "json", "query": json.dumps(query)}
        response = self.__make_request(compounds_url, method="GET", params=params)
        compounds_data = response.json()["SDQOutputSet"][0]["rows"]
        df = pd.json_normalize(compounds_data)
        return df

    def load_swissadme(self, smiles_list: Union[str, List[str]]) -> pd.DataFrame:
        """
        从SwissADME加载化合物的ADME信息。

        Args:
            smiles_list (Union[str, List[str]]): SMILES字符串或字符串列表。

        Returns:
            pd.DataFrame: 包含ADME信息的数据框。
        """
        if isinstance(smiles_list, list):
            smiles_data = "\n".join(smiles_list)
        else:
            smiles_data = smiles_list

        print("SwissADME请求已发送，正在解析结果...")

        # 发送POST请求获取结果页面
        url = "http://www.swissadme.ch/index.php"
        data = {"smiles": smiles_data}
        response = self.__make_request(url, method="POST", data=data)

        # 提取结果文件的代码
        match = re.search(r"results/(\d+)/swissadme\.csv", response.text)
        if not match:
            print("未能找到结果文件，请检查输入的SMILES字符串。")
            return pd.DataFrame()

        code = match.group(1)
        result_url = f"http://www.swissadme.ch/results/{code}/swissadme.csv"
        file_path = os.path.join(self.save_directory, f"swissadme_{code}.csv")

        self.__download_file(result_url, file_path)
        df = self.__read_csv_file(file_path)

        # 定义列名称
        violation_columns = [
            "Lipinski #violations",
            "Ghose #violations",
            "Veber #violations",
            "Egan #violations",
            "Muegge #violations",
        ]

        # 筛选出五列中至少3列为0且`GI absorption`为"high"的行
        swiss_adme_filtered: DataFrame = df[
            (df[violation_columns].eq(0).sum(axis=1) >= 3)
            & (df["GI absorption"].str.lower() == "high")
        ].loc[:, ["Molecule", "Canonical SMILES", "Formula"]]

        return swiss_adme_filtered


class __SwissPredict:
    def __init__(self):
        self.POST_URL = "http://swisstargetprediction.ch/predict.php"
        self.GET_URL_TEMPLATE = "http://swisstargetprediction.ch/result.php?job={job_id}&organism=Homo_sapiens"
        self.REFERER_POST = "http://swisstargetprediction.ch/"
        self.REFERER_GET = "http://swisstargetprediction.ch/predict.php"

        self.prob: float | None = 0

    def send_post_request(self, session, url, data):
        headers = {"Referer": self.REFERER_POST}
        response = session.post(url, data=data, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            raise Exception(f"POST 请求失败，状态码：{response.status_code}")

    def extract_job_id(self, response_text):
        """
        从 POST 请求的响应文本中提取 job ID
        """
        soup = BeautifulSoup(response_text, "html.parser")
        script_tag = soup.find("script", text=lambda x: x and "result.php?job=" in x)
        if script_tag and script_tag.string:
            job_id = script_tag.string.split("job=")[1].split("&")[0]
            return job_id
        else:
            raise ValueError("未找到 job ID")

    def send_get_request(self, session, url):
        headers = {"Referer": self.REFERER_GET}
        response = session.get(url, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            raise Exception(f"GET 请求失败，状态码：{response.status_code}")

    def parse_html_table(self, html_content, table_id):
        """
        从 HTML 内容中提取指定表格的数据并转换为 Pandas DataFrame
        """
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table", {"id": table_id})

        if table is None:
            # 打印部分 HTML 内容用于调试
            # print("HTML 内容中未找到指定表格。以下为 HTML 内容的一部分：")
            # print(html_content[:500])  # 打印前 500 个字符
            raise ValueError(f"未找到 id 为 '{table_id}' 的表格。")

        # 提取表头
        headers = [header.get_text(strip=True) for header in table.find_all("th")]

        # 提取表格行
        rows = []
        for row in table.find("tbody").find_all("tr"):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            rows.append(cells)

        # 转换为 DataFrame
        return pd.DataFrame(rows, columns=headers)

    def filter_by_probability(self, df, column_name):
        """
        筛选指定列大于给定阈值的行
        """

        if self.prob is not None:
            df = df[df[column_name].astype(float) > self.prob]
        return df

    def process_smiles(self, smiles_code, session):
        post_data = {
            "organism": "Homo_sapiens",
            "smiles": smiles_code,
            "Example": "",
            "ioi": "1",
        }
        # 发送 POST 请求
        post_response_text = self.send_post_request(session, self.POST_URL, post_data)
        # 提取 job ID
        job_id = self.extract_job_id(post_response_text)
        # 发送 GET 请求
        get_url = self.GET_URL_TEMPLATE.format(job_id=job_id)
        get_response_text = self.send_get_request(session, get_url)
        # 解析 HTML 表格
        result_df = self.parse_html_table(get_response_text, "resultTable")
        # 筛选 DataFrame
        filtered_df = self.filter_by_probability(result_df, "Probability*")
        return filtered_df

    def process_smiles_dataframe(self, df, smiles_column_name):
        """
        处理包含 SMILES 字符串的数据框，返回两个数据框：
        - 成功处理的长表数据框 final_df
        - 处理失败的 SMILES 字符串及错误信息 failed_df

        参数：
        - df: 待处理的 Pandas DataFrame。
        - smiles_column_name: 包含 SMILES 字符串的列名。

        返回：
        - final_df: 处理好的长表数据框。
        - failed_df: 包含处理失败的 SMILES 字符串及错误信息的数据框。
        """
        # 创建一个会话
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Connection": "keep-alive",
            }
        )

        results = []
        failed = []

        print("开始预测靶点...")
        for smiles in tqdm(df[smiles_column_name]):
            try:
                df_result = self.process_smiles(smiles, session)
                df_result[smiles_column_name] = smiles  # 在结果中添加 SMILES 字符串
                results.append(df_result)
            except Exception as e:
                print(f"处理 SMILES {smiles} 时出错：{e}")
                failed.append({smiles_column_name: smiles, "Error": str(e)})
                continue
            time.sleep(1)  # 每次请求后等待 1 秒

        # 将所有结果合并为一个数据框
        if results:
            success_df = pd.concat(results, ignore_index=True)
        else:
            # success_df = pd.DataFrame()  # 如果没有结果，返回空的 DataFrame
            success_df = pd.DataFrame(
                columns=[
                    "Target",
                    "Common name",
                    "Uniprot ID",
                    "ChEMBL ID",
                    "Target Class",
                    "Probability*",
                    "Known actives (3D/2D)",
                    "Canonical SMILES",
                ]
            )

        if failed:
            failure_df = pd.DataFrame(failed)
        else:
            failure_df = pd.DataFrame(columns=[smiles_column_name, "Error"])

        return success_df, failure_df


class SwissPredict:
    def __init__(self):
        self.POST_URL = "http://swisstargetprediction.ch/predict.php"
        self.GET_URL_TEMPLATE = "http://swisstargetprediction.ch/result.php?job={job_id}&organism=Homo_sapiens"
        self.REFERER_POST = "http://swisstargetprediction.ch/"
        self.REFERER_GET = "http://swisstargetprediction.ch/predict.php"

        self.prob: float | None = 0

        # 您提供的 User-Agent 列表
        self.user_agents = [
            # Opera
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36 OPR/26.0.1656.60",
            "Opera/8.0 (Windows NT 5.1; U; en)",
            "Mozilla/5.0 (Windows NT 5.1; U; en; rv:1.8.1) Gecko/20061208 Firefox/2.0.0 Opera 9.50",
            "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; en) Opera 9.50",
            # Firefox
            "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) Gecko/20100101 Firefox/34.0",
            "Mozilla/5.0 (X11; U; Linux x86_64; zh-CN; rv:1.9.2.10) Gecko/20100922 Ubuntu/10.10 (maverick) Firefox/3.6.10",
            # Safari
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/534.57.2 (KHTML, like Gecko) Version/5.1.7 Safari/534.57.2",
            # Chrome
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.71 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11",
            "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/534.16 (KHTML, like Gecko) Chrome/10.0.648.133 Safari/534.16",
            # 360
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; rv:11.0) like Gecko",
        ]

        # 初始化代理 IP 列表为空
        self.proxies_list = []

    def fetch_proxies(self):
        """
        从指定的 API 获取最新的代理 IP 列表，并更新 self.proxies_list
        """
        api_url = (
            "https://api.proxyscrape.com/v4/free-proxy-list/get?"
            "request=display_proxies&country=us,cn,sg,br,de&protocol=http"
            "&proxy_format=protocolipport&format=text&timeout=2000"
        )
        try:
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                proxy_text = response.text.strip()
                # 分割获取到的代理 IP 列表
                proxies = proxy_text.split("\n")
                # 过滤掉空行
                self.proxies_list = [
                    proxy.strip() for proxy in proxies if proxy.strip()
                ]
                print(f"成功获取 {len(self.proxies_list)} 个代理 IP。")
            else:
                print(f"获取代理 IP 失败，状态码：{response.status_code}")
        except Exception as e:
            print(f"获取代理 IP 时发生异常：{e}")

    def send_post_request(self, session, url, data):
        headers = session.headers.copy()
        headers.update({"Referer": self.REFERER_POST})
        response = session.post(url, data=data, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            raise Exception(f"POST 请求失败，状态码：{response.status_code}")

    def extract_job_id(self, response_text):
        """
        从 POST 请求的响应文本中提取 job ID
        """
        soup = BeautifulSoup(response_text, "html.parser")
        script_tag = soup.find("script", text=lambda x: x and "result.php?job=" in x)
        if script_tag and script_tag.string:
            job_id = script_tag.string.split("job=")[1].split("&")[0]
            return job_id
        else:
            raise ValueError("未找到 job ID")

    def send_get_request(self, session, url):
        headers = session.headers.copy()
        headers.update({"Referer": self.REFERER_GET})
        response = session.get(url, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            raise Exception(f"GET 请求失败，状态码：{response.status_code}")

    def parse_html_table(self, html_content, table_id):
        """
        从 HTML 内容中提取指定表格的数据并转换为 Pandas DataFrame
        """
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table", {"id": table_id})

        if table is None:
            raise ValueError(f"未找到 id 为 '{table_id}' 的表格。")

        # 提取表头
        headers = [header.get_text(strip=True) for header in table.find_all("th")]

        # 提取表格行
        rows = []
        for row in table.find("tbody").find_all("tr"):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            rows.append(cells)

        # 转换为 DataFrame
        return pd.DataFrame(rows, columns=headers)

    def filter_by_probability(self, df, column_name):
        """
        筛选指定列大于给定阈值的行
        """
        if self.prob is not None:
            df = df[df[column_name].astype(float) > self.prob]
        return df

    def process_smiles(self, smiles_code, session):
        post_data = {
            "organism": "Homo_sapiens",
            "smiles": smiles_code,
            "Example": "",
            "ioi": "1",
        }
        # 发送 POST 请求
        post_response_text = self.send_post_request(session, self.POST_URL, post_data)
        # 提取 job ID
        job_id = self.extract_job_id(post_response_text)
        # 发送 GET 请求
        get_url = self.GET_URL_TEMPLATE.format(job_id=job_id)
        get_response_text = self.send_get_request(session, get_url)
        # 解析 HTML 表格
        result_df = self.parse_html_table(get_response_text, "resultTable")
        # 筛选 DataFrame
        filtered_df = self.filter_by_probability(result_df, "Probability*")
        return filtered_df

    def process_smiles_dataframe(self, df, smiles_column_name):
        """
        处理包含 SMILES 字符串的数据框，返回两个数据框：
        - 成功处理的长表数据框 final_df
        - 处理失败的 SMILES 字符串及错误信息 failed_df
        """
        # 首先获取最新的代理 IP 列表
        self.fetch_proxies()
        if not self.proxies_list:
            print("代理 IP 列表为空，无法继续执行。")
            return None, None

        results = []
        failed = []

        print("开始预测靶点...")
        for smiles in tqdm(df[smiles_column_name]):
            success = False
            attempts = 0
            max_retries = 2  # 最大重试次数
            while not success and attempts < max_retries:
                try:
                    attempts += 1
                    # 创建一个新的会话
                    session = requests.Session()

                    # 随机选择一个 User-Agent
                    user_agent = random.choice(self.user_agents)
                    session.headers.update(
                        {
                            "User-Agent": user_agent,
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Accept-Language": "zh-CN,zh;q=0.9",
                            "Connection": "keep-alive",
                        }
                    )

                    # 随机选择一个代理 IP
                    if self.proxies_list:
                        proxy = random.choice(self.proxies_list)
                        session.proxies.update({"http": proxy, "https": proxy})
                    else:
                        print("代理 IP 列表为空，无法设置代理。")
                        break

                    # 处理 SMILES
                    df_result = self.process_smiles(smiles, session)
                    df_result[smiles_column_name] = smiles  # 在结果中添加 SMILES 字符串
                    results.append(df_result)
                    success = True
                except Exception as e:
                    print(f"处理 SMILES {smiles} 时出错，尝试次数 {attempts}：{e}")
                    # 如果是代理 IP 导致的错误，可以考虑从代理列表中移除该代理
                    if proxy in self.proxies_list:
                        self.proxies_list.remove(proxy)
                    time.sleep(random.uniform(1, 5))
                    continue
            if not success:
                failed.append(
                    {
                        smiles_column_name: smiles,
                        "Error": f"Failed after {max_retries} attempts",
                    }
                )
            time.sleep(random.uniform(1, 5))

        # 将所有结果合并为一个数据框
        if results:
            success_df = pd.concat(results, ignore_index=True)
        else:
            success_df = pd.DataFrame(
                columns=[
                    "Target",
                    "Common name",
                    "Uniprot ID",
                    "ChEMBL ID",
                    "Target Class",
                    "Probability*",
                    "Known actives (3D/2D)",
                    "Canonical SMILES",
                    smiles_column_name,
                ]
            )

        if failed:
            failure_df = pd.DataFrame(failed)
        else:
            failure_df = pd.DataFrame(columns=[smiles_column_name, "Error"])

        return success_df, failure_df
