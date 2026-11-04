# 导入 Pandas 和新写的查询函数
import pandas as pd
from sales_tools import get_sales_for_product

# 读取销售表格，计算每笔记录的销售额
df = pd.read_csv("sales.csv")
df["sales_amount"] = df["quantity"] * df["unit_price"]

# 查询一个存在的商品，观察正常结果
result = get_sales_for_product(df, "Keyboard")
print("查询 Keyboard：", result)

# 查询一个不存在的商品，观察错误提示
result = get_sales_for_product(df, "Phone")
print("查询 Phone：", result)