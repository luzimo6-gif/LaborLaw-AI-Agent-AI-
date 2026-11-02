import { http } from '@kit.NetworkKit';
import {
  ApiConfig,
  ApiErrorResponse,
  ChatCompletionRequest,
  ChatCompletionResponse,
  ChatMessage
} from '../models/AppModels';

class RequestHeaders {
  Authorization: string;
  'Content-Type': string = 'application/json';

  constructor(apiKey: string) {
    this.Authorization = 'Bearer ' + apiKey;
  }
}

export class AiApiClient {
  static validateConfig(config: ApiConfig): string {
    if (config.baseUrl.trim().length === 0) {
      return '请填写 Base URL';
    }
    if (!config.baseUrl.trim().startsWith('https://')) {
      return 'Base URL 必须使用 HTTPS';
    }
    if (config.model.trim().length === 0) {
      return '请填写模型名称';
    }
    if (config.apiKey.trim().length === 0) {
      return '请填写 API Key';
    }
    return '';
  }

  static completionUrl(baseUrl: string): string {
    let normalized: string = baseUrl.trim();
    while (normalized.endsWith('/')) {
      normalized = normalized.substring(0, normalized.length - 1);
    }
    if (normalized.endsWith('/chat/completions')) {
      return normalized;
    }
    return normalized + '/chat/completions';
  }

  static async send(config: ApiConfig, messages: ChatMessage[]): Promise<string> {
    const validationError: string = AiApiClient.validateConfig(config);
    if (validationError.length > 0) {
      throw new Error(validationError);
    }

    const request: http.HttpRequest = http.createHttp();
    const body: ChatCompletionRequest = new ChatCompletionRequest(config.model.trim(), messages);
    const headers: RequestHeaders = new RequestHeaders(config.apiKey.trim());

    try {
      const response: http.HttpResponse = await request.request(AiApiClient.completionUrl(config.baseUrl), {
        method: http.RequestMethod.POST,
        header: headers,
        extraData: JSON.stringify(body),
        expectDataType: http.HttpDataType.STRING,
        usingCache: false,
        connectTimeout: 15000,
        readTimeout: 60000
      });
      const raw: string = response.result as string;
      const statusCode: number = response.responseCode as number;

      if (statusCode < 200 || statusCode >= 300) {
        throw new Error(AiApiClient.httpErrorMessage(statusCode, raw));
      }

      let parsed: ChatCompletionResponse;
      try {
        parsed = JSON.parse(raw) as ChatCompletionResponse;
      } catch (error) {
        throw new Error('模型返回了无法解析的数据');
      }

      if (parsed.choices.length === 0 || parsed.choices[0].message === undefined) {
        throw new Error('模型响应中没有可显示的回答');
      }
      const answer: string = parsed.choices[0].message.content;
      if (answer !== undefined && answer.trim().length > 0) {
        return answer.trim();
      }
      const refusal: string = parsed.choices[0].message.refusal;
      if (refusal !== undefined && refusal.trim().length > 0) {
        return refusal.trim();
      }
      throw new Error('模型返回了空回答');
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('网络请求失败，请检查网络和接口配置');
    } finally {
      request.destroy();
    }
  }

  private static httpErrorMessage(statusCode: number, raw: string): string {
    let serverMessage: string = '';
    try {
      const parsed: ApiErrorResponse = JSON.parse(raw) as ApiErrorResponse;
      if (parsed.error !== undefined && parsed.error.message !== undefined) {
        serverMessage = parsed.error.message.trim();
      }
    } catch (error) {
      serverMessage = '';
    }

    if (statusCode === 401 || statusCode === 403) {
      return '认证失败，请检查 API Key';
    }
    if (statusCode === 404) {
      return '接口或模型不存在，请检查 Base URL 和模型名称';
    }
    if (statusCode === 408) {
      return '请求超时，请稍后重试';
    }
    if (statusCode === 429) {
      return '请求过于频繁或额度不足';
    }
    if (statusCode >= 500) {
      return '模型服务暂时不可用（' + statusCode.toString() + '）';
    }
    if (serverMessage.length > 0) {
      return '接口错误：' + serverMessage;
    }
    return '接口请求失败（HTTP ' + statusCode.toString() + '）';
  }
}
