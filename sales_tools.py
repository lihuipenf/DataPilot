"""兼容最初的函数用法，业务计算已统一到 datapilot.tools。"""
from datapilot.config import ROOT
from datapilot.data import load_sales
from datapilot.tools import ToolRegistry


def _tools(sales_df):
    return ToolRegistry(load_sales(sales_df), ROOT / "outputs" / "legacy")


# 保留原先接收 DataFrame 的接口，便于对照学习。
def get_product_sales(sales_df):
    return _tools(sales_df).product_sales()


def get_top_product(sales_df):
    return _tools(sales_df).get_top_product()


def get_total_sales(sales_df):
    return _tools(sales_df).get_total_sales()


def get_sales_for_product(sales_df, product_name):
    return _tools(sales_df).get_sales_for_product(product_name)
