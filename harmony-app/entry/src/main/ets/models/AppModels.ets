export enum AppSection {
  QUICK = 0,
  CASE = 1,
  DOSSIER = 2,
  SETTINGS = 3
}

export enum ChatRole {
  SYSTEM = 'system',
  USER = 'user',
  ASSISTANT = 'assistant'
}

export class PromptSuggestion {
  title: string;
  description: string;
  prompt: string;

  constructor(title: string, description: string, prompt: string) {
    this.title = title;
    this.description = description;
    this.prompt = prompt;
  }
}

export class ChatMessage {
  role: string;
  content: string;
  citations: LawCitation[];
  apiContent: string;

  constructor(role: string, content: string, citations: LawCitation[] = [], apiContent: string = '') {
    this.role = role;
    this.content = content;
    this.citations = citations;
    this.apiContent = apiContent.length > 0 ? apiContent : content;
  }
}

export class RequestChatMessage {
  role: string;
  content: string;

  constructor(role: string, content: string) {
    this.role = role;
    this.content = content;
  }
}

export class ApiConfig {
  baseUrl: string;
  model: string;
  apiKey: string;

  constructor(baseUrl: string, model: string, apiKey: string) {
    this.baseUrl = baseUrl;
    this.model = model;
    this.apiKey = apiKey;
  }
}

export class ChatCompletionRequest {
  model: string;
  messages: RequestChatMessage[] = [];
  stream: boolean = false;

  constructor(model: string, messages: ChatMessage[]) {
    this.model = model;
    messages.forEach((message: ChatMessage) => {
      this.messages.push(new RequestChatMessage(message.role, message.apiContent));
    });
  }
}

export class FileAttachment {
  name: string;
  format: string;
  text: string;
  truncated: boolean;

  constructor(name: string = '', format: string = '', text: string = '', truncated: boolean = false) {
    this.name = name;
    this.format = format;
    this.text = text;
    this.truncated = truncated;
  }
}

export class LawChunk {
  id: string = '';
  documentId: string = '';
  title: string = '';
  article: string = '';
  category: string = '';
  subcategory: string = '';
  region: string = '全国';
  source: string = '';
  status: string = '';
  effectiveDate: string = '';
  text: string = '';
}

export class LawDocumentIndex {
  documentId: string = '';
  title: string = '';
  category: string = '';
  subcategory: string = '';
  region: string = '全国';
  source: string = '';
  status: string = '';
  effectiveDate: string = '';
}

export class LawIndexPayload {
  version: number = 0;
  sourceFileCount: number = 0;
  documentCount: number = 0;
  searchableDocumentCount: number = 0;
  metadataOnlyCount: number = 0;
  chunkCount: number = 0;
  documents: LawDocumentIndex[] = [];
  chunks: LawChunk[] = [];
}

export class LawCitation {
  id: string;
  chunkId: string;
  title: string;
  article: string;
  source: string;
  status: string;
  effectiveDate: string;
  excerpt: string;

  constructor(id: string, chunk: LawChunk) {
    this.id = id;
    this.chunkId = chunk.id;
    this.title = chunk.title;
    this.article = chunk.article;
    this.source = chunk.source;
    this.status = chunk.status;
    this.effectiveDate = chunk.effectiveDate;
    this.excerpt = chunk.text;
  }
}

export class KnowledgeResult {
  context: string;
  citations: LawCitation[];

  constructor(context: string, citations: LawCitation[]) {
    this.context = context;
    this.citations = citations;
  }
}

export class ChatCompletionMessage {
  role: string = '';
  content: string = '';
  refusal: string = '';
}

export class ChatCompletionChoice {
  index: number = 0;
  message: ChatCompletionMessage = new ChatCompletionMessage();
  finish_reason: string = '';
}

export class ChatCompletionResponse {
  id: string = '';
  choices: ChatCompletionChoice[] = [];
}

export class ApiErrorDetail {
  message: string = '';
  type: string = '';
  code: string = '';
}

export class ApiErrorResponse {
  error: ApiErrorDetail = new ApiErrorDetail();
}

export class CaseFieldInfo {
  label: string;
  hint: string;

  constructor(label: string, hint: string) {
    this.label = label;
    this.hint = hint;
  }
}
