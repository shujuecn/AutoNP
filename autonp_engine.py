import os

import pandas as pd
import yaml

from utils.config_models import Config
from utils.data_crawl import HerbAC, Tcmsp

pd.set_option("display.max_columns", None)


class AutoNP:
    def __init__(self, config_path):
        self.config = self.load_config(config_path)
        self.initialize_modules()

    def load_config(self, config_path):
        # 加载配置文件
        with open(config_path, "r", encoding="utf-8") as file:
            config_data = yaml.safe_load(file)

        return Config(**config_data)

    def initialize_modules(self):
        # 初始化各个模块
        self.tcmsp = Tcmsp(self.config)
        self.herbac = HerbAC(self.config)

        for path in [self.config.save_dir.uniprot, self.config.save_dir.autonp]:
            os.makedirs(path, exist_ok=True)

    def match_gene(self):
        # Step 1: Define file paths
        tcmsp_target_file = os.path.join(
            self.tcmsp.save_directory, self.tcmsp.match_file_name
        )
        herbac_target_file = os.path.join(
            self.herbac.save_directory, self.herbac.predict_file_name
        )
        uniprot_full_gene_file = os.path.join(
            self.config.save_dir.uniprot, "uniprot_20426.csv"
        )

        self.tcmsp_herbac_target_file = os.path.join(
            self.config.save_dir.autonp, "tcmsp_herbac_target.csv"
        )
        self.target_gene_file = os.path.join(
            self.config.save_dir.autonp, "target_gene.csv"
        )

        # Step 2: Read CSV files into DataFrames
        tcmsp_target = pd.read_csv(tcmsp_target_file)
        herbac_target = pd.read_csv(herbac_target_file)
        uniprot_full_gene = pd.read_csv(uniprot_full_gene_file)

        # 选择关键列
        tcmsp_selected = tcmsp_target[["Herb", "MOL_ID", "Target_Name"]]
        herbac_selected = herbac_target[["Herb", "Ingredient_id", "Target"]]

        # 找出重叠的 Target_Name
        num_overlaps = (
            tcmsp_selected["Target_Name"].isin(herbac_selected["Target"]).sum()
        )
        print(f"有 {num_overlaps} 个 Target_Name 在两个数据框中重叠。")

        # 选择并重命名列
        tcmsp_selected = tcmsp_target[["Herb", "MOL_ID", "Target_Name"]].rename(
            columns={"MOL_ID": "Compound_ID"}
        )
        herbac_selected = herbac_target[["Herb", "Ingredient_id", "Target"]].rename(
            columns={"Ingredient_id": "Compound_ID", "Target": "Target_Name"}
        )

        # 按行拼接
        tcmsp_herbac_target = pd.concat(
            [tcmsp_selected, herbac_selected], ignore_index=True
        )

        # 清洗 Protein_names 列
        uniprot_full_gene["Protein_names"] = (
            uniprot_full_gene["Protein names"]
            .str.split(" \(")
            .str[0]
            .str.split(", ")
            .str[0]
        )

        # 左连接获取基因信息
        target_gene = (
            pd.merge(
                tcmsp_herbac_target,
                uniprot_full_gene,
                left_on="Target_Name",
                right_on="Protein_names",
                how="left",
            )
            .rename(columns={"Gene Names (primary)": "Gene_Symbol"})
            .loc[:, ["Herb", "Compound_ID", "Target_Name", "Gene_Symbol"]]
            .sort_values(by=["Herb", "Compound_ID"])
        )

        # 保存结果
        tcmsp_herbac_target.to_csv(self.tcmsp_herbac_target_file, index=False)
        target_gene.to_csv(self.target_gene_file, index=False)
        print(f"结果已保存到 {self.target_gene_file}")


if __name__ == "__main__":
    autonp = AutoNP("config.yaml")

    # 1. 从TCMSP数据库下载成分、靶点信息
    autonp.tcmsp.download_herbs_data()
    print(autonp.tcmsp.download_status)

    # 2. 匹配
    autonp.tcmsp.match_targets()
    print(autonp.tcmsp.ingredient_target_match)

    # 3. 设置需要从HerbAC补充的药物
    autonp.herbac.herb_names = autonp.tcmsp.failure_herbs

    # 4. 从HerbAC中下载成分信息
    autonp.herbac.download_herbs_data()
    print(autonp.herbac.download_status)

    # 5. 通过Pubchem、Swiss预测靶点信息
    autonp.herbac.predict_targets()

    # 6. 根据靶点（蛋白）匹配Uniprot基因
    autonp.match_gene()
