# 帮助与维护入口 / Support

DataPilot由个人维护，面向固定销售CSV的本地单用户分析。这里说明如何获得帮助和参与；没有付费支持、固定响应时限、可用性SLA或接受每项建议的承诺。

## 选择入口

| 你需要什么 | 去哪里 | 建议提供 |
|---|---|---|
| 安装、PyCharm、Docker或模型配置 | 先看[启动教程](docs/getting-started.md)与[模型指南](docs/models.md) | 使用版本、环境、对应教程步骤 |
| 可复现的普通缺陷 | [缺陷表单](https://github.com/lihuipenf/DataPilot/issues/new?template=bug_report.yml) | 版本/提交、模式、最小复现、预期与实际结果 |
| 功能改进建议 | [功能表单](https://github.com/lihuipenf/DataPilot/issues/new?template=feature_request.yml) | 场景、当前障碍、验收例子与替代方案 |
| 使用、指标或配置问题 | [提问表单](https://github.com/lihuipenf/DataPilot/issues/new?template=question.yml) | 目标、合成示例、已尝试步骤 |
| 安全漏洞或潜在数据泄露 | [SECURITY.md](SECURITY.md)中的专用邮箱 | 私下提供脱敏复现，不开公开安全Issue |
| 提交代码或文档 | [CONTRIBUTING.md](CONTRIBUTING.md)与[PR入口](https://github.com/lihuipenf/DataPilot/compare) | 小范围修改、实际验证结果与限制 |

提交前请搜索[已有Issue](https://github.com/lihuipenf/DataPilot/issues)，并核对[能力边界](docs/capabilities.md)。功能请求与项目范围有关时，维护者会按影响、复现信息和可维护性评估；超出范围的建议可能不采纳。

## 保护数据

仅使用合成CSV和已脱敏日志。不要上传.env、API Key、访问令牌、完整会话SQLite、outputs目录、客户订单或可识别个人的截图。需要说明配置时提供变量名和是否设置，不粘贴密钥值。

不要为复现问题而调用不可信模型端点或发送真实销售数据。若涉及凭据泄露，先撤销/轮换，再使用私下报告渠道。普通Issue和PR在仓库公开后所有人都可查看。

## English

Use the Bug, Feature or Question form linked above. Include a version/commit, environment, synthetic reproduction and what you already tried. Report vulnerabilities privately through SECURITY.md. Do not post credentials, customer data or session databases. This is a personal project with no guaranteed response SLA.
