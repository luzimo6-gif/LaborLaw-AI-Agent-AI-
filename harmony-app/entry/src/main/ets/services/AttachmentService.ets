import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { zlib } from '@kit.BasicServicesKit';
import { fileIo, picker } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { FileAttachment } from '../models/AppModels';

const LOG_DOMAIN: number = 0x1020;
const LOG_TAG: string = 'AttachmentService';
const MAX_SOURCE_BYTES: number = 8 * 1024 * 1024;
const MAX_UNPACKED_BYTES: number = 20 * 1024 * 1024;
const MAX_TEXT_CHARS: number = 16000;

export class AttachmentService {
  static async pick(context: common.UIAbilityContext): Promise<FileAttachment> {
    const documentPicker: picker.DocumentViewPicker = new picker.DocumentViewPicker(context);
    const options: picker.DocumentSelectOptions = new picker.DocumentSelectOptions();
    options.maxSelectNumber = 1;
    options.fileSuffixFilters = ['劳动法材料|.txt,.md,.docx'];
    try {
      const uris: string[] = await documentPicker.select(options);
      if (uris.length === 0) {
        throw new Error('未选择文件');
      }
      hilog.info(LOG_DOMAIN, LOG_TAG, 'Document picker returned one URI');
      const attachment: FileAttachment = await AttachmentService.read(context, uris[0]);
      hilog.info(LOG_DOMAIN, LOG_TAG, 'Attachment ready: %{public}s', attachment.name);
      return attachment;
    } catch (error) {
      hilog.error(LOG_DOMAIN, LOG_TAG, 'Attachment failed: %{public}s',
        AttachmentService.errorDetail(error));
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('文件选择已取消或读取失败');
    }
  }

  private static async read(context: common.UIAbilityContext, uri: string): Promise<FileAttachment> {
    try {
      const name: string = AttachmentService.fileName(uri);
      const format: string = AttachmentService.extension(name);
      if (format !== 'txt' && format !== 'md' && format !== 'docx') {
        throw new Error('仅支持 TXT、MD 和 DOCX 文件');
      }
      const sourceFile: fileIo.File = await fileIo.open(uri, fileIo.OpenMode.READ_ONLY);
      let extracted: string = '';
      try {
        const stat: fileIo.Stat = await fileIo.stat(sourceFile.fd);
        if (stat.size <= 0) {
          throw new Error('所选文件为空');
        }
        if (stat.size > MAX_SOURCE_BYTES) {
          throw new Error('文件不能超过 8 MB');
        }
        if (format === 'docx') {
          extracted = await AttachmentService.readDocx(context, sourceFile.fd);
        } else {
          extracted = AttachmentService.readPlainText(sourceFile.fd, stat.size);
        }
      } finally {
        try {
          await fileIo.close(sourceFile);
        } catch (error) {
        }
      }
      const normalized: string = AttachmentService.normalizeText(extracted);
      if (normalized.length === 0) {
        throw new Error('没有从文件中读取到可用文字');
      }
      const truncated: boolean = normalized.length > MAX_TEXT_CHARS;
      const text: string = truncated ? normalized.substring(0, MAX_TEXT_CHARS) : normalized;
      return new FileAttachment(name, format.toUpperCase(), text, truncated);
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('文件读取失败');
    }
  }

  private static readPlainText(fd: number, size: number): string {
    try {
      const readLength: number = Math.min(size, MAX_TEXT_CHARS * 4 + 4);
      const buffer: ArrayBuffer = new ArrayBuffer(readLength);
      const bytesRead: number = fileIo.readSync(fd, buffer);
      return new util.TextDecoder().decodeToString(new Uint8Array(buffer, 0, bytesRead));
    } catch (error) {
      throw new Error('TXT/MD 文本读取失败');
    }
  }

  private static async readDocx(context: common.UIAbilityContext, sourceFd: number): Promise<string> {
    try {
      const workRoot: string = context.cacheDir + '/docx_' + Date.now().toString();
      const archivePath: string = workRoot + '/source.docx';
      const outputPath: string = workRoot + '/content';
      fileIo.mkdirSync(workRoot);
      fileIo.mkdirSync(outputPath);
      await fileIo.copyFile(sourceFd, archivePath);
      const unpackedSize: number = await zlib.getOriginalSize(archivePath);
      if (unpackedSize > MAX_UNPACKED_BYTES) {
        throw new Error('DOCX 解压后内容过大');
      }
      await zlib.decompressFile(archivePath, outputPath);
      const documentPath: string = outputPath + '/word/document.xml';
      const xml: string =
        await fileIo.readText(documentPath, { length: 2 * 1024 * 1024, encoding: 'utf-8' });
      try {
        fileIo.unlinkSync(archivePath);
      } catch (error) {
      }
      return AttachmentService.docxXmlToText(xml);
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('DOCX 读取失败');
    }
  }

  private static docxXmlToText(xml: string): string {
    return xml
      .replace(/<w:tab[^>]*\/>/g, '\t')
      .replace(/<w:br[^>]*\/>/g, '\n')
      .replace(/<\/w:p>/g, '\n')
      .replace(/<\/w:tr>/g, '\n')
      .replace(/<\/w:tc>/g, '\t')
      .replace(/<[^>]+>/g, '')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, '\'')
      .replace(/&amp;/g, '&');
  }

  private static normalizeText(text: string): string {
    return text
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  private static fileName(uri: string): string {
    const queryIndex: number = uri.indexOf('?');
    const cleanUri: string = queryIndex >= 0 ? uri.substring(0, queryIndex) : uri;
    const slashIndex: number = cleanUri.lastIndexOf('/');
    const encoded: string = slashIndex >= 0 ? cleanUri.substring(slashIndex + 1) : cleanUri;
    try {
      return decodeURIComponent(encoded);
    } catch (error) {
      return encoded;
    }
  }

  private static extension(name: string): string {
    const dotIndex: number = name.lastIndexOf('.');
    return dotIndex >= 0 ? name.substring(dotIndex + 1).toLowerCase() : '';
  }

  private static errorDetail(error: Object): string {
    if (error instanceof Error) {
      return error.message;
    }
    try {
      return JSON.stringify(error);
    } catch (jsonError) {
      return 'unknown error';
    }
  }
}
