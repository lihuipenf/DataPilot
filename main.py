"""不调用模型的数据分析示例：读取、汇总、排名并生成图表。"""
from datapilot.config import ROOT
from datapilot.data import load_sales
from datapilot.tools import ToolRegistry

if __name__ == "__main__":
    tools = ToolRegistry(load_sales(), ROOT / "outputs" / "example")
    print("数据概况：", tools.get_dataset_summary())
    print("商品排名：", tools.get_product_ranking())
    result = tools.create_sales_chart("product")
    print("图表已保存到：", tools.output_dir / result["artifact"]["id"])
