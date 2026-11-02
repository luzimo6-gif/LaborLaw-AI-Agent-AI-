# 第三阶段：模型 API 接入与本机安全配置

## 目标

在不部署项目自有服务器的前提下，由 HarmonyOS 应用直接调用用户配置的
OpenAI 兼容 API，并完成配置持久化、多轮问答、案件报告和异常处理。

## 已实现

- [x] 声明 `ohos.permission.INTERNET`
- [x] OpenAI 兼容 `/chat/completions` 客户端
- [x] Base URL 自动规范化
- [x] HTTPS、模型名和 API Key 的发送前校验
- [x] Base URL、模型名使用 Preferences 本机持久化
- [x] API Key 使用 Asset Store 加密保存，不写入代码或普通首选项
- [x] 普法模式真实多轮消息链
- [x] 案件模式真实多轮消息链
- [x] 智能卷宗案件分析报告调用
- [x] 连接测试与加载状态
- [x] 认证失败、接口不存在、超时、限流、服务端错误和异常 JSON 提示
- [x] 请求结束后主动销毁 HTTP 请求对象
- [x] 无本地检索上下文时禁止模型编造法条、案例和来源

## 接口约定

- 默认 Base URL：`https://api.openai.com/v1`
- 请求路径：`{Base URL}/chat/completions`
- 认证：`Authorization: Bearer {API Key}`
- 请求类型：`application/json`
- 请求体：`model`、完整多轮 `messages`、`stream: false`
- 连接超时：15 秒
- 读取超时：60 秒

选择 Chat Completions 是为了兼容 OpenAI 以及多数第三方 OpenAI 兼容服务。
后续如只使用 OpenAI 官方接口，可以再评估迁移至 Responses API。

## 安全与隐私

1. API Key 通过 HarmonyOS Asset Store 保存，访问级别为设备首次解锁后可用，
   且禁止跨设备同步。
2. Base URL 和模型名不属于密钥，使用 Preferences 保存。
3. 仓库中没有写入真实或测试 API Key。
4. 只有用户主动点击发送、生成报告或测试连接时才会请求模型服务商。
5. 对话、案件信息和附件默认留在本机；提交时只发送本次功能需要的内容。

## 验收结果

- 日期：2026-07-25
- ArkTS/HAP 构建：`BUILD SUCCESSFUL`
- ArkTS 业务代码警告：0
- 模拟器：`LaborLawAI_API23`，HarmonyOS 6.1.0 (API 23)
- HAP 覆盖安装：成功
- 应用启动：成功
- 设置页：Base URL、模型名、密码输入、连接状态和隐私说明显示正常
- 缺配置测试：模型名为空时显示“请填写模型名称”，未发出网络请求
- 普法发送测试：缺配置时显示“请填写模型名称，请先前往设置”
- 真实 API 测试：通过
- 连接状态：`连接成功，可以开始咨询`
- 验收方式：使用者在模拟器设置页手动输入自己的 Base URL、模型 ID 和
  API Key；密钥未进入对话、代码或仓库

## 下一步

真实接口连接成功后进入第四阶段：先以 84 份全国性法律资料完成回归验证，再按
当前决定扩充为 2790 份全量本地只读索引，
实现本地检索、上下文注入、引用 ID 校验和来源展示。
