# Security Policy / 安全政策

## 受支持版本

| 版本 | 安全维护 |
|---|---|
| 最新的 1.3.x 版本 | 支持；请优先升级到最新补丁 |
| 1.2.x、1.1.x 及更早版本 | 不再单独回补，请升级 |

## 私下报告漏洞

请发送邮件至 **[13794556292@163.com](mailto:13794556292@163.com)**，邮件主题建议为 `DataPilot 安全漏洞报告`。

这是维护者指定的安全报告邮箱。请勿在公开 Issue、PR、评论或公开附件中披露尚未修复漏洞的利用细节，也不要提交真实 API Key、访问令牌、会话数据库或客户数据。

建议包含：

- 受影响的版本或提交、Python/操作系统和启动方式。
- 影响及触发前提，例如本地单用户、共享主机或自定义模型端点。
- 使用合成数据的最小复现、相关请求或脚本，以及预期和实际行为。
- 已脱敏的日志、你希望采用的署名方式（可选）。

如已发生凭据泄露，请先撤销或轮换凭据，不要通过邮件发送仍然有效的密钥。项目由个人维护，回复和修复时间取决于问题复杂度与维护者可用时间，不承诺固定响应时限或漏洞奖励。请等待私下沟通和修复协调后再披露详细利用步骤。

邮箱是当前报告渠道；不依赖仓库可见性，也不假定 GitHub 的私下漏洞报告功能已启用。普通功能缺陷可以通过 Issue 报告，但复现仍应使用合成数据。

## 安全边界

DataPilot 面向单进程、单用户的本地使用，没有多用户身份认证。默认绑定回环地址；Docker 端口应使用 `127.0.0.1:8765:8765`。共享主机或外部部署需要额外的认证和访问控制。

上传 CSV、用户问题和模型输出均视为不可信内容。实时模式会向配置的模型服务发送必要问题、历史和工具结果；请仅使用适合发送到该服务的数据。协作式取消不能保证立即终止供应商已经接收的请求。

既有检查记录见 [v1.3 加固说明](docs/security-hardening-v1.3.md)。这些记录不构成不存在未知漏洞的保证。

## Reporting in English

Report vulnerabilities privately to **13794556292@163.com**, with the subject `DataPilot security report`. Include the affected version or commit, prerequisites, impact, and a minimal reproduction using synthetic data. Do not include working credentials or private business records, and do not publish exploit details in public issues before coordination. This is a personally maintained project with no guaranteed response SLA or bounty program.
